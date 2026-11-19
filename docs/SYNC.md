# 收藏夹一键更新与桌面启动器

基础导入和检索不需要以下配置。只有希望点击“更新收藏”自动读取指定收藏夹时，才需要配置浏览器同步。

## 前置条件

- macOS
- 已安装 egolite 和 KimiCU，并允许 KimiCU 使用辅助功能
- 已自行在 egolite 登录对应平台账号
- 收藏夹内容为自己有权访问和整理的内容

同步器只使用 KimiCU 的本机只读页面结构、导航和滚动能力，不读取或导出 Cookie、密码、Token。不会自动登录，也不会绕过验证码或风控。平台页面结构变化可能导致提取失败，此时应以失败提示为准，不要假设已完整同步。

## 配置收藏夹

在项目根目录执行：

```bash
cp sync_sources.example.json sync_sources.json
```

编辑 `sync_sources.json`。这个文件已被 `.gitignore` 排除，不会提交到 GitHub。

小红书示例：

```json
{
  "key": "xhs_design",
  "platform": "xiaohongshu",
  "collection": "设计灵感",
  "url": "https://www.xiaohongshu.com/board/你的收藏夹ID?source=web_profile_page",
  "file": "private/xiaohongshu_design.json"
}
```

抖音示例：

```json
{
  "key": "douyin_videos",
  "platform": "douyin",
  "collection": "视频灵感",
  "profile_url": "https://www.douyin.com/user/self?from_tab_name=main&showSubTab=favorite_folder&showTab=favorite_collection",
  "file": "private/douyin_videos.json"
}
```

字段说明：

- `key`：唯一英文标识，只使用小写字母、数字和下划线。
- `collection`：页面显示的收藏夹名称，也用于灵感库筛选。
- `url`：小红书收藏夹完整地址。
- `profile_url`：抖音账号的收藏夹列表页，不是单个视频地址。
- `file`：本地原始 JSON 的保存位置，相对项目根目录。建议放在已被 Git 忽略的 `private/`。
- `account_marker`：抖音可选字段，用于核对页面上的账号昵称；不设置则只检查收藏夹名称。
- 顶层 `browser_app`：默认 `com.citrolabs.ego.lite`。

多个收藏夹在 `sources` 数组中依次填写。公共仓库中的示例 ID 是占位符，需要替换。

## 使用

打开灵感库页面，点击右上角“更新收藏” → “开始更新”。

也可以用 CLI：

```bash
python sync_collections.py

# 只更新指定 key
python sync_collections.py --only xhs_design

# 使用其他配置文件
python sync_collections.py --config /path/to/private-sync-config.json

# 已有 JSON 可单独回填收藏页顺序，不启动浏览器
python sync_collections.py --rebuild-order
```

同步器会：

1. 在浏览器新开一个标签页，依次读取配置的收藏夹。
2. 抖音会等待收藏夹卡片真正可点击，点击后确认作品列表出现，再开始读取。
3. 每轮滚动后等待 2–3 秒，合并当前页面条目。
4. 连续读取到至少 20 条已入库内容，或页面不再产生新内容时停止。
5. 只把新 ID 导入灵感库，旧素材不会因页面未完整加载而被删除。
6. 记录收藏页顺序，下载封面、自动标注并建立索引；封面网络错误会额外重试一次。

“页面标称数量”和“实际可读数量”可能不同。结果中的 `found` 是本轮实际读取数量，不是收藏夹总数量；本地原始 JSON 采用增量合并，不能用本轮 `found` 判断是否有收藏被删除。

需要登录或处理验证时，状态变为 `paused`。在浏览器中由你本人处理，然后重新点击更新。出现风控时当前同步会停止，不会切换账号或通道继续请求。

状态保存在 `data/sync_status.json`，日志保存在 `data/sync.log`，均在 Git 忽略范围内。不要把这些文件发布到仓库。

KimiCU 不在默认路径时，可设置环境变量：

```bash
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
