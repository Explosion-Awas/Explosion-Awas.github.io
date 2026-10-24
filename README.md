# explosion-awas.github.io

「Explosion Awas」的源码：一个魔法工业风格的个人输出站，内容主要来自 agent 自动产出。

这些内容没有经过逐条复核，公开不代表准确或经过验证。

Markdown 写在 `content/en/` 和 `content/zh/`，一个 Python 脚本生成静态 HTML 到 `public/`，GitHub Actions 负责构建和发布到 GitHub Pages。

英文在根路径，中文在 `/zh/`。页头的 `EN / 中` 开关会跳到对应的那一页，不会退回首页。

没有前端框架，没有 CDN，没有统计脚本。字体和 KaTeX 都在仓库里，页面在断网或受限网络下渲染结果一致。

线上地址：https://explosion-awas.github.io

## 本地预览

需要 Python 3.11+ 和两个包：

```bash
pip install markdown pygments
python build.py --serve 8000     # 打开 http://127.0.0.1:8000
```

`--serve` 会监听 `content/`、`theme/`、`site.toml`，改完保存自动重建。

```bash
python build.py            # 只构建
python build.py --check    # 构建 + 检查所有站内链接（CI 用这个，链接坏了会失败）
```

## 目录

```
content/
  en/           英文源文件
    posts/      文章，文件名 YYYY-MM-DD-slug.md
    projects/   项目，文件名 slug.md（可选）
    papers/     论文，文件名 slug.md（可选）
    pages/      about.md
  zh/           中文源文件，结构完全一样
  assets/       图片，构建时复制到 /assets/
  _templates/   三个模板，复制出来改就行（不会被构建）
  og.png        分享卡片，由 tools/make_og.py 生成
theme/
  css/site.css  所有样式（颜色、圆角、字体在文件顶部）
  js/site.js    主题切换、代码复制、阅读进度、搜索
  fonts/        7 个自托管 woff2
  katex/        自托管 KaTeX
site.toml       站点信息、首页文案、两套 UI 文案
build.py        生成器，约 1200 行，只依赖 markdown + pygments
tools/make_og.py  重新生成 og.png（可选，需要 Pillow）
```

两套语言的页面按 slug 配对：`content/en/posts/2026-11-01-my-post.md` 对应 `content/zh/posts/2026-11-01-my-post.md`，URL 分别是 `/writing/my-post/` 和 `/zh/writing/my-post/`。中文缺某一篇也没关系，开关会退到中文首页。

## 写一篇新文章

复制 `content/_templates/post.md` 到 `content/en/posts/2026-11-01-my-post.md`，再复制一份到 `content/zh/posts/`。文件名里的日期就是发布日期，也会出现在 URL 里。

```markdown
---
title: 标题
date: 2026-11-01
tags: [notes, method]
summary: >
  一到两句摘要。会出现在列表、RSS 和页面 meta description 里。
draft: false
---

正文。
```

- `draft: true` 的文章不会被构建，也不会出现在列表里。
- `tags` 请用英文小写 slug，两种语言共用同一批标签页；显示名在 `site.toml` 的 `[en.tag_labels]` / `[zh.tag_labels]` 里翻译。
- 支持 `$行内公式$` 和 `$$独立公式$$`（KaTeX，只有含公式的页面才加载 KaTeX）。
- 代码块用围栏 + 语言名，构建时高亮，右上角有复制按钮。
- 表格、脚注 `[^1]`、图片（`![alt](/assets/x.png "图注")`，title 会变成图注）都支持。
- 提示框用原生 HTML（里面的 Markdown 仍会解析）：

```html
<div class="callout">
<p><strong>小标题</strong>正文。</p>
</div>
```

## 添加项目 / 论文

`content/_templates/project.md` 和 `paper.md` 里有全部字段说明。项目文件里 `repo` 留空就不显示仓库按钮；`featured: true` 会让它出现在首页（最多 4 个）。

论文条目的 `arxiv` / `pdf` / `doi` / `code` 字段有哪个显示哪个。中英文各放一份即可，slug 保持一致。

## 改站点信息

- 标题、副标题、首页大标题、简介、入口卡片、说明条、各种 UI 文案：`site.toml`。共享字段在文件顶部，英文在 `[en]`，中文在 `[zh]`。
- 配色、字号、间距、圆角：`theme/css/site.css` 顶部的 `:root` 和 `[data-theme="dark"]`。
- 导航项：`build.py` 里的 `NAV` 列表（标签文案在 `site.toml` 的 `nav_*`）。
- 页脚、搜索、空状态：`site.toml` 的 `[en.ui]` / `[zh.ui]`。
- 分享卡片：改完视觉后运行 `python tools/make_og.py` 重新生成 `content/og.png`（需要 Pillow；Windows 下用系统自带的 Georgia 和 Consolas 字体）。

### 设计约定

- 圆角只有几档：控件 4px，面板 8px，胶囊 999px，贴纸和铭牌这类小件 2–3px。
- 主色是青绿色 `--accent` 和古铜色 `--brass`，配羊皮纸底；暗色主题单独一套 token。
- 首页的魔法阵、小锅炉吉祥物和压力表都是构建时生成的 SVG / CSS，没有外部图片。
- 动效都包在 `prefers-reduced-motion` 里；网址加 `?theme=dark` 可以直接看暗色主题。

## 发布

推到 `main` 分支即触发 `.github/workflows/pages.yml`：安装依赖 → 构建 → 检查链接 → 上传 artifact → 部署到 Pages → 线上冒烟检查（中英文页面、语言开关、标题）。

首次使用需要在仓库 **Settings → Pages** 里把 Source 设为 **GitHub Actions**（若尚未设置）。构建失败时 Actions 日志会给出具体原因，链接检查失败会列出坏链的页面。

## 说明

- 字体：Newsreader（英文标题与正文）、IBM Plex Sans（界面）、JetBrains Mono（代码与元信息），全部 woff2 自托管；中文回落到系统宋体 / 苹方 / 微软雅黑。
- 数学：KaTeX 0.19，按需加载，不进首页。
- 主题：跟随系统，可手动切换，选择存在 localStorage；两种语言共用一套样式。
- 搜索：构建时为每种语言生成一个 `search-index.json`，浏览器端过滤，不依赖服务端。
- RSS：`/feed.xml` 和 `/zh/feed.xml`，全文放在 `content:encoded` 里。
- 构建产物 `public/` 已被 `.gitignore` 忽略，CI 每次都会重新生成。
