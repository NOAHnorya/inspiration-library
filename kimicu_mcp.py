import json
import os
import select
import subprocess
import tempfile
import time


class KimiCU:
    def __init__(self, timeout=30):
        self.timeout = timeout
        self.request_id = 0
        self.stderr = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
        self.process = None

    def __enter__(self):
        self.process = subprocess.Popen(
            [os.environ.get("KIMICU_BIN", "/Applications/KimiCU.app/Contents/MacOS/kimi-cu"), "mcp", "-s", "user"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr,
            text=True,
        )
        result = self.request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "inspiration-library", "version": "1.0"},
        })
        if "error" in result:
            raise RuntimeError("KimiCU 初始化失败: " + str(result["error"]))
        self.notify("notifications/initialized", {})
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.stderr.close()

    def send(self, payload):
        if not self.process or self.process.poll() is not None:
            raise RuntimeError("KimiCU 未运行")
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def request(self, method, params):
        self.request_id += 1
        request_id = self.request_id
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.process.stdout], [], [], min(1, deadline - time.monotonic()))
            if not ready:
                continue
            line = self.process.stdout.readline()
            if not line:
                break
            message = json.loads(line)
            if message.get("id") == request_id:
                return message
        self.stderr.seek(0)
        detail = self.stderr.read().strip()[-2000:]
        raise RuntimeError("KimiCU 请求超时或已断开: " + method + (("\n" + detail) if detail else ""))

    def notify(self, method, params):
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def call(self, name, arguments):
        response = self.request("tools/call", {"name": name, "arguments": arguments})
        if "error" in response:
            raise RuntimeError(str(response["error"]))
        result = response.get("result", {})
        if result.get("isError"):
            raise RuntimeError(self.text(result))
        return result

    @staticmethod
    def text(result):
        if result.get("structuredContent", {}).get("tree_text"):
            return result["structuredContent"]["tree_text"]
        return "\n".join(part.get("text", "") for part in result.get("content", []) if part.get("type") == "text")

    def tree(self, app="com.citrolabs.ego.lite", limit=1000, offset=0, snapshot_id=None):
        arguments = {"app": app, "mode": "ax", "limit": limit, "offset": offset, "disable_diff": True}
        if snapshot_id:
            arguments["snapshot_id"] = snapshot_id
        return self.call("get_app_state", arguments)

    def full_tree(self):
        page = self.tree()
        pages = [page]
        while page["structuredContent"].get("has_more"):
            structured = page["structuredContent"]
            page = self.tree(offset=structured["next_offset"], snapshot_id=structured["snapshot_id"])
            pages.append(page)
        return pages
