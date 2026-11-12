import json
import re
import sqlite3
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

from core import Library, ROOT, now, sha256_file
from tagging import Catalog

VISUAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS visual_vectors (
    item_id TEXT PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    vector_json TEXT NOT NULL
);
"""


def visual_vector(path):
    with Image.open(path) as source:
        image = source.convert("RGB")
        hist = np.concatenate([np.histogram(np.asarray(image)[:, :, channel], bins=16, range=(0, 256))[0]
                               for channel in range(3)]).astype(np.float32)
        hist /= max(1.0, float(hist.sum()))
        layout = np.asarray(image.resize((8, 8)).convert("L"), dtype=np.float32) / 255.0
        layout = layout.flatten()
        layout = (layout - layout.mean()) / max(0.01, float(layout.std()))
        hist_norm = np.linalg.norm(hist)
        layout_norm = np.linalg.norm(layout)
        vector = np.concatenate([hist / max(hist_norm, 1e-9), layout / max(layout_norm, 1e-9)])
        return vector / max(1e-9, float(np.linalg.norm(vector)))


class Maintenance:
    def __init__(self, library, catalog):
        self.library = library
        self.catalog = catalog
        with self.library.connect() as conn:
            conn.executescript(VISUAL_SCHEMA)

    def build_visual_index(self, regenerate=False):
        indexed = []
        errors = []
        for item in self.library.list_items(100000):
            asset = next((a for a in item["assets"] if a["kind"] == "cover" and a["status"] == "ready"), None)
            if not asset:
                continue
            if regenerate:
                exists = False
            else:
                with self.library.connect() as conn:
                    exists = conn.execute("SELECT 1 FROM visual_vectors WHERE item_id=?", (item["id"],)).fetchone() is not None
            if exists:
                continue
            try:
                vector = visual_vector(self.library.data_dir / asset["local_path"])
                with self.library.connect() as conn:
                    conn.execute("INSERT INTO visual_vectors(item_id,provider,vector_json) VALUES(?,?,?) ON CONFLICT(item_id) DO UPDATE SET provider=excluded.provider,vector_json=excluded.vector_json",
                                 (item["id"], "color_layout_v1", json.dumps(vector.tolist())))
                indexed.append(item["id"])
            except Exception as exc:
                errors.append({"item_id": item["id"], "error": str(exc)})
        return {"indexed": len(indexed), "errors": errors, "provider": "color_layout_v1"}

    def visual_search(self, item_id, tags=None, match="all", exclude=None, platform="", collection="", limit=10):
        item = self.library.get_item(item_id)
        if not item:
            raise KeyError("素材不存在: " + item_id)
        with self.library.connect() as conn:
            row = conn.execute("SELECT vector_json FROM visual_vectors WHERE item_id=?", (item_id,)).fetchone()
        if not row:
            result = self.build_visual_index()
            with self.library.connect() as conn:
                row = conn.execute("SELECT vector_json FROM visual_vectors WHERE item_id=?", (item_id,)).fetchone()
        if not row:
            raise ValueError("该素材没有可用的封面视觉索引")
        query = np.asarray(json.loads(row[0]), dtype=np.float32)
        candidates = self.catalog.structured_ids(tags, match, exclude, platform, collection)
        candidate_ids = [value[0] for value in candidates]
        scores = []
        if candidate_ids:
            placeholders = ",".join("?" for _ in candidate_ids)
            with self.library.connect() as conn:
                rows = conn.execute("SELECT item_id,vector_json FROM visual_vectors WHERE item_id IN (" + placeholders + ")", candidate_ids).fetchall()
            for row in rows:
                vector = np.asarray(json.loads(row["vector_json"]), dtype=np.float32)
                scores.append((row["item_id"], max(0.0, float(np.dot(query, vector)))))
        scores.sort(key=lambda value: (-value[1], value[0]))
        items = []
        for candidate_id, score in scores[:limit]:
            found = self.library.get_item(candidate_id)
            found["visual_score"] = round(score, 4)
            items.append(found)
        return {"source_id": item_id, "items": items, "total": len(scores), "provider": "color_layout_v1"}

    def health_check(self):
        issues = []
        for item in self.library.list_items(100000):
            if item["import_status"] != "ready":
                issues.append({"type": "import_status", "item_id": item["id"], "detail": item["import_status"]})
            for asset in item["assets"]:
                if asset["status"] != "ready":
                    issues.append({"type": "asset_status", "item_id": item["id"], "detail": asset["error"]})
                    continue
                path = self.library.data_dir / asset["local_path"]
                if not path.is_file():
                    issues.append({"type": "missing_asset", "item_id": item["id"], "detail": asset["local_path"]})
                elif asset["sha256"] and sha256_file(path) != asset["sha256"]:
                    issues.append({"type": "asset_checksum", "item_id": item["id"], "detail": asset["local_path"]})
            if not item["cover_local"]:
                issues.append({"type": "missing_cover", "item_id": item["id"], "detail": "没有本地封面"})
        with self.library.connect() as conn:
            duplicate_urls = conn.execute("SELECT platform,url,COUNT(*) AS count FROM items WHERE url!='' GROUP BY platform,url HAVING count>1").fetchall()
            semantic_missing = conn.execute("SELECT COUNT(*) FROM items LEFT JOIN vectors ON items.id=vectors.item_id WHERE vectors.item_id IS NULL").fetchone()[0]
            visual_missing = conn.execute("SELECT COUNT(*) FROM assets LEFT JOIN visual_vectors ON assets.item_id=visual_vectors.item_id WHERE assets.kind='cover' AND assets.status='ready' AND visual_vectors.item_id IS NULL").fetchone()[0]
        duplicates = [{"platform": r["platform"], "url": r["url"], "count": r["count"]} for r in duplicate_urls]
        return {"ok": not issues and not duplicates, "issues": issues, "duplicate_urls": duplicates,
                "semantic_vectors_missing": semantic_missing, "visual_vectors_missing": visual_missing,
                "stats": self.library.stats()}

    def reindex_all(self):
        ids = [item["id"] for item in self.library.list_items(100000)]
        for item_id in ids:
            self.library.reindex_item(item_id)
            self.catalog.update_vector(item_id)
        visual = self.build_visual_index(regenerate=True)
        return {"items": len(ids), "visual": visual}

    def backup(self, output=None):
        with self.library.connect() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        if output:
            target = Path(output).expanduser().resolve()
        else:
            target = ROOT / "backups" / ("inspiration_" + re.sub(r"[^0-9]", "", now())[:14] + ".zip")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise ValueError("备份文件已存在，请使用新文件名: " + str(target))
        manifest = {"version": 1, "created_at": now(), "items": self.library.stats()["items"]}
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("inspiration_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for path in sorted(self.library.data_dir.rglob("*")):
                if path.is_file() and not path.name.endswith(("-wal", "-shm")):
                    archive.write(path, path.relative_to(self.library.data_dir))
        return {"path": str(target), "bytes": target.stat().st_size, "manifest": manifest}

    def restore(self, archive, target_dir):
        archive = Path(archive).expanduser().resolve()
        target = Path(target_dir).expanduser().resolve()
        if target.exists() and any(target.iterdir()):
            raise ValueError("恢复目录必须为空，拒绝覆盖现有数据")
        with zipfile.ZipFile(archive) as package:
            names = package.namelist()
            if "inspiration_manifest.json" not in names or "library.sqlite3" not in names:
                raise ValueError("备份缺少清单或数据库")
            for name in names:
                path = Path(name)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("备份包含不安全路径")
            package.extractall(target)
        restored = Library(target)
        catalog = Catalog(restored)
        health = self.__class__(restored, catalog).health_check()
        return {"ok": True, "data_dir": str(target), "stats": restored.stats(), "health": health}
