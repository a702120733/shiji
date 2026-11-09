# 拾集

## 项目介绍

拾集是一个本地运行的个人资料库，把自己在小红书的点赞、收藏、关注，以及 Chrome 收藏夹整理成可浏览、搜索和分组的内容。笔记可保存原图与视频；开启分析后，还能按实际读取到的正文和媒体生成分类与简短摘要。

在线入口：[shiji-local.vercel.app](https://shiji-local.vercel.app)。需要在同一台电脑启动本机服务并确认配对；在线站点不托管个人资料。

项目代码开放，导入的数据留在使用者自己的电脑上。仓库不包含个人资料库、浏览器登录状态或临时签名链接。

## 当前能力

- 在本地网页选择点赞、收藏、关注与每类读取上限。在本人 Chrome 的小红书网页登录，使用 OpenCLI 已连接的扩展验证当前账号；拾集不接收密码，不导出 Cookie。
- 后台读取点赞、收藏列表及可访问的笔记正文，下载原图、视频。已下载视频会抽帧并在本地转写语音；增量导入保留旧内容。遇到登录、验证码、访问拒绝或风控会停止并保存已完成进度。
- 在导入中心查看每一步的真实事件与剩余待处理数。点赞和收藏有本机瀑布流资料库、媒体查看、手动分组；关注导入保留综合、最新、最早三种来源顺序，缺少真实主页 ID 的账号标为待核实。
- Chrome 收藏夹可在页面一次授权本机读取当前 Chrome 配置后自动导入；再次打开书签页会自动同步。保留原文件夹层级并按一级、二级、三级展示。HTML 文件导入作为备用方式；个人产品可手动添加或移除网址。
- 导入页默认勾选“自动分类与总结”，使用当前用户已登录的 Codex CLI 逐条读取正文、全部原图、视频抽帧和转写，再写入有覆盖记录的 `analysis.json`。用户可关闭该选项。模型失败、素材缺失或证据不足时保留“待分析”或“部分”标记，不凭标题补全结论。
- 在线首页先选择小红书或 Chrome，再进入各自的授权导入流程；右上角“读取本机资料”可查看连接状态和当前资料目录，并通过本机系统选择已有拾集文件夹或 ZIP 资料包，确认内容后打开。

## 快速开始

适用环境：macOS、Python 3.12、Chrome、`ffmpeg`/`ffprobe`，以及连接到 Chrome 的 OpenCLI 扩展。当前适配器按 OpenCLI 1.8.6 的接口编写；可先运行 `npm install -g @jackwener/opencli@1.8.6`，再按照 OpenCLI 的扩展连接步骤完成浏览器授权。拾集不会安装扩展或打开浏览器调试端口。首次运行会创建 `.venv` 并安装 Python 依赖；首次使用视频转写时还会下载 Whisper 模型。

```bash
git clone https://github.com/a702120733/shiji.git
cd shiji
./run.sh
```

## 使用说明

1. 打开 `http://127.0.0.1:8879/import`，先选择小红书或 Chrome。抖音入口标为“即将上线”。选择小红书后，再选择点赞、收藏或关注及每类读取上限；首次建议选择 100 条。选择 Chrome 会进入收藏夹授权导入页。
2. 在自己的 Chrome 中登录小红书，在导入页点击“验证连接”。验证只读取当前登录账号，不需要在拾集里输入密码。
3. 按需开启“自动分类与总结”，然后开始导入。在页面查看采集和分析进度；遇到验证码、登录或访问限制时，已完成的内容会保留。
4. 导入完成后浏览资料库，使用搜索、分组和媒体查看功能。需要整合 Chrome 收藏夹时，打开 `/bookmarks.html` 并点击“授权读取并自动导入”；个人产品链接在 `/products.html` 管理。

使用[在线首页](https://shiji-local.vercel.app)时，先选程序；首次连接会打开本机配对窗口。右上角“读取本机资料”会显示连接、选择、检查与打开的状态。连接后可直接查看当前配置的资料目录，或点击“选择资料文件夹”“选择 ZIP 文件包”，在 macOS 系统选择器中选定已有拾集资料。页面会显示所选路径和可识别内容，确认后才打开。文件夹在本机只读浏览，不复制素材；ZIP 在本机解压并显示读取进度，网页不会上传资料包。需要选择的是包含拾集页面与数据标记的资料，不是任意文件夹或普通书签 HTML。

macOS 上本地数据默认写入 `~/Library/Application Support/Shiji/data/`。可通过 `SHIJI_DATA_DIR=/绝对路径 ./run.sh` 和 `SHIJI_PORT=端口号 ./run.sh` 调整。服务只监听 `127.0.0.1`，默认端口不会占用现有本机资料库的 8765。

如果想发布网页但让账号资料继续保存在每位用户的电脑上，参见[云端界面与本机数据](docs/cloud-local.md)。`cloud/` 只包含公开的界面与连接代码；笔记、原图、视频、书签、账号信息和导入任务仍由本机服务管理。线上网页须在运行本机服务的**同一台电脑**上打开，并由用户主动配对。

如需登录后自动启动并在意外退出后重启，在 macOS 上运行 `./.venv/bin/python scripts/service.py install`；移除登录项运行 `./.venv/bin/python scripts/service.py uninstall`。安装时会把运行代码和虚拟环境复制到 `~/Library/Application Support/Shiji/`，避免 macOS 登录项无法读取 Documents 下的项目；数据和日志也保存在该目录。更新项目代码后重新运行 `install` 即可同步运行副本。启用前请先停止手动运行的 `./run.sh`，避免端口冲突。

只检查导入界面时，可改用 `./.venv/bin/python scripts/service.py install-demo`。它在 8879 端口展示醒目的测试标识，数据写入独立的 `~/Library/Application Support/Shiji/demo-data/`；登录和导入步骤只做模拟，Chrome 书签读取接口也会拒绝访问真实配置。用 `install` 切回可实际导入的版本。测试模式不会自动读取个人资料；只有你在“读取本机资料”中明确选择已有文件夹或资料包并确认后，才会单独只读打开所选内容。

若要用另一个小红书账号真实测试授权和导入，可运行 `./.venv/bin/python scripts/service.py install-account-test 当前账号主页ID`，然后打开 `http://127.0.0.1:8880/import`。该服务使用独立的 `account-test-data/`，默认每类读取 100 条，可在下拉菜单中选择 200、500 或 1000 条；连接时会拒绝当前账号 ID，只有在 Chrome 登录了不同账号后才能继续；不会合并到既有资料库。移除测试服务可运行 `uninstall-account-test`。

已有本机资料库时，可在安装测试服务前设置 `SHIJI_PREVIOUS_ACCOUNT_URL=http://127.0.0.1:8765/accounts.html`，导入页会显示“返回原账号”。这个入口只切换资料库页面，不更改 Chrome 中的小红书登录账号。

已有本机资料库可在账号设置页显示经过主页核验的昵称和本机头像副本，并用“添加账号”进入 8880 的独立授权流程。页面可由 `scripts/render_account_settings.py --root 资料库路径` 从私有的 `account-profile.json` 生成；私有 JSON 不通过网页服务公开。

点击“打开小红书官方网页”是在用户自己的 Chrome 中完成登录，不是小红书官方 OAuth 授权。点击“验证连接”会通过 OpenCLI 在后台读取当前登录账号 ID。自动分类需要本机已登录的 Codex CLI；可运行 `codex login status` 检查。开启时，选中的正文、原图、视频抽帧和转写会交由 Codex 模型处理；不希望发送这些内容时可取消勾选，稍后手动分析。首次导入建议从最低的 100 条开始，确认效果再扩大范围。用户可随时取消，已完成内容保留。

Chrome 收藏夹入口是 `/bookmarks.html`。点击“授权读取并自动导入”后，拾集在本机读取 Chrome 最近使用的配置的 `Bookmarks` 文件，不需要导出 HTML，也不需要 Chrome 密码或 Cookie。授权仅限这个配置；之后打开页面会自动同步。若 Chrome 文件不可访问，可展开备用的 HTML 导入方式。`/products.html` 可添加自己的产品名称、网址与简介。开源仓库不包含你的书签、个人产品或任何已采集笔记。

## 补做逐条分析

```bash
./.venv/bin/python shiji/library.py pending --root "$HOME/Library/Application Support/Shiji/data/liked"
./.venv/bin/python shiji/library.py pending --root "$HOME/Library/Application Support/Shiji/data/saved"
```

上述命令列出需要实际阅读的 `review.json`。写入 `notes/<id>/analysis.json` 后重新生成页面：

```bash
./.venv/bin/python shiji/library.py render --root "$HOME/Library/Application Support/Shiji/data/liked" --source liked
./.venv/bin/python shiji/library.py render --root "$HOME/Library/Application Support/Shiji/data/saved" --source saved
```

`analysis.json` 结构和覆盖范围规则见 [分析格式](docs/analysis-format.md)。不要只根据标题或封面填充完整分析。

## 数据与安全边界

- OpenCLI 适配器以 `shiji-*` 独立名称安装到用户的 `~/.opencli/clis/xiaohongshu/`，不会覆盖现有的 `library-*` 或 `following-list` 适配器。它们仅针对小红书已登录页面执行读取，不会点赞、收藏、评论、关注或发布。
- 自动分类仅在导入设置中开启时运行。它通过用户自己的 Codex 登录调用模型；内容会发送给该模型服务，分析记录和素材副本仍保存在本机。模型调用使用只读沙箱与临时会话，不向模型提供签名链接或账号 Cookie。
- 资料库中的 `latest-list.json` 和 `notes/*/raw.json` 可能含临时签名链接。它们被 `.gitignore` 排除，网页服务也拒绝直接返回 JSON。不要把 `data/` 放进 Git，也不要直接公开本地服务或将完整资料库部署到云端。
- 使用云端界面时，浏览器会把已配对的本机资料发送给该网页的 JavaScript 以便展示；资料不会作为网站构建产物上传，但站点代码及其托管账号必须可信。配对仅授予指定的精确站点来源，停止本机服务可终止当前连接。
- “读取本机资料”由本机系统选择器返回所选路径，网页不能自行扫描电脑文件。选择文件夹后只读浏览原文件；选择 ZIP 后在本机解压，不能将资料包上传到 Vercel。配对后打开的资料页只监听 `127.0.0.1`；如需编辑分组或继续同步，应在正式资料库中操作。
- 书签和个人产品也可能含私人网址，`data/bookmarks.json`、`data/bookmarks-access.json` 与 `data/products.json` 以仅当前用户可读的权限写入，并由 `.gitignore` 排除。读取 Chrome 书签只发生在用户点击授权后，且只访问已授权配置的 `Bookmarks` 文件；不读取密码、Cookie 或浏览记录。浏览页面仅绑定 `127.0.0.1`。
- 小红书网页结构、可见范围和访问限制可能变化；只保存实际读取到的内容。不绕过验证码、登录要求或安全限制。
- 关注账号昵称可能重复。当前开源版只在来源页面提供真实主页链接时保存该链接，不会凭昵称构造 ID；未核验的关注账号仍可在本机查看但会标明待核实。
- 自动化测试使用合成账号；新仓库尚未用真实账号走完整采集。小红书页面结构与 OpenCLI 接口变化都需要在使用者自己的授权环境中验证。
- 本项目与小红书无关联。使用时遵守网站规则和创作者版权，资料仅用于个人整理。

## 开发

`shiji/app.py` 是本机导入 API 与任务状态；`shiji/import.html`、`import.css`、`import.js` 对应 Figma 的三步导入界面，节点映射见[设计对照](docs/design-map.md)；`shiji/library.py` 负责笔记采集、预处理和渲染，`shiji/analysis_engine.py` 在开启时调用 Codex 做逐条分析；`shiji/chrome_bookmarks.py` 读取用户授权的本机 Chrome 书签，`shiji/local_content.py` 负责备用 HTML 解析与个人产品链接；`shiji/library-server.py` 提供本地资料库浏览。`tests/` 包含不访问小红书账号的导入任务测试。

```bash
./.venv/bin/python -m unittest discover -s tests -v
```
