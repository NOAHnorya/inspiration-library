# 让你的 Agent 帮你装好灵感库

> 给用户：把下面这句话发给你的 Agent（Claude Code、Codex、Cursor、Kimi Code、DSH、Gemini CLI、OpenClaw 都可以）：
>
> **请按 https://github.com/NOAHnorya/inspiration-library 的 AGENT_SETUP.md 帮我装好灵感库。**

---

以下是给 Agent 的步骤。每一步都先告诉用户你要做什么；涉及修改用户全局配置的步骤，先征得同意。

## 1. 问用户两个问题

1. **你平时用哪个 Agent？** 通常就是你自己，直接确认即可：`claude-code`、`codex`、`kimi-code`、`cursor`、`gemini`、`dsh`、`openclaw`、`other`。
2. **要同步哪些收藏夹？**
   - 小红书：网页版打开“我 → 收藏 → 专辑”，进入某个专辑，复制地址栏链接（形如 `https://www.xiaohongshu.com/board/<24位ID>`），再给它起个名字。
   - 抖音：网页版“我的 → 收藏 → 收藏夹”里的收藏夹名称；可选填抖音昵称，用于核对账号。
   - 暂时不想同步也可以跳过，之后随时 `python cli.py init` 再加。

## 2. 安装

```bash
git clone https://github.com/NOAHnorya/inspiration-library.git
cd inspiration-library
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

需要 Python 3.9+。不需要任何模型 API Key。

## 3. 检查环境

```bash
python cli.py doctor
```

看输出里的 `drivers`：

- `ego-browser` 可用：最省事，同步时用 ego lite 浏览器自带的 Agent 接口在独立空间里只读读取。
- `kimicu` 可用：macOS 上用 KimiCU 读取。
- 都不可用：同步时会生成任务交给你（Agent）用自己的浏览器工具读。可以建议用户安装 ego lite（https://lite.ego.app/），装好后在 ego lite 里登录小红书 / 抖音。

## 4. 一条命令完成配置

用第 1 步的答案替换参数（小红书和抖音都可以重复多次）：

```bash
python cli.py init --agent codex \
  --xhs "https://www.xiaohongshu.com/board/<24位ID>" --xhs-name 设计灵感 \
  --douyin 审美数据 --douyin-account 用户的抖音昵称 \
  --yes
```

它会：

- 写好 `sync_sources.json`（只在本机，已被 Git 忽略）；
- 把灵感库的 MCP 服务注册到对应 Agent，改动前自动备份原配置文件；
- 安装 Skill / 说明，让 Agent 知道什么时候、怎么用灵感库。

各 Agent 写到哪里：

| Agent | MCP 配置 | Skill |
| --- | --- | --- |
| Claude Code | `claude mcp add --scope user inspiration …` | `~/.claude/skills/inspiration-library/` |
| Codex | `~/.codex/config.toml` 的 `[mcp_servers.inspiration]` | `~/.agents/skills/inspiration-library/` |
| Kimi Code | `~/.kimi-code/mcp.json` | `~/.agents/skills/inspiration-library/` |
| Cursor | `~/.cursor/mcp.json` | 用仓库里的 `AGENTS.md` |
| Gemini CLI | `~/.gemini/settings.json` | `~/.agents/skills/inspiration-library/` |
| DSH | `~/.dsh/profiles/desktop/cordis.patch.yml`（插入 `dsh-mcp-client`） | `~/.agents/skills/inspiration-library/` |
| OpenClaw / 其他 | 输出一段 MCP JSON，由用户贴进自己的配置 | `~/.agents/skills/inspiration-library/` |

用户想逐项确认时，去掉 `--yes`，在终端里运行 `python cli.py init` 即可进入问答模式。

## 5. 第一次同步（可选）

确认用户已经在对应浏览器里登录了小红书 / 抖音，然后：

```bash
python cli.py sync
```

第一次会从头读到尾，收藏多时需要几分钟，主要花在下载封面。结果里 `status`：

- `done`：完成。
- `needs_login` / `blocked`：请用户在浏览器里登录或处理验证，然后重试。**不要尝试绕过。**
- `waiting_for_agent`：轮到你用自己的浏览器读取，步骤见 `data/handoff/<key>.task.json`，读完调用 MCP 工具 `submit_collection_records`，或运行 `python cli.py sync --submit <key> --records 结果.json`。

## 6. 收尾

- 重启用户的 Agent（DSH、Cursor 需要重启应用），让新的 MCP 生效。
- 告诉用户可以这样试：“从我的灵感库里找 5 个复古未来主义风格的网页参考，给出 @引用 ID”。
- 图库网页：`python server.py`，打开 http://127.0.0.1:8765 。macOS 可运行 `python scripts/install_macos_launcher.py` 生成桌面图标。

使用规则见 [AGENTS.md](AGENTS.md)。
