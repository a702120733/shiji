# 拾集 Shiji

把自己在小红书的点赞、收藏和关注整理到本机。首页采用 [Figma 设计稿](https://www.figma.com/design/HkwSfasAI0PIEikxisf2Mq/)中的设置导入、连接账号、采集进度三个页面。项目代码可公开；个人资料库、签名链接和浏览器登录状态不属于开源仓库。

## 当前能力

- 在本地网页选择点赞、收藏、关注与每类读取上限。在本人 Chrome 的小红书网页登录，使用 OpenCLI 已连接的扩展验证当前账号；拾集不接收密码，不导出 Cookie。
- 后台读取点赞、收藏列表及可访问的笔记正文，下载原图、视频。已下载视频会抽帧并在本地转写语音；增量导入保留旧内容。遇到登录、验证码、访问拒绝或风控会停止并保存已完成进度。
- 在导入中心查看每一步的真实事件与剩余待处理数。点赞和收藏有本机瀑布流资料库、媒体查看、手动分组；关注导入保留综合、最新、最早三种来源顺序，缺少真实主页 ID 的账号标为待核实。
- Chrome 收藏夹可通过用户主动选择导出的 HTML 文件导入，保留原文件夹层级并按一级、二级、三级展示；个人产品可手动添加或移除网址。两者都保存在本机，不读取 Chrome 私有配置目录。
- 下载和预处理不会自动生成准确内容总结。逐条分类与摘要需要模型或人工真实阅读正文、原图、抽帧和完整转写后写入 `analysis.json`，再运行 `render`。未分析内容在资料库里明确显示“待分析”。

## 本机运行

适用环境：macOS、Python 3.12、Chrome、已连接 Chrome 的 OpenCLI 扩展，以及 `ffmpeg`/`ffprobe`。当前适配器按本机 OpenCLI 1.8.6 的接口编写；可先运行 `npm install -g @jackwener/opencli@1.8.6`，再按照 OpenCLI 的扩展连接步骤完成浏览器授权，并在 Chrome 中自行登录小红书。拾集不会安装扩展或打开浏览器调试端口。首次运行会创建 `.venv` 并安装 Python 依赖。Whisper 模型首次使用时另行下载。

```bash
./run.sh
```

打开 `http://127.0.0.1:8879/import`。本地数据默认写入仓库内被 Git 忽略的 `data/`；可通过 `SHIJI_DATA_DIR=/绝对路径 ./run.sh` 和 `SHIJI_PORT=端口号 ./run.sh` 调整。服务只监听 `127.0.0.1`，默认端口不会占用现有本机资料库的 8765。

点击“打开小红书官方网页”是在用户自己的 Chrome 中完成登录，不是小红书官方 OAuth 授权。点击“验证连接”会通过 OpenCLI 在后台读取当前登录账号 ID。首次导入建议每类先读 5 条，确认效果再扩大范围。用户可随时取消，已完成内容保留。

Chrome 收藏夹入口是 `/bookmarks.html`。先在 Chrome 的书签管理器中导出书签 HTML，再在页面选择文件导入；重复导入会替换本机书签副本。`/products.html` 可添加自己的产品名称、网址与简介。开源仓库不包含你的书签、个人产品或任何已采集笔记。

## 补做逐条分析

```bash
./.venv/bin/python shiji/library.py pending --root data/liked
./.venv/bin/python shiji/library.py pending --root data/saved
```

上述命令列出需要实际阅读的 `review.json`。写入 `notes/<id>/analysis.json` 后重新生成页面：

```bash
./.venv/bin/python shiji/library.py render --root data/liked --source liked
./.venv/bin/python shiji/library.py render --root data/saved --source saved
```

`analysis.json` 结构和覆盖范围规则见 [分析格式](docs/analysis-format.md)。不要只根据标题或封面填充完整分析。

## 数据与安全边界

- OpenCLI 适配器以 `shiji-*` 独立名称安装到用户的 `~/.opencli/clis/xiaohongshu/`，不会覆盖现有的 `library-*` 或 `following-list` 适配器。它们仅针对小红书已登录页面执行读取，不会点赞、收藏、评论、关注或发布。
- 资料库中的 `latest-list.json` 和 `notes/*/raw.json` 可能含临时签名链接。它们被 `.gitignore` 排除，网页服务也拒绝直接返回 JSON。不要把 `data/` 放进 Git，也不要直接公开本地服务或将完整资料库部署到云端。
- 书签和个人产品也可能含私人网址，`data/bookmarks.json` 与 `data/products.json` 以仅当前用户可读的权限写入，并由 `.gitignore` 排除。浏览页面仅绑定 `127.0.0.1`。
- 小红书网页结构、可见范围和访问限制可能变化；只保存实际读取到的内容。不绕过验证码、登录要求或安全限制。
- 关注账号昵称可能重复。当前开源版只在来源页面提供真实主页链接时保存该链接，不会凭昵称构造 ID；未核验的关注账号仍可在本机查看但会标明待核实。
- 自动化测试使用合成账号；新仓库尚未用真实账号走完整采集。小红书页面结构与 OpenCLI 接口变化都需要在使用者自己的授权环境中验证。
- 本项目与小红书无关联。使用时遵守网站规则和创作者版权，资料仅用于个人整理。

## 开发

`shiji/app.py` 是本机导入 API 与任务状态；`shiji/import.html`、`import.css`、`import.js` 对应 Figma 的三步导入界面，节点映射见[设计对照](docs/design-map.md)；`shiji/library.py` 负责笔记采集、预处理和渲染；`shiji/local_content.py` 负责用户主动选择的 Chrome 书签与产品链接；`shiji/library-server.py` 提供本地资料库浏览。`tests/` 包含不访问小红书账号的导入任务测试。

```bash
./.venv/bin/python -m unittest discover -s tests -v
```
