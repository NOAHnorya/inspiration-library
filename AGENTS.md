# 灵感库 · 给 Agent 的说明

这是用户本地的审美灵感库：小红书、抖音收藏夹，公开网页和本地文件，统一存成带稳定 ID 的条目（`@ins_…`），能按标签、关键词、封面配色检索。数据只在本机。

第一次帮用户安装或接入，请按 [AGENT_SETUP.md](AGENT_SETUP.md) 操作。

## 两种用法，任选其一

**有 MCP（推荐）**：工具名以 `inspiration` 服务开头，见下表。
**没有 MCP**：在仓库目录运行 `python cli.py …`，所有命令都输出 JSON。

| 想做什么 | MCP 工具 | 命令行 |
| --- | --- | --- |
| 找灵感 | `find_inspiration` | `python cli.py find "复古未来主义 网页" --tag 高饱和 --limit 8` |
| 看一条详情（可带封面图） | `get_inspiration` | `python cli.py get ins_xxx` |
| 对比 2–5 条 | `compare_inspiration` | `python cli.py compare ins_a ins_b` |
| 生成参考稿 | `create_reference_brief` | `python cli.py brief ins_a ins_b --goal "落地页"` |
| 校验引用 | `validate_references` | `python cli.py validate-refs "参考 @ins_a"` |
| 找相似封面 | `similar_inspiration` | `python cli.py similar ins_xxx` |
| 看有哪些标签 | `list_tags` | `python cli.py tags` |
| 概况和同步状态 | `library_status` | `python cli.py doctor` |
| 同步收藏夹 | `sync_collections` | `python cli.py sync` |
| 待你读取的任务 | `get_sync_tasks` | 看 `data/handoff/*.task.json` |
| 提交你读到的条目 | `submit_collection_records` | `python cli.py sync --submit KEY --records file.json` |
| 加网页 / 本地文件 | `import_url` / `import_file` | `python cli.py import-url URL` / `import-file PATH` |

## 做创作时

1. 先检索，再动手：用户说“参考我收藏的…”“找几个…风格”，先 `find_inspiration`。
2. 方案里用 `@ins_…` 引用具体素材，交付前用 `validate_references` 检查。
3. 需要看图时用 `get_inspiration` 加 `include_cover: true`，或打开结果里的本地封面路径。
4. 标签不够准时，可以用 `python cli.py update ID --add-tag 标签` 帮用户补标签（先告诉用户）。

## 同步收藏夹

`sync_collections` 会自动选择“手”：ego lite 自带的 `ego-browser` → KimiCU → 交给你。

- 前两种在后台运行，用 `library_status` 看进度和结果。
- 返回 `waiting_for_agent` 时，轮到你：按任务里的 `steps`，用你自己的浏览器工具在用户已登录的浏览器里只读读取，每条记 `url`、`title`、`author`、`cover`，保持页面顺序，读到连续 20 条 `known_ids` 里的作品就停。然后调用 `submit_collection_records`。

## 必须遵守

- 只读。不点赞、不收藏、不关注、不评论，不改任何账号设置。
- 不读取、不导出 Cookie、密码、Token。
- 遇到登录、验证码、滑块、“操作过于频繁”，立即停止，请用户本人在浏览器里处理，不要尝试绕过。
- `data/`、`backups/`、`sync_sources.json`、收藏 JSON 是用户的私人数据，不要提交到 Git 或发到网上。
- 服务只绑定 `127.0.0.1`，不要改成对外开放。

## 修改本仓库代码时：提交与合并

1. 在新分支上改，不直接提交到 `main`。
2. 开 PR 前后，都必须由**另一个 Agent**（不是写这批代码的那个）检查冲突：
   - 先 `git fetch origin`，再确认分支能干净合并进最新的 `origin/main`，例如 `git merge-tree --write-tree origin/main HEAD` 没有冲突文件。
   - 确认改动里没有私人数据：`data/`、`backups/`、`private/`、`sync_sources.json`、收藏 JSON、`.mcp.json`、`*.bak-inspiration-*`。
   - 把检查结论（检查的 Agent、对比的 `origin/main` 提交、是否有冲突）写进 PR 评论。
3. 只有检查结论是“无冲突”且 CI 通过，才可以 merge。有冲突时先在分支上解决，再请另一个 Agent 重新检查。
