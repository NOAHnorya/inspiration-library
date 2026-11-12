import re

REFERENCE_PATTERN = re.compile(r"@?(ins_[a-z0-9_]+_[A-Za-z0-9_-]+)")
CATEGORY_FIELDS = {
    "风格": "styles", "配色": "colors", "构图": "composition", "主题": "themes",
    "形式": "formats", "适用场景": "use_cases", "情绪气质": "moods",
}


class AgentTools:
    def __init__(self, catalog):
        self.catalog = catalog
        self.library = catalog.library

    def resolve(self, reference):
        match = re.fullmatch(REFERENCE_PATTERN, reference.strip())
        if not match:
            raise ValueError("非法灵感引用: " + reference)
        item = self.library.get_item(match.group(1))
        if not item:
            raise KeyError("灵感引用不存在或已删除: " + match.group(1))
        item["reference"] = "@" + item["id"]
        item["cover_path"] = str(self.library.data_dir / item["cover_local"]) if item["cover_local"] else ""
        return item

    def find_inspiration(self, query="", tags=None, match="all", exclude=None, platform="",
                         collection="", limit=5, semantic=True):
        result = self.catalog.search(query, tags, match, exclude, platform, collection, limit=limit, semantic=semantic)
        items = []
        for found in result["items"]:
            item = self.resolve(found["id"])
            matched = [tag for tag in tags or [] if tag in item["tag_names"]]
            reasons = []
            if query:
                reasons.append("检索词匹配“" + query + "”")
            if matched:
                reasons.append("命中标签：" + "、".join(matched))
            if not reasons:
                reasons.append("符合当前筛选条件")
            items.append({
                "id": item["id"], "reference": item["reference"], "title": item["title"],
                "author": item["author"], "url": item["url"], "cover": item["cover_path"] or item["cover_url"],
                "tags": item["tag_names"], "reason": "；".join(reasons), "score": found["score"],
            })
        return {"items": items, "total": result["total"], "query": query,
                "tags": tags or [], "match": match, "exclude": exclude or []}

    def get_inspiration(self, reference):
        return self.resolve(reference)

    def compare_inspiration(self, references):
        if not 2 <= len(references) <= 5:
            raise ValueError("对比需要 2–5 个灵感 ID")
        if len(set(references)) != len(references):
            raise ValueError("对比 ID 不能重复")
        items = [self.resolve(reference) for reference in references]
        shared = sorted(set(items[0]["tag_names"]).intersection(*(set(item["tag_names"]) for item in items[1:])))
        by_category = []
        for category, field in CATEGORY_FIELDS.items():
            values = {}
            for item in items:
                tags = [tag["name"] for tag in item["tags"] if tag["category"] == category]
                values[item["id"]] = tags or item["annotation"].get(field, [])
            if len({tuple(value) for value in values.values()}) > 1:
                by_category.append({"category": category, "values": values})
        compared = []
        for item in items:
            unique = sorted(set(item["tag_names"]) - set(shared))
            compared.append({
                "id": item["id"], "reference": item["reference"], "title": item["title"],
                "author": item["author"], "url": item["url"], "cover": item["cover_path"] or item["cover_url"],
                "distinctive_tags": unique,
                "evidence": {"source_url": item["url"], "annotation_provider": item["annotation"].get("provider", "manual")},
            })
        return {"items": compared, "shared_tags": shared, "differences": by_category,
                "citations": [item["reference"] for item in items]}

    def create_reference_brief(self, references, goal=""):
        if not 2 <= len(references) <= 5:
            raise ValueError("组合引用需要 2–5 个灵感 ID")
        if len(set(references)) != len(references):
            raise ValueError("组合引用 ID 不能重复")
        items = [self.resolve(reference) for reference in references]
        aspects = [("配色", "配色"), ("布局", "构图"), ("风格", "风格"), ("交互与场景", "适用场景")]
        instructions = []
        used = set()
        for aspect, category in aspects:
            candidates = [item for item in items if item["id"] not in used]
            if not candidates:
                candidates = items
            item = next((candidate for candidate in candidates
                         if any(tag["category"] == category for tag in candidate["tags"])), candidates[0])
            values = [tag["name"] for tag in item["tags"] if tag["category"] == category]
            if not values:
                continue
            instructions.append({"aspect": aspect, "source_id": item["id"], "source": item["reference"],
                                 "source_title": item["title"], "values": values, "evidence": item["url"]})
            used.add(item["id"])
        if not instructions:
            instructions = [{"aspect": "整体创意", "source_id": item["id"], "source": item["reference"],
                             "source_title": item["title"], "values": item["tag_names"], "evidence": item["url"]}
                            for item in items]
        lines = []
        if goal:
            lines.append("创作目标：" + goal)
        for instruction in instructions:
            lines.append("使用 {source} 的{aspect}：{values}。".format(
                source=instruction["source"], aspect=instruction["aspect"], values="、".join(instruction["values"])))
        lines.append("不复制原始文案和具体图形；原始链接仅用于核查来源。")
        return {"goal": goal, "instructions": instructions, "restrictions": ["不复制原文案", "不复制具体图形"],
                "citations": [item["reference"] for item in items], "text": "\n".join(lines)}

    def validate_references(self, text):
        ids = list(dict.fromkeys(REFERENCE_PATTERN.findall(text)))
        valid = []
        errors = []
        for item_id in ids:
            try:
                self.resolve(item_id)
                valid.append(item_id)
            except Exception as exc:
                errors.append({"id": item_id, "error": str(exc)})
        return {"total": len(ids), "valid": valid, "errors": errors, "ok": not errors}
