"""Shared pieces for collection-sync drivers.

A driver is the "hands" of a sync: it opens one configured collection in a
browser the user is already signed in to, reads the visible items and returns
them as plain records. It never logs in, never reads cookies or passwords and
stops as soon as a verification page or rate-limit notice appears.
"""
import re

BLOCK_TERMS = ["安全验证", "人机验证", "滑块验证", "请完成验证", "访问过于频繁", "操作过于频繁", "风控拦截"]
XHS_LOGIN_TERMS = ["登录状态异常", "登录后查看专辑", "登录后推荐更懂你的笔记"]
MAX_ROUNDS = 80
STOP_AFTER_KNOWN = 20
STOP_AFTER_UNCHANGED = 3


class NeedsLogin(Exception):
    """The page needs the user to sign in. Sync pauses; nothing is bypassed."""


class Blocked(Exception):
    """A CAPTCHA or rate-limit page appeared. Sync stops immediately."""


class DriverUnavailable(Exception):
    """The driver's tool is not installed or cannot be reached."""


class HandoffPending(Exception):
    """The collection was handed to the user's own agent; results are not back yet."""

    def __init__(self, message, task):
        super().__init__(message)
        self.task = task


def ensure_safe(text, platform):
    if any(term in text for term in BLOCK_TERMS):
        raise Blocked("检测到验证码或风控，已停止操作。请在浏览器中处理后再更新。")
    if platform == "xiaohongshu" and any(term in text for term in XHS_LOGIN_TERMS):
        raise NeedsLogin("小红书登录已失效。请在浏览器中登录，然后重新点击更新。")
    if "未连接到服务器" in text:
        raise RuntimeError("平台页面未能连接服务器，请检查网络后重试。")


def native_id(record):
    url = record.get("url", "")
    match = re.search(r"/(?:video|note)/(\d+)", url)
    if match:
        return match.group(1)
    matches = re.findall(r"/([0-9a-f]{24})(?=/|$|\?)", url)
    return matches[-1] if matches else ""


def normalize_records(records, source):
    """Validate records coming back from any driver or agent and keep page order."""
    if not isinstance(records, list):
        raise ValueError("收藏条目必须是 JSON 数组")
    cleaned = []
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        url = str(record.get("url", "")).strip()
        item = {"platform": source["platform"], "collection": source["collection"],
                "title": str(record.get("title", "")).strip() or "未命名素材",
                "author": str(record.get("author", "")).strip(), "url": url,
                "cover": str(record.get("cover", "")).strip()}
        if record.get("raw"):
            item["raw"] = record["raw"]
        key = native_id(item)
        if not key or key in seen:
            continue
        if source["platform"] == "douyin" and not re.search(r"douyin\.com/(?:video|note)/\d+", url):
            continue
        if source["platform"] == "xiaohongshu" and not re.search(r"(?:xiaohongshu|rednote)\.com/", url):
            continue
        seen.add(key)
        cleaned.append(item)
    return cleaned


class Driver:
    name = ""
    label = ""

    @classmethod
    def check(cls):
        """Return (available, detail)."""
        return False, "未实现"

    def __init__(self, config):
        self.config = config

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        pass

    def read_collection(self, source, known_ids, status):
        """Return records in the order the collection page shows them."""
        raise NotImplementedError
