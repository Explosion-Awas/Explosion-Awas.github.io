# explosion-awas.github.io

个人博客的源码。Markdown 写在 `content/`，一个 Python 脚本生成静态 HTML 到 `public/`，GitHub Actions 负责构建和发布到 GitHub Pages。

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
  posts/        文章，文件名 YYYY-MM-DD-slug.md
  projects/     项目，文件名 slug.md
  papers/       论文，文件名 slug.md
  pages/        about.md 等固定页
  assets/       图片，构建时复制到 /assets/
  _templates/   三个模板，复制出来改就行（不会被构建）
theme/
  css/site.css  所有样式（设计变量在文件顶部）
  js/site.js    主题切换、代码复制、阅读进度、搜索
  fonts/        自托管 woff2
  katex/        自托管 KaTeX
site.toml       站点标题、首页文案、三个入口卡片
build.py        生成器，约 1000 行，只依赖 markdown + pygments
```

## 写一篇新文章

复制 `content/_templates/post.md` 到 `content/posts/2026-11-01-my-post.md`。文件名里的日期就是发布日期，也会出现在 URL 里：`/writing/my-post/`。

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

论文条目的 `arxiv` / `pdf` / `doi` / `code` 字段有哪个显示哪个。

## 改站点信息

- 标题、副标题、首页大标题、简介、三个入口卡片：`site.toml`
- 配色、字号、间距：`theme/css/site.css` 顶部的 `:root` 和 `[data-theme="dark"]`
- 导航项：`build.py` 里的 `NAV` 列表

## 发布

推到 `main` 分支即触发 `.github/workflows/pages.yml`：安装依赖 → 构建 → 检查链接 → 上传 artifact → 部署到 Pages。

首次使用需要在仓库 **Settings → Pages** 里把 Source 设为 **GitHub Actions**（若尚未设置）。构建失败时 Actions 日志会给出具体原因，链接检查失败会列出坏链的页面。

## 说明

- 字体：Newsreader（标题与正文）、IBM Plex Sans（界面）、JetBrains Mono（代码与元信息），全部 woff2 自托管。
- 数学：KaTeX 0.19，按需加载，不进首页。
- 主题：跟随系统，可手动切换，选择存在 localStorage。
- 搜索：构建时生成 `search-index.json`，浏览器端过滤，不依赖服务端。
- RSS：`/feed.xml`，全文放在 `content:encoded` 里。
