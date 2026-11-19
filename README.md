# 灵感库 Inspiration Library

一个本地优先、可独立运行的个人灵感素材库。把小红书、抖音、公开网页和本地文件整理成统一条目，通过标签、全文、轻量语义和封面视觉特征检索，并用稳定 ID 将一条或多条灵感交给 Agent 引用。

**你的收藏内容不属于开源代码。** 数据库、封面、原始收藏 JSON 和备份默认都不会进入 Git。

## 功能

- 统一导入小红书、抖音收藏 JSON、公开网页和本地文件
- 本地封面保存、稳定素材 ID、重复导入更新
- 自动标签：标题规则 + 同义词 + 封面颜色/布局分析
- 标签包含/排除、AND/OR、平台与收藏夹筛选
- 全文与本地语义混合搜索，无需模型 API Key
- 封面颜色与布局相似搜索
- 多素材对比、命名组合、Agent 引用与引用校验
- 本地 Web 图库、健康检查、索引重建、ZIP 备份与恢复
- 可选：通过本机浏览器一键增量更新指定收藏夹
- 可选：macOS 桌面应用图标与一键启动器

## 先了解边界

- 默认使用本地 JSON 导入；浏览器增量更新是可选功能，不会自动登录或实时同步小红书/抖音。
- 请仅整理自己有权访问的内容并遵守平台规则；遇到验证码或风控会停止，不要尝试绕过。
- 自动解读采用本地规则与图像统计，不是多模态大模型，也不会把素材发送给云端模型。
- 服务没有登录鉴权，只绑定 `127.0.0.1`。不要改成 `0.0.0.0` 或暴露到公网。
- 开源许可证仅覆盖本项目代码和自制示例。第三方笔记、封面等内容的权利归原作者或相关权利人。

## 前置条件

| 项目 | 要求 |
| --- | --- |
| Python | 3.9 或更高版本 |
| pip | 随 Python 安装，用于安装依赖 |
| SQLite | 使用 Python 自带版本，需支持 FTS5 trigram；通常无需单独安装 |
| 浏览器 | 最新版 Chrome、Edge、Firefox 或 Safari，仅用于打开本地页面 |
| 网络 | 仅下载封面或读取公开网页时需要；示例和已有素材检索可离线运行 |

不需要 Node.js、Docker、数据库服务、OpenAI/Claude API Key，也不需要安装小红书或抖音开发者工具。可选的浏览器同步与桌面启动器仅在 macOS 上使用；同步另需 egolite 和 KimiCU，详见 [收藏夹更新指南](docs/SYNC.md)。

macOS / Linux 的终端命令如下。Windows 可使用 PowerShell，将 `python3` 换成 `py -3`，并用 `.venv\Scripts\Activate.ps1` 激活虚拟环境。

## 5 分钟跑起来

### 1. 获取项目

```bash
git clone https://github.com/NOAHnorya/inspiration-library.git
cd inspiration-library
```

如果下载的是 ZIP，先解压，再进入解压后的 `inspiration-library` 目录。

### 2. 创建独立环境并安装依赖

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

以后每次使用先进入项目目录并执行 `source .venv/bin/activate`。

### 3. 检查 SQLite 检索能力

```bash
python -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute(\"CREATE VIRTUAL TABLE t USING fts5(content, tokenize='trigram')\"); print('SQLite OK')"
```

看到 `SQLite OK` 即可继续。若报错，请换用支持 FTS5 trigram 的新版 Python，而不是修改数据库文件。

### 4. 用离线示例验证

项目自带两张自制示例封面，不需要登录或联网：

```bash
python cli.py import-file examples/y2k-poster.png
python cli.py import-file examples/minimal-poster.png
python cli.py annotate
python cli.py reindex
python cli.py find "Y2K 海报"
python cli.py search --tag Y2K
python cli.py health
```

预期：前两条命令各返回一个 `ins_file_...` ID；`find` 和标签搜索能找到示例；最后的健康检查中 `ok` 为 `true`。

### 5. 打开图库

```bash
python server.py
```

浏览器打开 **http://127.0.0.1:8765**。停止服务时回到终端按 `Ctrl+C`。

若端口被占用：

```bash
PORT=8766 python server.py
```

然后访问 `http://127.0.0.1:8766`。

## 导入自己的素材

### 小红书 / 抖音

准备 JSON 数组，每条至少包含标题、作者、链接和收藏夹名。`cover` 是原始封面 URL；没有时可留空，也可以改为导入本地图片，生成独立的本地素材条目。

```json
[
  {
    "platform": "douyin",
    "collection": "我的收藏夹",
    "title": "笔记或作品标题",
    "author": "作者昵称",
    "url": "https://www.douyin.com/video/1234567890123456789",
    "cover": "https://example.com/cover.jpg"
  }
]
```

导入命令：

```bash
python cli.py import-douyin /path/to/douyin.json
python cli.py import-xhs /path/to/xiaohongshu.json
python cli.py annotate
python cli.py reindex
```

链接格式要求：抖音为 `/video/数字ID` 或 `/note/数字ID`；小红书链接末尾为 24 位十六进制笔记 ID。

仅导入元数据、不下载封面时加 `--no-download`。没有可用本地封面的条目标记为 `needs_review`，这是待补充状态，不是程序崩溃。

完整格式、离线抖音 AX 快照转换方式和重复导入行为见 [导入指南](docs/DATA_IMPORT.md)。

### 公开网页 / 本地文件

```bash
python cli.py import-url https://example.com
python cli.py import-file /path/to/image-or-project-file
python cli.py annotate
python cli.py reindex
```

网页导入只读取公开 HTML 元数据。需要登录、出现验证码或访问失败时会保留待复核状态，不会尝试绕过。

也可以在图库右上角选择“导入与记录”，粘贴本机文件路径或公开 URL。

## 可选：一键更新与桌面启动

配置自己的收藏夹后，点击页面右上角“更新收藏”即可增量导入新增内容。收藏夹地址、账号核对信息和原始 JSON 都保存在本地，配置默认被 Git 忽略：

```bash
cp sync_sources.example.json sync_sources.json
# 编辑 sync_sources.json 后运行
python sync_collections.py
```

macOS 用户还可以安装带图标的桌面启动器：

```bash
python scripts/install_macos_launcher.py
```

完整配置、风控暂停规则和使用限制见 [收藏夹更新与桌面启动指南](docs/SYNC.md)。

## 标签检索与 Agent 引用

```bash
# 关键词 + 多标签，默认要求同时满足所有标签
python cli.py search "网页设计" --tag Y2K --tag 高饱和

# 任一标签命中
python cli.py search --tag 复古 --tag Y2K --match any

# 排除标签，并限定收藏夹
python cli.py search --tag 海报 --exclude 暗色调 --collection 我的收藏夹

# 按收藏夹页面原始顺序正向或反向浏览
python cli.py search --collection 我的收藏夹 --sort collection_asc
python cli.py search --collection 我的收藏夹 --sort collection_desc

# Agent 友好的精简结果，包含 @稳定引用 ID
python cli.py find "复古未来主义 网页" --limit 5

# 查看完整素材；ID 以 find 的实际输出为准
python cli.py get ins_file_xxx

# 对比或组合 2–5 条素材
python cli.py compare ins_file_xxx ins_file_yyy
python cli.py brief ins_file_xxx ins_file_yyy --goal "设计一个开发者工具落地页"

# 检查一段提示词中的引用是否都存在
python cli.py validate-refs "参考 @ins_file_xxx 和 @ins_file_yyy"

# 查找颜色与布局相似的素材
python cli.py similar ins_file_xxx --limit 10
```

在 Agent 对话中，可以先让它执行 `find`，再把返回的 `@ins_...` 放入创作提示词。引用指向本地原始素材和来源链接，不只是标题文本。

## 数据位置、备份与恢复

默认所有私人数据保存在项目下的 `data/`，备份写入 `backups/`；两者已被 `.gitignore` 排除。

```bash
python cli.py stats
python cli.py health
python cli.py backup
```

备份到指定位置：

```bash
python cli.py backup --output /path/to/inspiration-backup.zip
```

恢复目录必须不存在或为空，工具不会覆盖已有数据：

```bash
python cli.py restore /path/to/inspiration-backup.zip /path/to/empty-directory
```

若想把数据与代码分开，CLI 使用全局 `--data-dir`（放在子命令前）：

```bash
python cli.py --data-dir /path/to/private-data stats
```

Web 服务使用环境变量：

```bash
INSPIRATION_DATA_DIR=/path/to/private-data python server.py
```

## 常见问题

**`python3: command not found`**：先从 [python.org](https://www.python.org/downloads/) 安装 Python 3.9+，安装后重开终端。

**`No module named ...`**：确认已激活 `.venv`，再运行 `python -m pip install -r requirements.txt`。

**端口被占用**：使用 `PORT=8766 python server.py`，不要结束不认识的进程。

**封面失败或 `needs_review`**：检查网络与原始 URL，或在详情中重试；原始元数据仍会保留。原始链接失效时可以改为导入本地图片。

**搜索结果不理想**：运行 `python cli.py annotate` 和 `python cli.py reindex`，或在详情页添加人工标签。自动标签只是辅助，人工标签与锁定标签不会被重新标注覆盖。

**数据会不会上传 GitHub？** 只要保留仓库中的 `.gitignore`，`data/`、`backups/`、`private/` 和根目录的收藏 JSON 就不会被 Git 跟踪。发布前仍必须执行 `git status` 人工检查。

## 项目结构

```text
core.py               统一数据、SQLite、导入和本地资产
tagging.py            标签、全文与语义检索
agent_tools.py        Agent 查找、对比和组合引用
groups.py             命名组合
maintenance.py        视觉索引、健康检查、备份恢复
cli.py                命令行入口
server.py             本地 FastAPI 服务
sync_collections.py   可选的只读增量收藏更新
sync_config.py        同步配置校验
kimicu_mcp.py         本机浏览器控制接口
static/               Web 图库
extract_douyin_ax.py  离线 AX 快照转换器
scripts/              macOS 桌面启动器安装与运行脚本
assets/               自制应用图标
examples/             可公开分发的虚构 JSON 与自制封面
docs/                 导入、同步和发布指南
```

## 参与与发布

欢迎围绕导入格式、检索质量、可访问性和文档提出建议。修改后请至少完成离线示例流程、CLI 检索、Web 页面和健康检查。

项目代码使用 [MIT License](LICENSE)。准备上传自己的 GitHub 仓库时，按 [GitHub 发布指南](docs/GITHUB.md) 操作，尤其不要提交私人收藏和账号信息。
