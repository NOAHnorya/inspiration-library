"""Connect the inspiration library to the user's own agent.

Each agent gets the same MCP server (mcp_server.py over stdio) plus a skill /
instructions file, written to wherever that agent reads them. Every change to
a file outside this repository is previewed first and backed up before writing.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from core import ROOT

HOME = Path.home()
SERVER_NAME = "inspiration"
SKILL_SOURCE = ROOT / "skills" / "inspiration-library" / "SKILL.md"
SHARED_SKILLS = HOME / ".agents" / "skills"
DSH_MARK_START = "# >>> inspiration-library (managed by cli.py init)"
DSH_MARK_END = "# <<< inspiration-library"


def server_command(data_dir, config_path, python=None):
    args = [str(ROOT / "mcp_server.py"), "--data-dir", str(data_dir), "--config", str(config_path)]
    return {"command": python or sys.executable, "args": args}


def exists_any(*paths):
    return any(Path(path).expanduser().exists() for path in paths)


AGENTS = [
    {"id": "claude-code", "label": "Claude Code",
     "detect": lambda: bool(shutil.which("claude")) or exists_any("~/.claude")},
    {"id": "codex", "label": "Codex",
     "detect": lambda: bool(shutil.which("codex")) or exists_any("~/.codex")},
    {"id": "kimi-code", "label": "Kimi Code（含 KimiCU）",
     "detect": lambda: bool(shutil.which("kimi")) or exists_any("~/.kimi-code")},
    {"id": "cursor", "label": "Cursor",
     "detect": lambda: exists_any("~/.cursor", "/Applications/Cursor.app")},
    {"id": "gemini", "label": "Gemini CLI",
     "detect": lambda: bool(shutil.which("gemini")) or exists_any("~/.gemini")},
    {"id": "dsh", "label": "DSH（DeepSeek 桌面 Agent）",
     "detect": lambda: exists_any("~/.dsh", "/Applications/DSH Desktop.app")},
    {"id": "openclaw", "label": "OpenClaw",
     "detect": lambda: bool(shutil.which("openclaw")) or exists_any("~/.openclaw")},
    {"id": "other", "label": "其他 / 还没有固定用的", "detect": lambda: False},
]
AGENT_IDS = [agent["id"] for agent in AGENTS]


def detect_agents():
    return [{"id": agent["id"], "label": agent["label"], "detected": agent["detect"]()} for agent in AGENTS]


class Change:
    """One planned write. `apply()` backs up the target before writing."""

    def __init__(self, path, content, summary, command=None):
        self.path = Path(path) if path else None
        self.content = content
        self.summary = summary
        self.command = command

    def preview(self):
        if self.command:
            return "运行命令：" + " ".join(self.command)
        return f"写入 {self.path}\n" + self.content[-1200:]

    def apply(self):
        if self.command:
            result = subprocess.run(self.command, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout).strip())
            return {"ran": " ".join(self.command)}
        backup = None
        if self.path.exists() and self.path.read_text(encoding="utf-8") == self.content:
            return {"unchanged": str(self.path)}
        if self.path.exists():
            backup = self.path.with_name(self.path.name + ".bak-inspiration-" + time.strftime("%Y%m%d%H%M%S"))
            shutil.copy2(self.path, backup)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".inspiration.tmp")
        temporary.write_text(self.content, encoding="utf-8")
        if self.path.exists():
            shutil.copymode(self.path, temporary)  # keep private configs private (often 600)
        temporary.replace(self.path)
        return {"written": str(self.path), "backup": str(backup) if backup else None}


def rendered_skill(python=None):
    text = SKILL_SOURCE.read_text(encoding="utf-8")
    return text.replace("{{REPO}}", str(ROOT)).replace("{{PYTHON}}", python or sys.executable)


def skill_change(folder, python=None):
    target = Path(folder).expanduser() / "inspiration-library" / "SKILL.md"
    return Change(target, rendered_skill(python), "安装 Skill：" + str(target))


def json_mcp_change(path, server, key="mcpServers", extra=None):
    path = Path(path).expanduser()
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() and path.read_text(encoding="utf-8").strip() else {}
    data.setdefault(key, {})[SERVER_NAME] = {**server, **(extra or {})}
    return Change(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", f"在 {path} 的 {key} 里加入 {SERVER_NAME}")


def toml_string(value):
    return json.dumps(str(value), ensure_ascii=False)


def codex_change(server, path="~/.codex/config.toml"):
    path = Path(path).expanduser()
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    block = (f"[mcp_servers.{SERVER_NAME}]\n"
             f"command = {toml_string(server['command'])}\n"
             "args = [" + ", ".join(toml_string(arg) for arg in server["args"]) + "]\n"
             "startup_timeout_sec = 30\n")
    pattern = re.compile(r"^\[mcp_servers\." + SERVER_NAME + r"\]\n(?:(?!^\[).*\n?)*", re.M)
    if pattern.search(text):
        text = pattern.sub(block + "\n", text, count=1)
    else:
        text = text.rstrip("\n") + ("\n\n" if text.strip() else "") + block
    return Change(path, text, f"在 {path} 加入 [mcp_servers.{SERVER_NAME}]")


def dsh_change(server, profile="desktop"):
    path = HOME / ".dsh" / "profiles" / profile / "cordis.patch.yml"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    args = ", ".join(json.dumps(arg, ensure_ascii=False) for arg in server["args"])
    # A running DSH may re-save this file and drop standalone comments, so the
    # block is found by its structure (insert + mcp-inspiration), not markers.
    block = ("- insert: # inspiration-library (managed by cli.py init)\n"
             "    - id: mcp-inspiration\n"
             "      name: '@deepseek-ai/dsh-mcp-client'\n"
             "      config:\n"
             f"        serverName: {SERVER_NAME}\n"
             "        transport: stdio\n"
             f"        command: {json.dumps(server['command'], ensure_ascii=False)}\n"
             f"        args: [{args}]\n"
             "        toolCallTimeoutMs: 120000\n"
             f"{DSH_MARK_END}\n")
    pattern = re.compile(r"^(?:" + re.escape(DSH_MARK_START) + r"[^\n]*\n)?- insert:[^\n]*\n {4}- id: mcp-inspiration\n"
                         r"(?: {4,}[^\n]*\n?)*(?:" + re.escape(DSH_MARK_END) + r"\n?)?", re.M)
    if pattern.search(text):
        text = pattern.sub(block, text, count=1)
    else:
        text = text.rstrip("\n") + ("\n" if text.strip() else "") + block
    return Change(path, text, f"在 DSH 的 {profile} 配置里加入 MCP 服务（重启 DSH 后生效）")


def claude_changes(server):
    claude = shutil.which("claude")
    if claude:
        remove = Change(None, "", "移除旧的 inspiration 配置（如果有）",
                        command=[claude, "mcp", "remove", "--scope", "user", SERVER_NAME])
        add = Change(None, "", "用 claude mcp add 注册（用户级，所有项目可用）",
                     command=[claude, "mcp", "add", "--scope", "user", SERVER_NAME, "--", server["command"], *server["args"]])
        return [remove, add]
    return [json_mcp_change(ROOT / ".mcp.json", server)]


def plan(agent_id, data_dir, config_path, python=None):
    """Return (changes, manual_instructions) for one agent."""
    server = server_command(data_dir, config_path, python)
    snippet = json.dumps({"mcpServers": {SERVER_NAME: server}}, ensure_ascii=False, indent=2)
    if agent_id == "claude-code":
        return claude_changes(server) + [skill_change(HOME / ".claude" / "skills", python)], ""
    if agent_id == "codex":
        return [codex_change(server), skill_change(SHARED_SKILLS, python)], ""
    if agent_id == "kimi-code":
        return [json_mcp_change(HOME / ".kimi-code" / "mcp.json", server), skill_change(SHARED_SKILLS, python)], ""
    if agent_id == "cursor":
        return [json_mcp_change(HOME / ".cursor" / "mcp.json", server)], ""
    if agent_id == "gemini":
        return [json_mcp_change(HOME / ".gemini" / "settings.json", server), skill_change(SHARED_SKILLS, python)], ""
    if agent_id == "dsh":
        return [dsh_change(server), skill_change(SHARED_SKILLS, python)], ""
    manual = ("把下面这段加到你的 Agent 的 MCP 配置里（不同 Agent 位置不同，通常叫 mcpServers）：\n" + snippet +
              "\n\n如果你的 Agent 不支持 MCP，告诉它：“阅读 " + str(ROOT / "AGENTS.md") + "，用里面的命令行使用我的灵感库。”")
    return [skill_change(SHARED_SKILLS, python)], manual


def apply_changes(changes, confirm=None):
    results = []
    for change in changes:
        if confirm and not confirm(change):
            results.append({"skipped": change.summary})
            continue
        try:
            results.append({"summary": change.summary, **change.apply()})
        except Exception as exc:
            if change.command and "remove" in change.command:
                results.append({"summary": change.summary, "note": "之前没有，跳过"})
                continue
            results.append({"summary": change.summary, "error": str(exc)})
    return results


def try_prompt(agent_id):
    prompts = {
        "claude-code": "claude",
        "codex": "codex",
        "kimi-code": "kimi",
        "gemini": "gemini",
        "dsh": "重启 DSH Desktop",
        "cursor": "重启 Cursor",
    }
    opener = prompts.get(agent_id, "打开你的 Agent")
    return f"{opener}，然后说：“从我的灵感库里找 5 个复古未来主义风格的网页参考，给出 @引用 ID”"
