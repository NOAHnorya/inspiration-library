"""ego-browser driver: uses ego lite's own agent API.

Runs in a separate task space of the user's signed-in ego lite browser, so it
does not take over the mouse or the user's tabs, and reads links straight from
the page instead of parsing an accessibility tree. Works wherever ego lite runs
(macOS and Windows).
"""
from collections import deque
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time

from .base import (BLOCK_TERMS, MAX_ROUNDS, STOP_AFTER_KNOWN, STOP_AFTER_UNCHANGED, XHS_LOGIN_TERMS,
                   Blocked, Driver, DriverUnavailable, NeedsLogin, normalize_records)

SCRIPT = Path(__file__).with_name("ego_browser_sync.mjs")
TIMEOUT_SECONDS = 15 * 60


def ego_browser_bin():
    configured = os.environ.get("EGO_BROWSER_BIN")
    if configured:
        return configured if Path(configured).exists() else ""
    found = shutil.which("ego-browser")
    if found:
        return found
    for candidate in [Path.home() / ".local" / "bin" / "ego-browser",
                      Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "ego-browser" / "ego-browser.exe"]:
        if str(candidate) not in ("", ".") and candidate.exists():
            return str(candidate)
    return ""


class EgoBrowserDriver(Driver):
    name = "ego-browser"
    label = "ego lite 浏览器自带的 Agent 接口（推荐）"

    @classmethod
    def check(cls):
        binary = ego_browser_bin()
        if binary:
            return True, binary
        return False, "未找到 ego-browser 命令。安装 ego lite（https://lite.ego.app/）后会自带。"

    def __init__(self, config):
        super().__init__(config)
        available, detail = self.check()
        if not available:
            raise DriverUnavailable(detail)
        self.binary = detail

    def read_collection(self, source, known_ids, status):
        board = re.search(r"/board/([0-9a-f]{24})", source.get("url", ""))
        params = {
            "spaceName": "灵感库同步 " + source["key"] + " " + time.strftime("%m-%d %H:%M:%S"),
            "platform": source["platform"],
            "url": source["profile_url"] if source["platform"] == "douyin" else source["url"],
            "collection": source["collection"],
            "accountMarker": source.get("account_marker", ""),
            "boardId": board.group(1) if board else "",
            "knownIds": sorted(known_ids),
            "blockTerms": BLOCK_TERMS,
            "loginTerms": XHS_LOGIN_TERMS,
            "maxRounds": MAX_ROUNDS,
            "stopAfterKnown": STOP_AFTER_KNOWN,
            "stopAfterUnchanged": STOP_AFTER_UNCHANGED,
        }
        if source["platform"] == "xiaohongshu" and not params["boardId"]:
            raise ValueError("小红书收藏夹链接中缺少 board ID: " + source["key"])
        script = "const P = " + json.dumps(params, ensure_ascii=False) + ";\n" + SCRIPT.read_text(encoding="utf-8")
        process = subprocess.Popen([self.binary, "nodejs"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        timer = threading.Timer(TIMEOUT_SECONDS, process.kill)
        timer.start()
        result = None
        tail = deque(maxlen=20)
        try:
            process.stdin.write(script)
            process.stdin.close()
            for line in process.stdout:
                line = line.rstrip("\n")
                if line.startswith("__INSPIRATION_PROGRESS__"):
                    progress = json.loads(line[len("__INSPIRATION_PROGRESS__"):])
                    status.progress(source, progress["round"], progress["found"], progress["new"])
                elif line.startswith("__INSPIRATION_RESULT__"):
                    result = json.loads(line[len("__INSPIRATION_RESULT__"):])
                elif line.strip():
                    tail.append(line)
            process.wait()
        finally:
            timer.cancel()
        if result is None:
            raise RuntimeError("ego-browser 没有返回结果。请确认 ego lite 已打开。\n" + "\n".join(tail))
        if not result.get("ok"):
            kind = result.get("kind")
            if kind == "blocked":
                raise Blocked(result["error"])
            if kind == "needs_login":
                raise NeedsLogin(result["error"])
            raise RuntimeError(result.get("error", "ego-browser 读取失败"))
        return normalize_records(result["items"], source)
