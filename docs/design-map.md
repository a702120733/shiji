# Figma 与实现对照

设计文件：[小红书工作台](https://www.figma.com/design/HkwSfasAI0PIEikxisf2Mq/)。当前开源版实现以下三个导入节点：

| 设计节点 | 页面阶段 | 代码位置 |
| --- | --- | --- |
| `3:15927` | 首页与导入设置 | `shiji/import.html` 的 `settings-stage`，`shiji/import.css` 的 `.settings-grid`、`.source-card` |
| `3:16116` | 获取网页授权（实现为 Chrome 登录验证） | `shiji/import.html` 的 `connect-stage`，`shiji/import.js` 的 `check-connection` |
| `3:16278` | 抓取与整理进度 | `shiji/import.html` 的 `progress-stage`，`shiji/import.js` 的 `renderJob()` |

视觉变量在 `shiji/import.css` 的 `:root`：页面底色 `--paper`、侧栏 `--sidebar`、文字 `--ink`、辅助文字 `--muted`、边线 `--line`、主按钮 `--red`。页面宽度由 `.app-shell` 的侧栏宽度和 `.content` 的 `max-width` 控制；卡片间距由 `.settings-grid` 与 `.source-grid` 的 `gap` 控制。

设计稿中的相册拼贴为示意视觉，仓库未包含来源授权不明的照片；使用可发布的 CSS 图形替代。进度不伪造百分比，显示真实阶段、处理数与事件。

导入前侧栏仅显示“导入中心”；导入完成后，`shiji/import.js` 的 `updateNavigation()` 根据实际保存数量显示来源入口，并使用已分析笔记的分类结果生成侧栏链接。导入设置增加可关闭的 Codex 自动分类选项，明确告知模型会处理所选内容。
