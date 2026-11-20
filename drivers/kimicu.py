"""KimiCU driver: reads the macOS accessibility tree of the browser window.

macOS only. Needs KimiCU with Accessibility permission. Kept for users who
already rely on it; ego-browser is preferred when available.
"""
import os
from pathlib import Path
import random
import re
import subprocess
import time
from urllib.parse import urlsplit, urlunsplit

from extract_douyin_ax import extract_lines
from kimicu_mcp import KimiCU

from .base import (Driver, DriverUnavailable, NeedsLogin, MAX_ROUNDS, STOP_AFTER_KNOWN,
                   STOP_AFTER_UNCHANGED, ensure_safe, native_id)

IMAGE_RE = re.compile(r"AXImage .* URL: (https://[^\s]+)")
AUTHOR_RE = re.compile(r"AXLink \((.*)\) .*URL: https://www\.(?:xiaohongshu|rednote)\.com/user/profile/")
NODE_RE = re.compile(r"- \[(\d+)\]")
DEFAULT_BIN = "/Applications/KimiCU.app/Contents/MacOS/kimi-cu"


def kimicu_bin():
    return os.environ.get("KIMICU_BIN", DEFAULT_BIN)


def page_text(client, page):
    return client.text(page).split("<mcp-result-extras>")[0]


def page_nodes(page):
    return page.get("structuredContent", {}).get("nodes", [])


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


class KimiCUDriver(Driver):
    name = "kimicu"
    label = "KimiCU（macOS 辅助功能树）"

    @classmethod
    def check(cls):
        path = Path(kimicu_bin())
        if path.exists():
            return True, str(path)
        return False, "未找到 KimiCU（macOS 专用，可设置 KIMICU_BIN）"

    def __init__(self, config):
        super().__init__(config)
        available, detail = self.check()
        if not available:
            raise DriverUnavailable(detail)
        self.app = config.get("browser_app", "com.citrolabs.ego.lite")
        self.client = KimiCU().__enter__()
        subprocess.run(["/usr/bin/open", "-b", self.app, "about:blank"], check=True)
        time.sleep(2)

    def close(self):
        self.client.close()

    def navigate(self, url):
        self.client.call("press_key", {"app": self.app, "keys": "cmd+l"})
        self.client.call("paste", {"app": self.app, "text": url, "format": "text"})
        self.client.call("press_key", {"app": self.app, "keys": "return"})
        time.sleep(3)

    def open_douyin_collection(self, source):
        client = self.client
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
                client.call("click", {"app": self.app, "index": index,
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

    def read_collection(self, source, known_ids, status):
        client = self.client
        try:
            if source["platform"] == "douyin":
                self.navigate(source["profile_url"])
                self.open_douyin_collection(source)
            else:
                self.navigate(source["url"])
            return self.collect(source, known_ids, status)
        except Exception:
            try:
                client.call("activate_window", {"app": self.app})
            except Exception:
                pass
            raise

    def collect(self, source, known_ids, status):
        client = self.client
        items = {}
        previous = None
        unchanged = 0
        for round_number in range(1, MAX_ROUNDS + 1):
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
            status.progress(source, round_number, len(ordered), new_count)
            if trailing_known >= STOP_AFTER_KNOWN or unchanged >= STOP_AFTER_UNCHANGED:
                if not ordered:
                    raise RuntimeError(source["collection"] + " 没有读取到作品，页面结构可能已变化")
                return ordered
            scroll_area = next((node for node in page_nodes(pages[0]) if node.get("role") == "AXScrollArea"), None)
            if not scroll_area:
                raise RuntimeError("找不到收藏夹滚动区域")
            try:
                client.call("scroll", {"app": self.app, "index": scroll_area["index"], "page": -1,
                                       "snapshot_id": pages[0]["structuredContent"]["snapshot_id"]})
            except RuntimeError as exc:
                if ordered and "already at end" in str(exc):
                    return ordered
                raise
            time.sleep(random.uniform(2, 3))
        raise RuntimeError(source["collection"] + f" 超过 {MAX_ROUNDS} 次读取仍未到达已知条目，已安全停止")
