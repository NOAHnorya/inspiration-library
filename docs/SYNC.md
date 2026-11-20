# 收藏夹一键更新与桌面启动器

基础导入和检索不需要以下配置。只有希望点击“更新收藏”或运行 `python cli.py sync` 自动读取指定收藏夹时，才需要配置同步。

最简单的方式：运行 `python cli.py init`，按提示选择你的 Agent、添加收藏夹；或让你的 Agent 按 [AGENT_SETUP.md](../AGENT_SETUP.md) 帮你完成。

## 同步方式（“手”）

同步本身是一段固定流程，不需要大模型参与：打开收藏夹 → 读取 → 滚动 → 读到旧内容就停。负责操作浏览器的部分可以替换：

| driver | 需要什么 | 平台 | 说明 |
| --- | --- | --- | --- |
| `ego-browser` | [ego lite](https://lite.ego.app/)，并在其中登录小红书 / 抖音 | macOS、Windows | 推荐。用 ego lite 自带的 Agent 接口，在独立任务空间里运行，不占用鼠标和你的标签页，直接读取页面里的链接 |
| `kimicu` | KimiCU，并允许其使用辅助功能 | macOS | 读取浏览器窗口的辅助功能树（默认操作 ego lite，可用 `browser_app` 改成其他浏览器的 bundle id） |
| `handoff` | 任何带浏览器工具的 Agent | 任意 | 灵感库生成读取任务，由你的 Agent 用它自己的浏览器读取后交回 |

`auto`（默认）按上表顺序选第一个可用的。查看本机情况：

```bash
python cli.py doctor
python sync_collections.py --list-drivers
```

为什么没有 agent-desktop 驱动：它读取的辅助功能树里没有链接地址，拿不到笔记 / 作品 ID，就无法可靠去重和增量更新。

所有方式共同遵守：只读；不读取或导出 Cookie、密码、Token；不自动登录；遇到验证码、滑块或“操作过于频繁”立即停止，不切换账号或通道继续请求。平台页面结构变化可能导致提取失败，此时以失败提示为准，不要假设已完整同步。

## 配置收藏夹

推荐用 `python cli.py init` 生成。也可以手动：

```bash
cp sync_sources.example.json sync_sources.json
```

`sync_sources.json` 已被 `.gitignore` 排除，不会提交到 GitHub。

```json
{
  "driver": "auto",
  "sources": [
    {
      "key": "xhs_design",
      "platform": "xiaohongshu",
      "collection": "设计灵感",
      "url": "https://www.xiaohongshu.com/board/你的专辑ID?source=web_profile_page",
      "file": "private/xiaohongshu_design.json"
    },
    {
      "key": "douyin_videos",
      "platform": "douyin",
      "collection": "视频灵感",
      "profile_url": "https://www.douyin.com/user/self?from_tab_name=main&showSubTab=favorite_folder&showTab=favorite_collection",
      "account_marker": "你的抖音昵称",
      "file": "private/douyin_videos.json",
      "driver": "handoff"
    }
  ]
}
```

字段说明：

- `driver`：顶层为默认方式，单个收藏夹可以单独指定。可选 `auto`、`ego-browser`、`kimicu`、`handoff`。
- `key`：唯一英文标识，只使用小写字母、数字和下划线。
- `collection`：页面显示的收藏夹名称，也用于灵感库筛选。
- `url`：小红书专辑完整地址。
- `profile_url`：抖音账号的收藏夹列表页，不是单个视频地址。
- `file`：本地原始 JSON 的保存位置，相对 `sync_sources.json` 所在目录。建议放在已被 Git 忽略的 `private/`。
- `account_marker`：抖音可选字段，用于核对页面上的账号昵称。
- 顶层 `browser_app`：仅 `kimicu` 使用，默认 `com.citrolabs.ego.lite`。

## 使用

打开灵感库页面，点击右上角“更新收藏” → “开始更新”。也可以：

```bash
python cli.py sync                      # 全部
python cli.py sync --only xhs_design    # 只更新一个
python cli.py sync --driver ego-browser # 临时指定方式
python sync_collections.py --rebuild-order  # 已有 JSON 回填收藏顺序，不启动浏览器
```

在 Agent 里：调用 MCP 工具 `sync_collections`，再用 `library_status` 查看结果。

同步器会：

1. 打开配置的收藏夹（抖音会先核对账号、点开对应收藏夹，确认作品列表出现）。
2. 每轮滚动后等待 2–3 秒，合并当前页面条目。
3. 连续读取到至少 20 条已入库内容，或页面不再产生新内容时停止。
4. 只把新 ID 导入灵感库；旧素材不会因页面未完整加载而被删除，已有的标题、作者、封面也不会被空值覆盖。
5. 记录收藏页顺序，下载封面、自动标注并建立索引；封面网络错误会额外重试一次。

第一次同步会从头读到尾，收藏多时需要几分钟，主要时间花在下载封面。结果中的 `found` 是本轮实际读取数量，不是收藏夹总数量。

## 交给你的 Agent 读取（handoff）

`handoff` 适合没有 ego lite / KimiCU，但你的 Agent 自带浏览器的情况（例如 Claude in Chrome、Codex、OpenClaw）。

1. 运行同步（或在 Agent 里调用 `sync_collections`），结果为 `waiting_for_agent`。
2. 任务写在 `data/handoff/<key>.task.json`：打开哪个地址、读哪些字段、何时停止、已有的作品 ID。Agent 也可以用 MCP 工具 `get_sync_tasks` 读取。
3. Agent 用自己的浏览器只读读取后，调用 `submit_collection_records`；没有 MCP 时，把 JSON 数组写到任务里的 `result_path`，再运行 `python cli.py sync --only <key>`，或直接：

```bash
python cli.py sync --submit <key> --records 结果.json
```

灵感库会校验链接格式，丢弃无效条目，然后按正常流程去重、导入。

## 状态与日志

- `paused`：需要登录或处理验证。在浏览器中由你本人处理，然后重新更新。
- `waiting_for_agent`：等待 Agent 读取并提交。
- 状态保存在 `data/sync_status.json`，日志在 `data/sync.log`，均在 Git 忽略范围内。

找不到工具时可以指定路径：

```bash
export EGO_BROWSER_BIN=/path/to/ego-browser
export KIMICU_BIN=/path/to/kimi-cu
```

## macOS 桌面启动器

安装依赖后运行：

```bash
python scripts/install_macos_launcher.py
```

桌面会生成带应用图标的 `灵感库.app`。双击后若服务未运行则自动启动，已运行则只打开页面，避免重复启动。默认端口为 `8765`。

指定端口或更新本工具创建的应用：

```bash
python scripts/install_macos_launcher.py --port 58150 --replace
```

启动器使用执行安装时的 Python 环境，因此建议先激活项目的 `.venv` 再安装。若项目目录或虚拟环境被移动，需要重新执行安装。启动失败时查看 `~/Library/Logs/InspirationLibrary.log`。
