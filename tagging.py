import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from core import now, safe_json

TAXONOMY = {
    "风格": {
        "Y2K": ["y2k", "千禧"], "复古": ["复古", "retro"], "极简": ["极简", "minimal"],
        "复古未来主义": ["复古未来", "retro futur"], "法式": ["法式"], "像素风": ["像素"],
        "赛博朋克": ["赛博朋克", "cyberpunk"], "废土科幻": ["废土"], "梦幻": ["梦幻", "童话"],
    },
    "配色": {
        "黑白": ["黑白"], "高饱和": ["高饱和"], "柔和粉彩": ["粉彩", "柔和配色"],
        "暗色调": ["暗调"], "多彩": ["多彩"], "暖色": ["暖色"], "冷色": ["冷色"],
    },
    "构图": {
        "网格": ["网格", "grid"], "居中": ["居中"], "大留白": ["留白"],
        "拼贴": ["拼贴", "collage"], "卡片式": ["卡片"], "分栏": ["分栏"],
        "全屏视觉": ["全屏", "fullscreen"], "文字环绕": ["文字环绕"],
    },
    "主题": {
        "AI": ["ai", "人工智能"], "3D": ["3d", "三维"], "游戏": ["游戏", "game"],
        "编程": ["编程", "coding", "codex", "claude", "gpt"], "设计": ["设计", "design"],
        "视频": ["视频", "影片", "vlog", "mv"], "音乐": ["音乐", "music"],
        "空间设计": ["空间设计", "室内", "建筑"], "时尚": ["时尚", "穿搭"],
        "开源": ["开源"], "黑客松": ["黑客松", "hacker house", "hackathon"],
        "工作流": ["工作流", "workflow"], "创业": ["创业", "变现", "用户增长"],
    },
    "形式": {
        "网页": ["网页", "网站", "web", "html"], "PPT": ["ppt"], "海报": ["海报"],
        "视频": ["视频", "影片", "vlog", "mv"], "教程": ["教程", "攻略", "指南"],
        "工具": ["工具", "skill", "插件", "api"], "应用": ["app", "应用"],
        "作品集": ["作品集"], "书籍": ["画册", "书籍"], "项目复盘": ["复盘", "总结", "上线"],
    },
    "适用场景": {
        "落地页": ["落地页", "landing page"], "品牌视觉": ["品牌", "branding"],
        "开发者工具": ["开发者", "开发者工具", "vibe coding", "codex", "claude"],
        "作品集": ["作品集"], "演示文稿": ["演示文稿", "ppt"], "社交内容": ["社媒", "社交媒体"],
        "游戏设计": ["游戏设计", "gamejam", "游戏黑客松"], "UI设计": ["ui", "交互", "首页"],
    },
    "情绪气质": {
        "极客": ["极客", "hacker"], "活泼": ["活泼", "可爱"], "高级": ["高级", "奢华"],
        "实验性": ["实验", "实验性"], "未来感": ["未来", "科幻"], "惊悚": ["惊悚", "惊吓"],
        "温馨": ["温馨", "生日"], "艺术感": ["艺术", "审美"],
    },
}
ALIASES = {}
for category, tags in TAXONOMY.items():
    for name, aliases in tags.items():
        for alias in aliases + [name]:
            ALIASES[alias.lower()] = name

VECTOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS vectors (
    item_id TEXT PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    vector_json TEXT NOT NULL
);
"""


def contains(text, term):
    term = term.lower()
    if re.fullmatch(r"[a-z0-9_+.-]+", term):
        return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None
    return term in text


def normalize_tag(name):
    cleaned = re.sub(r"\s+", " ", name.strip())
    for tags in TAXONOMY.values():
        for canonical in tags:
            if cleaned.lower() == canonical.lower():
                return canonical
    return ALIASES.get(cleaned.lower(), cleaned)


SEMANTIC_GROUPS = [
    ["个人", "私人"], ["收入", "月薪", "年入", "薪资"], ["职业", "职场", "工作", "人生选择"],
    ["访谈", "对话", "采访"], ["免费", "白嫖"], ["资源", "资料"], ["获奖", "冠军"],
    ["短片", "视频", "影片"], ["网站", "网页"], ["项目", "作品"],
]


def text_vector(text, dimensions=1024):
    normalized = text.lower()
    for alias, canonical in ALIASES.items():
        if contains(normalized, alias):
            normalized += " " + canonical.lower()
    for group in SEMANTIC_GROUPS:
        if any(contains(normalized, term) for term in group):
            normalized += " " + " ".join(group)
    normalized = re.sub(r"\s+", " ", normalized)
    features = re.findall(r"[a-z0-9_+.-]+", normalized)
    compact = re.sub(r"\s+", "", normalized)
    features.extend(compact[i:i + size] for size in (2, 3) for i in range(max(0, len(compact) - size + 1)))
    vector = np.zeros(dimensions, dtype=np.float32)
    for feature in features:
        digest = hashlib.blake2b(feature.encode(), digest_size=4).digest()
        index = int.from_bytes(digest, "big") % dimensions
        vector[index] += 1.0
    norm = float(np.linalg.norm(vector))
    if norm:
        vector /= norm
    return vector


def term_lexical(term, text):
    if term in text:
        return 1.0
    if len(term) < 4 or not re.search(r"[\u3400-\u9fff]", term):
        return 0.0
    features = {term[i:i + size] for size in (2, 3) for i in range(len(term) - size + 1)}
    coverage = sum(feature in text for feature in features) / max(1, len(features))
    return coverage * 0.9 if coverage >= 0.35 else 0.0


class Catalog:
    def __init__(self, library):
        self.library = library
        with self.library.connect() as conn:
            conn.executescript(VECTOR_SCHEMA)

    def ensure_tag(self, name, category="自定义", aliases=None):
        name = normalize_tag(name)
        if not name:
            raise ValueError("标签不能为空")
        for known_category, values in TAXONOMY.items():
            if name in values:
                category = known_category
                aliases = sorted(set((aliases or []) + values[name]))
                break
        with self.library.connect() as conn:
            conn.execute("""
                INSERT INTO tags(name,category,aliases_json,created_at) VALUES(?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET category=excluded.category,aliases_json=excluded.aliases_json
            """, (name, category, safe_json(aliases or []), now()))
        return name

    def visual_tags(self, item):
        path = next((a for a in item["assets"] if a["kind"] == "cover" and a["status"] == "ready"), None)
        if not path:
            return []
        try:
            with Image.open(self.library.data_dir / path["local_path"]) as source:
                image = source.convert("RGB")
                image.thumbnail((80, 80))
                pixels = np.asarray(image, dtype=np.float32) / 255.0
                maximum = pixels.max(axis=2)
                minimum = pixels.min(axis=2)
                saturation = np.divide(maximum - minimum, maximum, out=np.zeros_like(maximum), where=maximum > 0)
                brightness = float(maximum.mean())
                sat = float(saturation.mean())
                tags = []
                if brightness < 0.32:
                    tags.append(("暗色调", 0.9))
                if brightness > 0.72:
                    tags.append(("明亮", 0.85))
                if sat > 0.48:
                    tags.append(("高饱和", 0.9))
                if sat < 0.13:
                    tags.append(("黑白", 0.8))
                elif brightness > 0.65 and sat < 0.32:
                    tags.append(("柔和粉彩", 0.8))
                quantized = image.quantize(colors=5)
                palette = quantized.getpalette()
                counts = sorted(quantized.getcolors() or [], reverse=True)
                hues = []
                for count, index in counts[:3]:
                    rgb = np.array(palette[index * 3:index * 3 + 3], dtype=np.float32) / 255.0
                    mx, mn = rgb.max(), rgb.min()
                    if mx == mn:
                        continue
                    if mx == rgb[0]:
                        hue = ((rgb[1] - rgb[2]) / (mx - mn)) % 6
                    elif mx == rgb[1]:
                        hue = (rgb[2] - rgb[0]) / (mx - mn) + 2
                    else:
                        hue = (rgb[0] - rgb[1]) / (mx - mn) + 4
                    hues.append(hue / 6)
                if hues and sum(h < 0.17 or h > 0.92 for h in hues) >= 2:
                    tags.append(("暖色", 0.7))
                if hues and sum(0.45 <= h <= 0.75 for h in hues) >= 2:
                    tags.append(("冷色", 0.7))
                if len(set(round(h, 1) for h in hues)) >= 3:
                    tags.append(("多彩", 0.65))
                return [(name, confidence) for name, confidence in tags]
        except Exception:
            return []

    def auto_annotate(self, item_id, regenerate=False):
        item = self.library.get_item(item_id)
        if not item:
            raise KeyError("素材不存在: " + item_id)
        annotation = dict(item["annotation"])
        if annotation and not regenerate:
            self.update_vector(item_id)
            return item
        text = "\n".join([item["title"], item["author"], item["collection"], item["source"].get("description", "")]).lower()
        assigned = {}
        for category, tags in TAXONOMY.items():
            for name, aliases in tags.items():
                if any(contains(text, alias) for alias in aliases + [name]):
                    assigned[name] = (category, 0.9 if name in text.lower() else 0.82)
        for name, confidence in self.visual_tags(item):
            self.ensure_tag(name, "配色")
            assigned[name] = ("配色", confidence)
        existing = {tag["name"]: tag for tag in item["tags"]}
        for name, (category, confidence) in assigned.items():
            self.ensure_tag(name, category)
            old = existing.get(name)
            if old and (old["locked"] or old["source"] == "manual"):
                continue
            with self.library.connect() as conn:
                conn.execute("INSERT INTO item_tags(item_id,name,source,confidence,locked) VALUES(?,?,?,?,0) ON CONFLICT(item_id,name) DO UPDATE SET source='auto',confidence=excluded.confidence",
                             (item_id, name, "auto", confidence))
        with self.library.connect() as conn:
            for name, tag in existing.items():
                if tag["source"] == "auto" and not tag["locked"] and name not in assigned:
                    conn.execute("DELETE FROM item_tags WHERE item_id=? AND name=?", (item_id, name))
        manual_fields = set(annotation.get("manual_fields", []))
        grouped = {key: [] for key in ["styles", "colors", "composition", "themes", "formats", "use_cases", "moods"]}
        mapping = dict(zip(["风格", "配色", "构图", "主题", "形式", "适用场景", "情绪气质"], grouped))
        for name, (category, _) in assigned.items():
            grouped[mapping[category]].append(name)
        generated = {
            "version": 1, "provider": "local_rules_visual_v1", "generated_at": now(),
            "summary": item["title"], "innovation": "",
        }
        generated.update({key: sorted(value) for key, value in grouped.items()})
        for key in manual_fields:
            if key in annotation:
                generated[key] = annotation[key]
        generated["manual_fields"] = sorted(manual_fields)
        with self.library.connect() as conn:
            conn.execute("UPDATE items SET annotation_json=?,updated_at=? WHERE id=?", (safe_json(generated), now(), item_id))
        self.library.write_item_files(item_id)
        self.library.reindex_item(item_id)
        self.update_vector(item_id)
        return self.library.get_item(item_id)

    def annotate_all(self, regenerate=False):
        with self.library.connect() as conn:
            ids = [r[0] for r in conn.execute("SELECT id FROM items ORDER BY id")]
        return [self.auto_annotate(item_id, regenerate) for item_id in ids]

    def update_vector(self, item_id):
        item = self.library.get_item(item_id)
        vector = text_vector(item["search_text"])
        with self.library.connect() as conn:
            conn.execute("INSERT INTO vectors(item_id,provider,vector_json) VALUES(?,?,?) ON CONFLICT(item_id) DO UPDATE SET provider=excluded.provider,vector_json=excluded.vector_json",
                         (item_id, "local_ngram_alias_v1", json.dumps(vector.tolist())))

    def update_item(self, item_id, notes=None, annotation_patch=None, add_tags=None, remove_tags=None,
                    lock_tags=None, unlock_tags=None):
        item = self.library.get_item(item_id)
        if not item:
            raise KeyError("素材不存在: " + item_id)
        annotation = dict(item["annotation"])
        manual_fields = set(annotation.get("manual_fields", []))
        if annotation_patch:
            annotation.update(annotation_patch)
            manual_fields.update(annotation_patch)
        annotation["manual_fields"] = sorted(manual_fields)
        annotation["modified_at"] = now()
        with self.library.connect() as conn:
            if notes is not None:
                conn.execute("UPDATE items SET notes=?,updated_at=? WHERE id=?", (notes, now(), item_id))
            if annotation_patch is not None:
                conn.execute("UPDATE items SET annotation_json=?,updated_at=? WHERE id=?", (safe_json(annotation), now(), item_id))
            for name in remove_tags or []:
                conn.execute("DELETE FROM item_tags WHERE item_id=? AND name=?", (item_id, normalize_tag(name)))
        for name in add_tags or []:
            self.ensure_tag(name)
            with self.library.connect() as conn:
                conn.execute("INSERT INTO item_tags(item_id,name,source,confidence,locked) VALUES(?,?,?,1,0) ON CONFLICT(item_id,name) DO UPDATE SET source='manual',confidence=1",
                             (item_id, normalize_tag(name), "manual"))
        with self.library.connect() as conn:
            for name in lock_tags or []:
                conn.execute("UPDATE item_tags SET locked=1 WHERE item_id=? AND name=?", (item_id, normalize_tag(name)))
            for name in unlock_tags or []:
                conn.execute("UPDATE item_tags SET locked=0 WHERE item_id=? AND name=?", (item_id, normalize_tag(name)))
        self.library.write_item_files(item_id)
        self.library.reindex_item(item_id)
        self.update_vector(item_id)
        return self.library.get_item(item_id)

    def merge_tags(self, source, target):
        source, target = normalize_tag(source), normalize_tag(target)
        self.ensure_tag(target)
        if source == target:
            return target
        with self.library.connect() as conn:
            source_row = conn.execute("SELECT aliases_json FROM tags WHERE name=?", (source,)).fetchone()
            target_row = conn.execute("SELECT aliases_json FROM tags WHERE name=?", (target,)).fetchone()
            if not source_row or not target_row:
                raise ValueError("合并前两个标签都必须存在")
            aliases = set(json.loads(target_row[0])) | set(json.loads(source_row[0])) | {source}
            conn.execute("UPDATE OR IGNORE item_tags SET name=? WHERE name=?", (target, source))
            conn.execute("DELETE FROM item_tags WHERE name=?", (source,))
            conn.execute("DELETE FROM tags WHERE name=?", (source,))
            conn.execute("UPDATE tags SET aliases_json=? WHERE name=?", (safe_json(sorted(aliases)), target))
        ALIASES[source.lower()] = target
        return target

    def list_tags(self, query=""):
        with self.library.connect() as conn:
            rows = conn.execute("""
                SELECT tags.name,tags.category,tags.aliases_json,COUNT(item_tags.item_id) AS count
                FROM tags LEFT JOIN item_tags ON tags.name=item_tags.name
                WHERE tags.name LIKE ? OR tags.aliases_json LIKE ?
                GROUP BY tags.name ORDER BY tags.category,tags.name
            """, ("%" + query + "%", "%" + query + "%")).fetchall()
        return [{"name": r["name"], "category": r["category"], "aliases": json.loads(r["aliases_json"]), "count": r["count"]} for r in rows]

    def structured_ids(self, tags=None, match="all", exclude=None, platform="", collection=""):
        clauses = []
        params = []
        if platform:
            clauses.append("platform=?")
            params.append(platform)
        if collection:
            clauses.append("collection=?")
            params.append(collection)
        normalized = [normalize_tag(tag) for tag in tags or [] if tag.strip()]
        if normalized and match == "any":
            placeholders = ",".join("?" for _ in normalized)
            clauses.append("EXISTS(SELECT 1 FROM item_tags WHERE item_id=items.id AND name IN (" + placeholders + "))")
            params.extend(normalized)
        elif normalized:
            for tag in normalized:
                clauses.append("EXISTS(SELECT 1 FROM item_tags WHERE item_id=items.id AND name=?)")
                params.append(tag)
        for tag in exclude or []:
            clauses.append("NOT EXISTS(SELECT 1 FROM item_tags WHERE item_id=items.id AND name=?)")
            params.append(normalize_tag(tag))
        sql = "SELECT id,search_text,collection_position FROM items"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        with self.library.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [(r["id"], r["search_text"], r["collection_position"]) for r in rows]

    def fts_matches(self, terms):
        if not terms or any(len(term) < 3 for term in terms):
            return {}
        expression = " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)
        try:
            with self.library.connect() as conn:
                rows = conn.execute("SELECT id,bm25(items_fts) AS rank FROM items_fts WHERE items_fts MATCH ?", (expression,)).fetchall()
            if not rows:
                return {}
            ranks = [float(r["rank"]) for r in rows]
            low, high = min(ranks), max(ranks)
            return {r["id"]: 1.0 if high == low else 1.0 - (float(r["rank"]) - low) / (high - low) for r in rows}
        except Exception:
            return {}

    def search(self, q="", tags=None, match="all", exclude=None, platform="", collection="",
               limit=20, offset=0, semantic=True, min_score=0.16, sort="collection_asc"):
        if sort not in {"relevance", "collection_asc", "collection_desc"}:
            raise ValueError("不支持的排序方式")
        candidates = self.structured_ids(tags, match, exclude, platform, collection)
        terms = [term.lower() for term in re.findall(r"[^\s]+", q.strip())]
        lexical_fts = self.fts_matches(terms)
        query_vector = text_vector(q) if q and semantic else None
        vectors = {}
        if query_vector is not None and candidates:
            placeholders = ",".join("?" for _ in candidates)
            with self.library.connect() as conn:
                rows = conn.execute("SELECT item_id,vector_json FROM vectors WHERE item_id IN (" + placeholders + ")",
                                    [item_id for item_id, _, _ in candidates]).fetchall()
            vectors = {r["item_id"]: np.asarray(json.loads(r["vector_json"]), dtype=np.float32) for r in rows}
        scored = []
        for item_id, text, position in candidates:
            lowered = text.lower()
            lexical = 0.0
            if terms:
                hits = sum(term_lexical(term, lowered) for term in terms)
                lexical = hits / len(terms)
                if item_id in lexical_fts:
                    lexical = max(lexical, 0.75 + 0.25 * lexical_fts[item_id])
            similarity = 0.0
            if query_vector is not None and item_id in vectors:
                similarity = max(0.0, float(np.dot(query_vector, vectors[item_id])))
            if not q:
                score = 1.0
            elif semantic:
                score = 0.6 * lexical + 0.4 * similarity
            else:
                score = lexical
            if q and score < min_score:
                continue
            scored.append((item_id, score, lexical, similarity, position))
        if sort == "collection_asc":
            scored.sort(key=lambda value: (value[4] is None, value[4] if value[4] is not None else 0, -value[1], value[0]))
        elif sort == "collection_desc":
            scored.sort(key=lambda value: (value[4] is None, -(value[4] if value[4] is not None else 0), value[1], value[0]))
        else:
            scored.sort(key=lambda value: (-value[1], value[0]))
        total = len(scored)
        selected = scored[offset:offset + limit]
        items = []
        for item_id, score, lexical, similarity, position in selected:
            item = self.library.get_item(item_id)
            item["score"] = round(score, 4)
            item["match_detail"] = {"lexical": round(lexical, 4), "semantic": round(similarity, 4)}
            items.append(item)
        return {"items": items, "total": total, "query": q, "tags": tags or [], "match": match,
                "exclude": exclude or [], "offset": offset, "limit": limit, "sort": sort,
                "semantic_provider": "local_ngram_alias_v1" if semantic else "disabled"}

    def evaluate(self, benchmark_path):
        benchmark = json.loads(Path(benchmark_path).read_text(encoding="utf-8"))
        results = []
        for entry in benchmark["queries"]:
            expected_ids = []
            for fragment in entry.get("expect_title_contains", []):
                with self.library.connect() as conn:
                    rows = conn.execute("SELECT id FROM items WHERE title LIKE ?", ("%" + fragment + "%",)).fetchall()
                expected_ids.extend(r[0] for r in rows)
            found = self.search(q=entry["query"], limit=5)
            found_ids = [item["id"] for item in found["items"]]
            if entry.get("expect_empty"):
                passed = not found_ids
            else:
                passed = bool(expected_ids) and any(item_id in found_ids for item_id in expected_ids)
            results.append({"id": entry["id"], "query": entry["query"], "expected_ids": expected_ids,
                            "found_ids": found_ids, "passed": passed})
        return {"total": len(results), "passed": sum(r["passed"] for r in results),
                "pass_rate": sum(r["passed"] for r in results) / len(results), "results": results}
