import argparse
import json
import os
from pathlib import Path
import random
import re
import subprocess
import time
from urllib.parse import urlsplit, urlunsplit

from core import Library, ROOT, now
from extract_douyin_ax import extract_lines
from kimicu_mcp import KimiCU
from maintenance import Maintenance
from sync_config import load_sync_config
from tagging import Catalog

IMAGE_RE = re.compile(r"AXImage .* URL: (https://[^\s]+)")
AUTHOR_RE = re.compile(r"AXLink \((.*)\) .*URL: https://www\.(?:xiaohongshu|rednote)\.com/user/profile/")
NODE_RE = re.compile(r"- \[(\d+)\]")


class NeedsLogin(Exception):
    pass


class Blocked(Exception):
    pass


def page_text(client, page):
    return client.text(page).split("<mcp-result-extras>")[0]


def page_nodes(page):
    return page.get("structuredContent", {}).get("nodes", [])


def native_id(record):
    url = record.get("url", "")
    match = re.search(r"/(?:video|note)/(\d+)", url)
    if match:
        return match.group(1)
    matches = re.findall(r"/([0-9a-f]{24})(?=/|$|\?)", url)
    return matches[-1] if matches else ""


def parse_douyin_pages(client, pages, collection):
    items = {}
    for page in pages:
        for item in extract_lines(page_text(client, page).splitlines()):
            items.setdefault(item["native_id"], item)
    return [{"platform": "douyin", "collection": collection, "title": item["title"],
             "author": item["author"], "url": item["url"], "cover": item["cover"], "raw": item["raw"]}
            for item in items.values()]


def xhs_link_pattern(board_url):
    parts = urlsplit(board_url)
    base = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
    return re.compile(r"AXLink(?: \((.*)\))? .*URL: (" + re.escape(base) + r"/([0-9a-f]{24})[^\s]*)")


def parse_xhs_lines(lines, collection, board_url):
    link_re = xhs_link_pattern(board_url)
    covers = {}
    items = {}
    for index, line in enumerate(lines):
        match = link_re.search(line)
        if not match:
            continue
        label, url, item_id = match.groups()
        if not label:
            for following in lines[index + 1:index + 6]:
                image = IMAGE_RE.search(following)
                if image:
                    covers[item_id] = image.group(1)
                    break
            continue
        author = ""
        for following in lines[index + 1:index + 8]:
            author_match = AUTHOR_RE.search(following)
            if author_match:
                author = author_match.group(1)
                break
        items[item_id] = {"platform": "xiaohongshu", "collection": collection,
                          "title": label.strip(), "author": author, "url": url,
                          "cover": covers.get(item_id, "")}
    return list(items.values())


def parse_xhs_pages(client, pages, collection, board_url):
    items = {}
    for page in pages:
        for item in parse_xhs_lines(page_text(client, page).splitlines(), collection, board_url):
            key = native_id(item)
            if key in items and items[key]["cover"] and not item["cover"]:
                continue
            items[key] = item
    return list(items.values())


def ensure_safe(text, platform):
    if any(term in text for term in ["安全验证", "人机验证", "滑块验证", "请完成验证", "访问过于频繁", "操作过于频繁", "风控拦截"]):
        raise Blocked("检测到验证码或风控，已停止操作。请在浏览器中处理后再更新。")
    if platform == "xiaohongshu" and any(term in text for term in ["登录状态异常", "登录后查看专辑", "登录后推荐更懂你的笔记"]):
        raise NeedsLogin("小红书登录已失效。请在浏览器中登录，然后重新点击更新。")
    if "未连接到服务器" in text:
        raise RuntimeError("平台页面未能连接服务器，请检查网络后重试。")


def clickable_ancestor(lines, target_index):
    target_indent = len(lines[target_index]) - len(lines[target_index].lstrip())
    for cursor in range(target_index - 1, -1, -1):
        line = lines[cursor]
        indent = len(line) - len(line.lstrip())
        if indent < target_indent and "AXGroup" in line and "AXPress" in line:
            match = NODE_RE.search(line)
            if match:
                return int(match.group(1))
    raise RuntimeError("找不到收藏夹卡片的只读点击目标")


def navigate(client, app, url, new_tab=False):
    if new_tab:
        client.call("press_key", {"app": app, "keys": "cmd+t"})
        time.sleep(0.8)
    client.call("press_key", {"app": app, "keys": "cmd+l"})
    client.call("paste", {"app": app, "text": url, "format": "text"})
    client.call("press_key", {"app": app, "keys": "return"})
    time.sleep(3)


def open_douyin_collection(client, app, source):
    collection_found = False
    for _ in range(15):
        pages = client.full_tree()
        text = "\n".join(page_text(client, page) for page in pages)
        ensure_safe(text, "douyin")
        account_marker = source.get("account_marker", "")
        if account_marker and account_marker not in text:
            time.sleep(2)
            continue
        for page in pages:
            lines = page_text(client, page).splitlines()
            target = next((index for index, line in enumerate(lines)
                           if line.strip().endswith('AXStaticText = "' + source["collection"] + '"')), None)
            if target is None:
                continue
            collection_found = True
            try:
                index = clickable_ancestor(lines, target)
            except RuntimeError:
                continue
            client.call("click", {"app": app, "index": index,
                                  "snapshot_id": page["structuredContent"]["snapshot_id"]})
            time.sleep(3)
            for _ in range(15):
                pages = client.full_tree()
                text = "\n".join(page_text(client, page) for page in pages)
                ensure_safe(text, "douyin")
                if parse_douyin_pages(client, pages, source["collection"]):
                    return
                time.sleep(2)
            raise RuntimeError(source["collection"] + " 打开后仍未读取到作品，请检查网络后重试")
        time.sleep(2)
    if collection_found:
        raise RuntimeError("抖音收藏夹卡片尚未就绪，请重试: " + source["collection"])
    raise NeedsLogin("抖音收藏夹不可读，请检查浏览器登录状态后重试。")


def collect(client, app, source, known_ids, status):
    items = {}
    previous = None
    unchanged = 0
    for round_number in range(1, 81):
        pages = client.full_tree()
        text = "\n".join(page_text(client, page) for page in pages)
        ensure_safe(text, source["platform"])
        if source["platform"] == "douyin":
            current = parse_douyin_pages(client, pages, source["collection"])
        else:
            current = parse_xhs_pages(client, pages, source["collection"], source["url"])
        for item in current:
            items.setdefault(native_id(item), item)
        ordered = list(items.values())
        trailing_known = 0
        for item in reversed(ordered):
            if native_id(item) not in known_ids:
                break
            trailing_known += 1
        fingerprint = tuple(native_id(item) for item in current)
        unchanged = unchanged + 1 if fingerprint == previous else 0
        previous = fingerprint
        new_count = sum(native_id(item) not in known_ids for item in ordered)
        status.update(message=f"{source['collection']}：第 {round_number} 次读取，已见 {len(ordered)} 条，新增 {new_count} 条",
                      current={"key": source["key"], "collection": source["collection"],
                               "round": round_number, "found": len(ordered), "new": new_count})
        if trailing_known >= 20 or unchanged >= 3:
            if not ordered:
                raise RuntimeError(source["collection"] + " 没有读取到作品，页面结构可能已变化")
            return ordered
        scroll_area = next((node for node in page_nodes(pages[0]) if node.get("role") == "AXScrollArea"), None)
        if not scroll_area:
            raise RuntimeError("找不到收藏夹滚动区域")
        try:
            client.call("scroll", {"app": app, "index": scroll_area["index"], "page": -1,
                                   "snapshot_id": pages[0]["structuredContent"]["snapshot_id"]})
        except RuntimeError as exc:
            if ordered and "already at end" in str(exc):
                return ordered
            raise
        time.sleep(random.uniform(2, 3))
    raise RuntimeError(source["collection"] + " 超过 80 次读取仍未到达已知条目，已安全停止")


def merge_records(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    known_ids = {native_id(record) for record in existing if native_id(record)}
    new_records = [record for record in records if native_id(record) not in known_ids]
    old_by_id = {native_id(record): record for record in existing if native_id(record)}
    merged = []
    seen = set()
    for record in records + existing:
        item_id = native_id(record)
        if not item_id or item_id in seen:
            continue
        merged.append({**old_by_id.get(item_id, {}), **record})
        seen.add(item_id)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return new_records


def retry_covers(library, catalog, results):
    succeeded = 0
    for result in results:
        if result.get("status") != "needs_review" or not result.get("id"):
            continue
        item = library.get_item(result["id"])
        if not item or not item.get("cover_url"):
            continue
        asset = library.download_asset(item["id"], item["cover_url"])
        if not asset:
            continue
        with library.connect() as conn:
            conn.execute("UPDATE items SET import_status='ready',updated_at=? WHERE id=?", (now(), item["id"]))
        catalog.auto_annotate(item["id"], regenerate=True)
        result["status"] = "ready"
        succeeded += 1
    return succeeded


def import_new(library, catalog, source, records, data_dir):
    incoming = data_dir / ("sync_" + source["key"] + "_new.json")
    incoming.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not records:
        return {"imported": 0, "needs_review": 0, "cover_retries_succeeded": 0}
    importer = library.import_douyin if source["platform"] == "douyin" else library.import_xhs
    results = importer(incoming, True)
    for result in results:
        if result.get("id"):
            catalog.auto_annotate(result["id"])
    retries = retry_covers(library, catalog, results)
    return {"imported": sum(result["status"] == "ready" for result in results),
            "needs_review": sum(result["status"] == "needs_review" for result in results),
            "cover_retries_succeeded": retries}


def source_path(source):
    path = Path(source["file"]).expanduser()
    return path if path.is_absolute() else ROOT / path


def backfill_collection_positions(library, sources):
    results = []
    for source in sources:
        path = source_path(source)
        if not path.exists():
            results.append({"key": source["key"], "updated": 0, "missing_file": True})
            continue
        records = json.loads(path.read_text(encoding="utf-8"))
        prefix = "ins_douyin_" if source["platform"] == "douyin" else "ins_xhs_"
        updated = 0
        with library.connect() as conn:
            for position, record in enumerate(records):
                item_id = native_id(record)
                if not item_id:
                    continue
                cursor = conn.execute("UPDATE items SET collection_position=? WHERE id=?",
                                      (position, prefix + item_id))
                updated += cursor.rowcount
        results.append({"key": source["key"], "updated": updated})
    return {"sources": results, "updated": sum(result["updated"] for result in results)}


class Status:
    def __init__(self, path):
        self.path = path
        self.value = {}

    def update(self, **values):
        self.value.update(values)
        self.value["updated_at"] = now()
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)


def run(keys=None, config_path=None):
    config = load_sync_config(config_path)
    selected = [source for source in config["sources"] if not keys or source["key"] in keys]
    if not selected:
        raise ValueError("没有选中需要更新的收藏夹")
    unknown = set(keys or []) - {source["key"] for source in config["sources"]}
    if unknown:
        raise ValueError("配置中不存在收藏夹: " + ", ".join(sorted(unknown)))
    library = Library()
    data_dir = library.data_dir
    status = Status(data_dir / "sync_status.json")
    status.update(state="running", pid=os.getpid(), started_at=now(), message="准备只读更新",
                  current=None, results=[])
    catalog = Catalog(library)
    maintenance = Maintenance(library, catalog)
    results = []
    total_new = 0
    app = config["browser_app"]
    try:
        with KimiCU() as client:
            subprocess.run(["/usr/bin/open", "-b", app, "about:blank"], check=True)
            time.sleep(2)
            for source in selected:
                status.update(message="打开收藏夹：" + source["collection"],
                              current={"key": source["key"], "collection": source["collection"]})
                try:
                    if source["platform"] == "douyin":
                        navigate(client, app, source["profile_url"])
                        open_douyin_collection(client, app, source)
                    else:
                        navigate(client, app, source["url"])
                    path = source_path(source)
                    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
                    known_ids = {native_id(record) for record in existing if native_id(record)}
                    records = collect(client, app, source, known_ids, status)
                    new_records = merge_records(path, records)
                    imported = import_new(library, catalog, source, new_records, data_dir)
                    backfill_collection_positions(library, [source])
                    total_new += len(new_records)
                    result = {"key": source["key"], "platform": source["platform"],
                              "collection": source["collection"], "status": "done",
                              "found": len(records), "new": len(new_records), **imported}
                except NeedsLogin as exc:
                    result = {"key": source["key"], "platform": source["platform"],
                              "collection": source["collection"], "status": "needs_login", "error": str(exc)}
                    client.call("activate_window", {"app": app})
                except Blocked as exc:
                    result = {"key": source["key"], "platform": source["platform"],
                              "collection": source["collection"], "status": "blocked", "error": str(exc)}
                    results.append(result)
                    status.update(results=results)
                    client.call("activate_window", {"app": app})
                    break
                except Exception as exc:
                    result = {"key": source["key"], "platform": source["platform"],
                              "collection": source["collection"], "status": "failed", "error": str(exc)}
                results.append(result)
                status.update(results=results)
        if total_new:
            maintenance.build_visual_index()
        health = maintenance.health_check()
        state = "done"
        if any(result["status"] in {"needs_login", "blocked"} for result in results):
            state = "paused"
        elif any(result["status"] == "failed" for result in results):
            state = "failed"
        status.update(state=state, current=None, results=results, finished_at=now(),
                      message=f"更新结束：新增 {total_new} 条", stats=library.stats(), health_ok=health["ok"])
    except Exception as exc:
        status.update(state="failed", current=None, results=results, finished_at=now(),
                      message="更新失败", error=str(exc))
        raise
    return status.value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    parser.add_argument("--only", action="append")
    parser.add_argument("--rebuild-order", action="store_true")
    args = parser.parse_args()
    if args.rebuild_order:
        config = load_sync_config(args.config)
        result = backfill_collection_positions(Library(), config["sources"])
    else:
        result = run(args.only, args.config)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
