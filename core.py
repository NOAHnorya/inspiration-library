import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = ROOT / "data"
SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    native_id TEXT,
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    collection TEXT NOT NULL DEFAULT '',
    cover_url TEXT NOT NULL DEFAULT '',
    source_json TEXT NOT NULL DEFAULT '{}',
    annotation_json TEXT NOT NULL DEFAULT '{}',
    notes TEXT NOT NULL DEFAULT '',
    import_status TEXT NOT NULL DEFAULT 'ready',
    search_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_platform ON items(platform);
CREATE INDEX IF NOT EXISTS idx_items_collection ON items(collection);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(import_status);
CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    original_url TEXT NOT NULL DEFAULT '',
    local_path TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    UNIQUE(item_id, kind)
);
CREATE TABLE IF NOT EXISTS tags (
    name TEXT PRIMARY KEY,
    category TEXT NOT NULL DEFAULT '自定义',
    aliases_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS item_tags (
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    name TEXT NOT NULL REFERENCES tags(name) ON DELETE CASCADE,
    source TEXT NOT NULL DEFAULT 'auto',
    confidence REAL NOT NULL DEFAULT 1.0,
    locked INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(item_id, name)
);
CREATE INDEX IF NOT EXISTS idx_item_tags_name ON item_tags(name);
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_value TEXT NOT NULL,
    status TEXT NOT NULL,
    item_id TEXT,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS groups (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS group_items (
    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    PRIMARY KEY(group_id, item_id)
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(id UNINDEXED, content, tokenize='trigram');
"""


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_url(url):
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("仅支持有效的 http/https URL")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"spm", "fbclid", "gclid"}]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/") or "/", urlencode(query), ""))


def web_id(url):
    return "ins_web_" + sha256_bytes(normalize_url(url).encode())[:20]


def safe_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class PageMetadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = {}
        self.title_parts = []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag != "meta":
            return
        key = attrs.get("property") or attrs.get("name") or attrs.get("itemprop")
        content = attrs.get("content")
        if key and content:
            self.meta[key.lower()] = content.strip()

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)

    def value(self, *keys):
        for key in keys:
            if self.meta.get(key):
                return self.meta[key]
        return ""

    @property
    def title(self):
        return "".join(self.title_parts).strip()


class Library:
    def __init__(self, data_dir=None):
        self.data_dir = Path(data_dir or os.environ.get("INSPIRATION_DATA_DIR", DEFAULT_DATA_DIR)).expanduser().resolve()
        self.items_dir = self.data_dir / "items"
        self.db_path = self.data_dir / "library.sqlite3"
        self.items_dir.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def item_dir(self, item_id):
        path = self.items_dir / item_id
        (path / "assets").mkdir(parents=True, exist_ok=True)
        return path

    def write_item_files(self, item_id):
        item = self.get_item(item_id)
        if not item:
            raise KeyError("素材不存在: " + item_id)
        directory = self.item_dir(item_id)
        (directory / "source.json").write_text(json.dumps(item["source"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (directory / "annotation.json").write_text(json.dumps(item["annotation"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def upsert_item(self, item):
        item_id = item["id"]
        if not re.fullmatch(r"ins_[a-z0-9_]+_[A-Za-z0-9_-]+", item_id):
            raise ValueError("非法素材 ID")
        timestamp = now()
        source = item.get("source", {})
        annotation = item.get("annotation", {})
        with self.connect() as conn:
            exists = conn.execute("SELECT 1 FROM items WHERE id=?", (item_id,)).fetchone()
            conn.execute("""
                INSERT INTO items(id,platform,native_id,title,author,url,collection,cover_url,source_json,annotation_json,notes,import_status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    platform=excluded.platform,native_id=excluded.native_id,title=excluded.title,
                    author=excluded.author,url=excluded.url,collection=excluded.collection,
                    cover_url=excluded.cover_url,source_json=excluded.source_json,
                    import_status=excluded.import_status,updated_at=excluded.updated_at
            """, (
                item_id, item["platform"], item.get("native_id"), item.get("title") or "未命名素材",
                item.get("author", ""), item.get("url", ""), item.get("collection", ""),
                item.get("cover_url", ""), safe_json(source), safe_json(annotation),
                item.get("notes", ""), item.get("import_status", "ready"),
                timestamp if not exists else conn.execute("SELECT created_at FROM items WHERE id=?", (item_id,)).fetchone()[0],
                timestamp,
            ))
        self.write_item_files(item_id)
        self.reindex_item(item_id)
        return item_id

    def record_import(self, source_type, source_value, status, item_id=None, error=""):
        with self.connect() as conn:
            conn.execute("INSERT INTO imports(source_type,source_value,status,item_id,error,created_at) VALUES(?,?,?,?,?,?)",
                         (source_type, source_value, status, item_id, error, now()))

    def record_asset(self, item_id, kind, local_path, original_url="", sha256="", status="ready", error=""):
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO assets(item_id,kind,original_url,local_path,sha256,status,error)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(item_id,kind) DO UPDATE SET original_url=excluded.original_url,
                    local_path=excluded.local_path,sha256=excluded.sha256,status=excluded.status,error=excluded.error
            """, (item_id, kind, original_url, local_path, sha256, status, error))

    def download_asset(self, item_id, url, kind="cover"):
        if not url:
            self.record_asset(item_id, kind, "", status="missing", error="没有可下载的封面 URL")
            return None
        directory = self.item_dir(item_id) / "assets"
        try:
            response = httpx.get(url, follow_redirects=True, timeout=25, headers={"User-Agent": "Mozilla/5.0 InspirationLibrary/1.0"})
            response.raise_for_status()
            content = response.content
            if len(content) > 25 * 1024 * 1024:
                raise ValueError("资产超过 25 MB")
            if kind == "cover":
                from io import BytesIO
                with Image.open(BytesIO(content)) as image:
                    extension = (image.format or "PNG").lower()
                    image.verify()
                if extension == "jpeg":
                    extension = "jpg"
                extension = re.sub(r"[^a-z0-9]", "", extension) or "img"
            else:
                extension = Path(urlsplit(url).path).suffix.lstrip(".") or "bin"
            filename = kind + "." + extension
            target = directory / filename
            target.write_bytes(content)
            relative = str(target.relative_to(self.data_dir))
            self.record_asset(item_id, kind, relative, url, sha256_bytes(content))
            return relative
        except Exception as exc:
            self.record_asset(item_id, kind, "", url, status="needs_review", error=str(exc))
            return None

    def import_xhs(self, path, download=True):
        source_path = Path(path).expanduser().resolve()
        records = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            raise ValueError("小红书导入文件必须是 JSON 数组")
        results = []
        for record in records:
            source_value = str(source_path) + "#" + str(record.get("url", ""))
            try:
                url = record["url"]
                match = re.search(r"/([0-9a-f]{24})/?$", urlsplit(url).path)
                if not match:
                    raise ValueError("链接中缺少有效笔记 ID")
                native_id = match.group(1)
                item_id = "ins_xhs_" + native_id
                self.upsert_item({
                    "id": item_id, "platform": "xiaohongshu", "native_id": native_id,
                    "title": record.get("title") or "未命名素材", "author": record.get("author", ""),
                    "url": url, "collection": record.get("collection", ""),
                    "cover_url": record.get("cover", ""), "source": record,
                    "import_status": "ready",
                })
                asset = self.download_asset(item_id, record.get("cover", "")) if download else None
                if not download:
                    asset = next((a["local_path"] for a in self.get_item(item_id)["assets"]
                                  if a["kind"] == "cover" and a["status"] == "ready"), None)
                if record.get("cover") and not asset:
                    with self.connect() as conn:
                        conn.execute("UPDATE items SET import_status='needs_review',updated_at=? WHERE id=?", (now(), item_id))
                    self.record_import("xiaohongshu", source_value, "needs_review", item_id, "封面下载失败" if download else "封面尚未本地化")
                    results.append({"id": item_id, "status": "needs_review"})
                else:
                    self.record_import("xiaohongshu", source_value, "ready", item_id)
                    results.append({"id": item_id, "status": "ready"})
            except Exception as exc:
                self.record_import("xiaohongshu", source_value, "failed", error=str(exc))
                results.append({"status": "failed", "error": str(exc), "url": record.get("url", "")})
        return results

    def import_douyin(self, path, download=True):
        source_path = Path(path).expanduser().resolve()
        records = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            raise ValueError("抖音导入文件必须是 JSON 数组")
        results = []
        for record in records:
            source_value = str(source_path) + "#" + str(record.get("url", ""))
            try:
                url = record["url"]
                match = re.search(r"/(?:video|note)/(\d+)/?$", urlsplit(url).path)
                if not match:
                    raise ValueError("链接中缺少有效抖音作品 ID")
                native_id = match.group(1)
                item_id = "ins_douyin_" + native_id
                self.upsert_item({
                    "id": item_id, "platform": "douyin", "native_id": native_id,
                    "title": record.get("title") or "未命名素材", "author": record.get("author", ""),
                    "url": url, "collection": record.get("collection", ""),
                    "cover_url": record.get("cover", ""), "source": record,
                    "import_status": "ready",
                })
                asset = self.download_asset(item_id, record.get("cover", "")) if download else None
                if not download:
                    asset = next((a["local_path"] for a in self.get_item(item_id)["assets"]
                                  if a["kind"] == "cover" and a["status"] == "ready"), None)
                if record.get("cover") and not asset:
                    with self.connect() as conn:
                        conn.execute("UPDATE items SET import_status='needs_review',updated_at=? WHERE id=?", (now(), item_id))
                    self.record_import("douyin", source_value, "needs_review", item_id, "封面下载失败" if download else "封面尚未本地化")
                    results.append({"id": item_id, "status": "needs_review"})
                else:
                    self.record_import("douyin", source_value, "ready", item_id)
                    results.append({"id": item_id, "status": "ready"})
            except Exception as exc:
                self.record_import("douyin", source_value, "failed", error=str(exc))
                results.append({"status": "failed", "error": str(exc), "url": record.get("url", "")})
        return results

    def import_url(self, url, download=True):
        normalized = normalize_url(url)
        item_id = web_id(normalized)
        hostname = urlsplit(normalized).hostname or "web"
        platform = next((name for name, domain in [("behance", "behance.net"), ("dribbble", "dribbble.com"), ("pinterest", "pinterest.")]
                        if domain in hostname), "web")
        metadata = {}
        error = ""
        content = ""
        try:
            response = httpx.get(normalized, follow_redirects=True, timeout=25,
                                 headers={"User-Agent": "Mozilla/5.0 InspirationLibrary/1.0"})
            response.raise_for_status()
            if len(response.content) > 15 * 1024 * 1024:
                raise ValueError("页面超过 15 MB，未读取")
            content = response.text
            if re.search(r"captcha|安全验证|人机验证|verify you are human", content, re.I):
                raise PermissionError("页面要求验证，已停止读取")
        except Exception as exc:
            error = str(exc)
        parser = PageMetadata()
        if content:
            parser.feed(content)
            metadata = parser.meta
        title = parser.value("og:title", "twitter:title") or parser.title or hostname
        author = parser.value("author", "article:author", "og:site_name")
        cover = parser.value("og:image", "og:image:url", "twitter:image", "twitter:image:src")
        if cover:
            cover = urljoin(normalized, cover)
        status = "needs_review" if error or not content else "ready"
        self.upsert_item({
            "id": item_id, "platform": platform, "title": title, "author": author,
            "url": normalized, "cover_url": cover,
            "source": {"url": normalized, "title": title, "author": author, "cover": cover,
                       "description": parser.value("description", "og:description"), "fetch_error": error},
            "import_status": status,
        })
        asset = self.download_asset(item_id, cover) if download and content else None
        if error or (download and cover and content and not asset):
            status = "needs_review"
            with self.connect() as conn:
                conn.execute("UPDATE items SET import_status='needs_review',updated_at=? WHERE id=?", (now(), item_id))
        self.record_import("url", normalized, status, item_id, error or ("封面下载失败" if cover and content and download and not asset else ""))
        return {"id": item_id, "status": status, "title": title, "error": error}

    def import_file(self, path):
        source_path = Path(path).expanduser().resolve()
        if not source_path.is_file():
            raise ValueError("文件不存在: " + str(source_path))
        digest = sha256_file(source_path)
        item_id = "ins_file_" + digest[:20]
        title = source_path.stem
        self.upsert_item({
            "id": item_id, "platform": "file", "title": title, "url": source_path.as_uri(),
            "source": {"name": source_path.name, "original_path": str(source_path), "sha256": digest},
            "import_status": "ready",
        })
        suffix = source_path.suffix.lower().lstrip(".") or "bin"
        target = self.item_dir(item_id) / "assets" / ("source." + suffix)
        if not target.exists() or sha256_file(target) != digest:
            shutil.copyfile(source_path, target)
        is_image = False
        try:
            with Image.open(target) as image:
                image.verify()
            is_image = True
        except Exception:
            pass
        kind = "cover" if is_image else "attachment"
        relative = str(target.relative_to(self.data_dir))
        self.record_asset(item_id, kind, relative, source_path.as_uri(), digest)
        self.record_import("file", str(source_path), "ready", item_id)
        return {"id": item_id, "status": "ready", "title": title, "kind": kind}

    def reindex_item(self, item_id):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            if not row:
                return
            annotation = json.loads(row["annotation_json"] or "{}")
            tags = [r[0] for r in conn.execute("SELECT name FROM item_tags WHERE item_id=?", (item_id,))]
            values = [row["title"], row["author"], row["collection"], row["platform"], row["notes"], row["url"]]
            values.extend(tags)
            for key in ["summary", "styles", "colors", "composition", "themes", "formats", "use_cases", "moods", "innovation"]:
                value = annotation.get(key, "")
                values.append(" ".join(value) if isinstance(value, list) else str(value))
            text = "\n".join(v for v in values if v)
            conn.execute("UPDATE items SET search_text=?,updated_at=? WHERE id=?", (text, now(), item_id))
            conn.execute("DELETE FROM items_fts WHERE id=?", (item_id,))
            conn.execute("INSERT INTO items_fts(id,content) VALUES(?,?)", (item_id, text))

    def get_item(self, item_id):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            if not row:
                return None
            assets = [dict(r) for r in conn.execute("SELECT * FROM assets WHERE item_id=?", (item_id,))]
            tags = [dict(r) for r in conn.execute("SELECT item_tags.*,tags.category FROM item_tags JOIN tags USING(name) WHERE item_id=? ORDER BY tags.category,name", (item_id,))]
        result = dict(row)
        result["source"] = json.loads(result.pop("source_json") or "{}")
        result["annotation"] = json.loads(result.pop("annotation_json") or "{}")
        result["assets"] = assets
        result["tags"] = tags
        result["tag_names"] = [tag["name"] for tag in tags]
        cover = next((a for a in assets if a["kind"] == "cover" and a["status"] == "ready"), None)
        result["cover_local"] = cover["local_path"] if cover else ""
        result["cover"] = "/assets/" + cover["local_path"] if cover else result["cover_url"]
        return result

    def list_items(self, limit=100, offset=0):
        with self.connect() as conn:
            rows = conn.execute("SELECT id FROM items ORDER BY created_at DESC,id LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return [self.get_item(row["id"]) for row in rows]

    def list_imports(self, limit=100):
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM imports ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def stats(self):
        with self.connect() as conn:
            return {
                "items": conn.execute("SELECT COUNT(*) FROM items").fetchone()[0],
                "ready": conn.execute("SELECT COUNT(*) FROM items WHERE import_status='ready'").fetchone()[0],
                "needs_review": conn.execute("SELECT COUNT(*) FROM items WHERE import_status='needs_review'").fetchone()[0],
                "assets": conn.execute("SELECT COUNT(*) FROM assets WHERE status='ready'").fetchone()[0],
                "tags": conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0],
                "groups": conn.execute("SELECT COUNT(*) FROM groups").fetchone()[0],
            }
