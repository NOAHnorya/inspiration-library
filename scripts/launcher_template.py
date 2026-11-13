#!/usr/bin/python3
import json
import os
import platform
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path($project_root)
PYTHON = $python_executable
HOST = "127.0.0.1"
PORT = $port
URL = f"http://{HOST}:{PORT}"
LOG = Path.home() / "Library" / "Logs" / "InspirationLibrary.log"

if platform.machine() == "x86_64" and Path("/usr/bin/arch").exists():
    native_arm = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.optional.arm64"], capture_output=True, text=True)
    if native_arm.stdout.strip() == "1":
        os.execv("/usr/bin/arch", ["/usr/bin/arch", "-arm64", PYTHON, str(Path(__file__).resolve())])


def healthy():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(URL + "/api/health", timeout=2) as response:
            return bool(json.load(response).get("ok"))
    except Exception:
        return False


def alert(message):
    script = 'display alert "灵感库" message ' + json.dumps(message, ensure_ascii=False) + ' as critical'
    subprocess.run(["/usr/bin/osascript", "-e", script], check=False)


def open_page():
    subprocess.run(["/usr/bin/open", URL], check=False)


if healthy():
    open_page()
    raise SystemExit(0)

with socket.socket() as connection:
    connection.settimeout(1)
    if connection.connect_ex((HOST, PORT)) == 0:
        alert(f"端口 {PORT} 已被其他程序占用，灵感库未启动。")
        raise SystemExit(1)

LOG.parent.mkdir(parents=True, exist_ok=True)
environment = dict(os.environ, PORT=str(PORT), PYTHONDONTWRITEBYTECODE="1")
with LOG.open("ab") as log:
    subprocess.Popen(
        [PYTHON, str(ROOT / "server.py")],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

for _ in range(60):
    if healthy():
        open_page()
        raise SystemExit(0)
    time.sleep(0.5)

alert("服务未能在 30 秒内启动。请查看日志：" + str(LOG))
sys.exit(1)
