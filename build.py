#!/usr/bin/env python3
"""Static site generator for the research notebook.

No framework, no client-side rendering, no external requests.
Dependencies: markdown, pygments  (pip install markdown pygments)

    python build.py              # build into public/
    python build.py --serve 8000 # build, serve, and rebuild on change
    python build.py --check      # build, then verify every internal link
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import markdown

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
THEME = ROOT / "theme"
OUT = ROOT / "public"

# --------------------------------------------------------------------------- #
# small utilities
# --------------------------------------------------------------------------- #


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    value = re.sub(r"[\s_]+", "-", value)
    return re.sub(r"-{2,}", "-", value).strip("-") or "item"


def fmt_date(value: dt.date, style: str = "long") -> str:
    if style == "iso":
        return value.isoformat()
    return f"{value.day} {value.strftime('%B')} {value.year}"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# front matter
# --------------------------------------------------------------------------- #

_FM = re.compile(r"^---\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.S)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _coerce(value: str):
    low = value.strip().lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if re.fullmatch(r"-?\d+", low):
        return int(low)
    return _unquote(value)


def parse_front_matter(text: str) -> tuple[dict, str]:
    m = _FM.match(text)
    if not m:
        return {}, text
    block, body = m.group(1), text[m.end():]
    meta: dict = {}
    lines = block.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        km = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if not km:
            i += 1
            continue
        key, value = km.group(1).lower(), km.group(2).strip()
        i += 1
        continuation: list[str] = []
        while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
            continuation.append(lines[i])
            i += 1
        if value in ("|", ">", "|-", ">-"):
            raw = [l.strip() for l in continuation if l.strip()]
            meta[key] = "\n".join(raw) if value.startswith("|") else " ".join(" ".join(raw).split())
        elif value.startswith("[") and value.endswith("]"):
            meta[key] = [_unquote(x) for x in value[1:-1].split(",") if x.strip()]
        elif not value and continuation:
            items = [l.strip()[1:].strip() for l in continuation if l.strip().startswith("-")]
            meta[key] = items if items else " ".join(" ".join(l.strip() for l in continuation).split())
        else:
            meta[key] = _coerce(value)
    return meta, body


# --------------------------------------------------------------------------- #
# markdown pipeline (math- and code-safe)
# --------------------------------------------------------------------------- #

_FENCE = re.compile(r"(^[ \t]*```.*?^[ \t]*```[ \t]*$)", re.S | re.M)
_INLINE_CODE = re.compile(r"(`+)(?:.+?)\1", re.S)
_MATH_BLOCK = re.compile(r"\$\$(.+?)\$\$", re.S)
_MATH_BRACKET = re.compile(r"\\\[(.+?)\\\]", re.S)
_MATH_INLINE = re.compile(r"(?<!\\)\$(?!\$)([^$\n]+?)(?<!\\)\$")
_MATH_PAREN = re.compile(r"\\\((.+?)\\\)", re.S)

PH = "MTHPH{}PH"
CPH = "CDEPH{}PH"

MD = markdown.Markdown(
    extensions=["toc", "extra", "sane_lists", "codehilite"],
    extension_configs={
        "toc": {"toc_depth": "2-3", "permalink": True, "permalink_class": "h-anchor",
                "permalink_title": "Link to this section"},
        "codehilite": {"guess_lang": False, "css_class": "highlight", "linenums": False},
    },
    output_format="html5",
)

CALLOUT_HINT = re.compile(r'<p>\s*<strong>([^<]{1,40}?)[.:]?\s*</strong>', re.I)


@dataclass
class Render:
    html: str
    toc: str
    words: int


def render_markdown(raw: str) -> Render:
    """Convert markdown, keeping math and inline code away from the parser."""
    store: list[tuple[str, str]] = []

    def stash(kind: str) -> str:
        store.append((kind, ""))
        return PH.format(len(store))

    def sub_math(text: str) -> str:
        def keep(kind: str):
            def _inner(m: re.Match) -> str:
                store.append((kind, m.group(0)))
                return PH.format(len(store))
            return _inner
        text = _MATH_BLOCK.sub(keep("block"), text)
        text = _MATH_BRACKET.sub(keep("block"), text)
        text = _MATH_PAREN.sub(keep("inline"), text)
        text = _MATH_INLINE.sub(keep("inline"), text)
        return text

    parts = _FENCE.split(raw)
    langs = []
    for idx in range(1, len(parts), 2):
        m = re.match(r"[ \t]*```+[ \t]*([\w+#.-]*)", parts[idx])
        langs.append((m.group(1) if m else "").lower())

    for idx, part in enumerate(parts):
        if idx % 2 == 1:
            continue
        # inline code first: it may contain dollar signs
        def keep_code(m: re.Match) -> str:
            store.append(("code", m.group(0)))
            return CPH.format(len(store))
        part = _INLINE_CODE.sub(keep_code, part)
        parts[idx] = sub_math(part)

    MD.reset()
    body = MD.convert("".join(parts))
    toc = MD.toc

    for i, (kind, payload) in enumerate(store, start=1):
        token = PH.format(i) if kind != "code" else CPH.format(i)
        if kind == "code":
            ticks = len(payload) - len(payload.lstrip("`"))
            body = body.replace(token, f"<code>{esc(payload[ticks:-ticks])}</code>")
        elif kind == "inline":
            body = body.replace(token, f'<span class="math math--inline">{esc(payload)}</span>')
        else:
            block = f'<div class="math math--display">{esc(payload)}</div>'
            body = body.replace(f"<p>{token}</p>", block).replace(token, block)

    body = postprocess(body)
    # annotate pygments blocks with their source language (pygments drops it)
    chunks = body.split('<div class="highlight">')
    if len(chunks) > 1:
        rebuilt = [chunks[0]]
        for i, chunk in enumerate(chunks[1:]):
            lang = langs[i] if i < len(langs) else ""
            rebuilt.append(f'<div class="highlight" data-lang="{lang}">' + chunk if lang
                           else '<div class="highlight">' + chunk)
        body = "".join(rebuilt)
    words = len(re.sub(r"<[^>]+>", " ", body).split())
    return Render(html=body, toc=toc, words=words)


def postprocess(body: str) -> str:
    def img(m: re.Match) -> str:
        tag = m.group(0)
        tag = tag.replace("<img ", '<img loading="lazy" decoding="async" ', 1)
        title = re.search(r'title="([^"]*)"', tag)
        if not title:
            return tag
        tag = re.sub(r'\s+title="[^"]*"', "", tag)
        return f'<figure class="fig">{tag}<figcaption>{title.group(1)}</figcaption></figure>'

    body = re.sub(r"<img[^>]*>", img, body)
    body = re.sub(r'<p>\s*(<figure class="fig">.*?</figure>)\s*</p>', r"\1", body, flags=re.S)

    def link(m: re.Match) -> str:
        tag = m.group(0)
        if "target=" in tag:
            return tag
        return tag.replace("<a ", '<a target="_blank" rel="noopener noreferrer" ', 1)

    body = re.sub(r'<a [^>]*href="https?://[^"]*"[^>]*>', link, body)
    body = body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    return body


# --------------------------------------------------------------------------- #
# models
# --------------------------------------------------------------------------- #


@dataclass
class Doc:
    kind: str
    slug: str
    title: str
    meta: dict
    body: str
    toc: str
    words: int
    path: Path
    date: dt.date | None = None
    summary: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        prefix = {"post": "/writing", "project": "/projects", "paper": "/papers"}[self.kind]
        return f"{prefix}/{self.slug}/"

    @property
    def minutes(self) -> int:
        return max(1, round(self.words / 210))

    @property
    def year(self) -> str:
        return str(self.date.year) if self.date else str(self.meta.get("year", ""))


def load_docs(folder: str, kind: str) -> list[Doc]:
    docs: list[Doc] = []
    base = CONTENT / folder
    if not base.exists():
        return docs
    for path in sorted(base.glob("*.md")):
        if path.name.startswith("_"):
            continue
        meta, raw = parse_front_matter(read_text(path))
        if meta.get("draft") is True:
            continue
        stem = path.stem
        date = None
        dm = re.match(r"^(\d{4})-(\d{2})-(\d{2})-(.+)$", stem)
        if dm:
            date = dt.date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
            slug = dm.group(4)
        else:
            slug = stem
        if meta.get("date"):
            try:
                date = dt.date.fromisoformat(str(meta["date"]))
            except ValueError:
                pass
        slug = slugify(str(meta.get("slug", slug)))
        out = render_markdown(raw)
        tags = meta.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        docs.append(
            Doc(
                kind=kind,
                slug=slug,
                title=str(meta.get("title", slug.replace("-", " ").title())),
                meta=meta,
                body=out.html,
                toc=out.toc,
                words=out.words,
                path=path,
                date=date,
                summary=str(meta.get("summary", "")),
                tags=[str(t) for t in tags],
            )
        )
    docs.sort(key=lambda d: (d.date or dt.date.min, d.slug), reverse=True)
    return docs


# --------------------------------------------------------------------------- #
# layout
# --------------------------------------------------------------------------- #

ICON = {
    "arrow": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
    "github": '<svg viewBox="0 0 16 16" class="i-fill" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/></svg>',
    "rss": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 11a9 9 0 0 1 9 9M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1.6"/></svg>',
    "mail": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>',
    "search": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m16.5 16.5 4.5 4.5"/></svg>',
    "sun": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M19.1 4.9l-1.8 1.8M6.7 17.3l-1.8 1.8"/></svg>',
    "moon": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z"/></svg>',
    "lens": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.6"/><circle cx="12" cy="12" r="3.2"/><path d="M12 1.4v2.4M12 20.2v2.4M1.4 12h2.4M20.2 12h2.4"/></svg>',
    "copy": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/></svg>',
}

NAV = [
    ("Writing", "/writing/"),
    ("Projects", "/projects/"),
    ("Papers", "/papers/"),
    ("About", "/about/"),
]


def asset_url(cfg: dict, path: str) -> str:
    return path if path.startswith(("http", "/")) else f"/{path.lstrip('/')}"


def page(cfg: dict, *, title: str, description: str, path: str, content: str,
         body_class: str = "", math: bool = False, head: str = "") -> str:
    site_title = cfg["title"]
    full_title = site_title if not title else f"{title} — {site_title}"
    canonical = cfg["url"].rstrip("/") + path
    og_type = "article" if body_class == "page-article" else "website"
    katex_css = ('<link rel="stylesheet" href="/theme/katex/katex.min.css">' if math else "")
    katex_js = ('<script src="/theme/katex/katex.min.js" defer></script>\n'
                '<script src="/theme/katex/auto-render.min.js" defer></script>\n' if math else "")
    year_now = dt.date.today().year
    start = int(cfg.get("start_year", year_now))
    years = str(year_now) if start >= year_now else f"{start}–{year_now}"
    sha = "" if BUILD_ID in ("dev", "local", "") else f" · {BUILD_ID}"
    nav = "".join(
        '<a href="{href}"{cur}>{label}</a>'.format(
            href=href, label=label,
            cur=' aria-current="page"' if path.startswith(href) else "")
        for label, href in NAV
    )
    gh = f"https://github.com/{cfg['github']}"
    ld = {
        "@context": "https://schema.org",
        "@type": "WebSite" if path == "/" else "WebPage",
        "name": site_title,
        "url": cfg["url"],
        "description": cfg["description"],
        "publisher": {"@type": "Person", "name": cfg["author"], "url": gh},
    }
    return f"""<!doctype html>
<html lang="{cfg.get('locale', 'en')}" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(full_title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{esc(canonical)}">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#fbfaf7">
<meta property="og:type" content="{og_type}">
<meta property="og:title" content="{esc(full_title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(canonical)}">
<meta property="og:site_name" content="{esc(site_title)}">
<meta property="og:image" content="{esc(cfg['url'])}/og.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="alternate" type="application/rss+xml" title="{esc(site_title)} — writing" href="/feed.xml">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
{katex_css}
<link rel="stylesheet" href="/theme/css/site.css?v={BUILD_ID}">
<script>try{{var t=localStorage.getItem('theme');if(t){{document.documentElement.dataset.theme=t}}else if(matchMedia('(prefers-color-scheme: dark)').matches){{document.documentElement.dataset.theme='dark'}}}}catch(e){{}}</script>
<script type="application/ld+json">{json.dumps(ld)}</script>
{head}
</head>
<body class="{body_class}">
<a class="skip" href="#main">Skip to content</a>
<header class="site-head">
  <div class="shell head-inner">
    <a class="brand" href="/" aria-label="{esc(site_title)} — home">
      <span class="brand-mark">{ICON['lens']}</span>
      <span class="brand-text">{esc(site_title)}</span>
    </a>
    <nav class="nav" aria-label="Primary">{nav}</nav>
    <div class="head-tools">
      <button class="icon-btn" type="button" data-search-open aria-label="Search" title="Search (press /)">
        {ICON['search']}<kbd>/</kbd>
      </button>
      <button class="icon-btn" type="button" data-theme-toggle aria-label="Switch theme" title="Switch theme">
        <span class="when-light">{ICON['moon']}</span><span class="when-dark">{ICON['sun']}</span>
      </button>
    </div>
  </div>
  <div class="read-progress" aria-hidden="true"><span id="read-progress-bar"></span></div>
</header>
<main id="main">
{content}
</main>
<footer class="site-foot">
  <div class="shell foot-grid">
    <div class="foot-brand">
      <div class="foot-logo"><span class="brand-mark">{ICON['lens']}</span>{esc(site_title)}</div>
      <p class="foot-note">Prose {esc(cfg['license_prose'])} · code {esc(cfg['license_code'])}.<br>Corrections and replications are welcome.</p>
    </div>
    <div class="foot-cols">
      <div>
        <h2 class="foot-h">Site</h2>
        <ul>{''.join(f'<li><a href="{h}">{l}</a></li>' for l, h in NAV)}<li><a href="/feed.xml">RSS</a></li></ul>
      </div>
      <div>
        <h2 class="foot-h">Elsewhere</h2>
        <ul>
          <li><a href="{gh}" target="_blank" rel="noopener">{ICON['github']}GitHub</a></li>
          {f'<li><a href="mailto:{cfg["email"]}">{ICON["mail"]}Email</a></li>' if cfg.get('email') else ''}
          <li><a href="{gh}/{cfg['github']}.github.io">Source</a></li>
        </ul>
      </div>
    </div>
  </div>
  <div class="shell foot-base">
    <span>© {years} {esc(cfg['author'])}</span>
    <span>Built {dt.date.today().isoformat()}{sha} · <a href="{gh}/{cfg['github']}.github.io">plain HTML, no trackers</a></span>
  </div>
</footer>
<div class="search" id="search" hidden>
  <div class="search-panel" role="dialog" aria-modal="true" aria-labelledby="search-label">
    <div class="search-bar">
      <span class="search-icon">{ICON['search']}</span>
      <label class="visually-hidden" id="search-label" for="search-input">Search this site</label>
      <input id="search-input" type="search" placeholder="Search writing, projects, papers…" autocomplete="off" spellcheck="false">
      <kbd class="search-esc">esc</kbd>
    </div>
    <div class="search-results" id="search-results"></div>
    <div class="search-foot"><span>↑↓ to move</span><span>↵ to open</span><span>{len(TITLES)} entries</span></div>
  </div>
</div>
{katex_js}<script src="/theme/js/site.js?v={BUILD_ID}" defer></script>
</body>
</html>
"""


def section_head(num: str, title: str, href: str = "", label: str = "All") -> str:
    link = (f'<a class="sec-link" href="{href}">{label}<span aria-hidden="true">→</span></a>'
            if href else "")
    return f"""<div class="sec-head">
  <span class="sec-num">{num}</span>
  <h2 class="sec-title">{esc(title)}</h2>
  {link}
</div>"""


def post_rows(posts: list[Doc], limit: int = 0) -> str:
    items = posts[:limit] if limit else posts
    if not items:
        return empty_state(
            "Empty for now",
            "The first entries are being written. Posts appear here as their results are checked.",
            "/feed.xml", "Subscribe via RSS",
        )
    rows = []
    for post in items:
        date = fmt_date(post.date, "iso") if post.date else "—"
        tags = " · ".join(post.tags[:2]) if post.tags else "note"
        rows.append(f"""<li class="row">
    <a class="row-link" href="{post.url}">
      <time class="row-date" datetime="{date}">{date}</time>
      <span class="row-title">{esc(post.title)}</span>
      <span class="row-meta">{esc(tags)} · {post.minutes} min</span>
      <span class="row-arrow" aria-hidden="true">→</span>
    </a>
  </li>""")
    return f'<ol class="rows">{"".join(rows)}</ol>'


def work_cards(projects: list[Doc]) -> str:
    if not projects:
        return empty_state(
            "Code in progress",
            "Repositories are released here once the results they produce are stable enough to cite.",
            f"https://github.com/{CFG['github']}", "Follow on GitHub",
        )
    cards = []
    for i, p in enumerate(projects, start=1):
        chip = p.meta.get("status", "active")
        cards.append(f"""<a class="work" href="{p.url}">
    <span class="work-top"><span class="work-idx">{i:02d}</span><span class="chip chip--{esc(str(chip))}">{esc(str(chip))}</span></span>
    <h3 class="work-title">{esc(p.title)}</h3>
    <p class="work-sum">{esc(p.summary)}</p>
    <span class="work-foot">{''.join(f'<span class="tag">{esc(t)}</span>' for t in p.tags[:3])}</span>
  </a>""")
    return f'<div class="work-grid">{"".join(cards)}</div>'


def empty_state(kicker: str, text: str, href: str, label: str) -> str:
    return f"""<div class="empty">
  <p class="empty-kicker">{esc(kicker)}</p>
  <p class="empty-text">{esc(text)}</p>
  <a class="btn btn--ghost" href="{esc(href)}">{esc(label)}{ICON['arrow']}</a>
</div>"""


# --------------------------------------------------------------------------- #
# pages
# --------------------------------------------------------------------------- #


def build_home(cfg: dict, posts: list[Doc], projects: list[Doc], papers: list[Doc]) -> str:
    hero = cfg["hero"]
    lines = [ln.strip() for ln in str(hero["headline"]).split("|")]
    headline = "<br>".join(
        re.sub(r"\*(.+?)\*", r"<em>\1</em>", esc(ln)) for ln in lines
    )
    sections_html = "".join(
        f"""<a class="area" href="{esc(s.get('href', '/'))}">
      <p class="area-note">{esc(s.get('note', ''))}</p>
      <h3 class="area-title">{esc(s['title'])}<span class="area-arrow" aria-hidden="true">→</span></h3>
      <p class="area-body">{esc(s.get('body', ''))}</p>
    </a>"""
        for s in cfg.get("sections", [])
    )
    gh = f"https://github.com/{cfg['github']}"

    latest = posts[0] if posts else None
    if latest:
        side = f"""<div class="now">
        <div class="now-head"><span class="kicker">Latest</span><span class="now-stamp">{latest.date.strftime('%Y-%m-%d') if latest.date else ''}</span></div>
        <a class="side-post" href="{latest.url}">
          <span class="side-post-title">{esc(latest.title)}</span>
          <span class="side-post-sum">{esc(latest.summary)}</span>
          <span class="side-post-meta">{latest.minutes} min read · {' · '.join(latest.tags[:3])}</span>
        </a>
        <a class="side-sub" href="/feed.xml">{ICON['rss']}<span>Subscribe via RSS</span></a>
      </div>"""
    else:
        side = f"""<div class="now">
        <div class="now-head"><span class="kicker">Latest</span></div>
        <p class="side-post-sum">No posts yet. The first one will land here.</p>
        <a class="side-sub" href="/feed.xml">{ICON['rss']}<span>Subscribe via RSS</span></a>
      </div>"""

    notice = cfg.get("notice") or {}
    notice_html = ""
    if notice.get("text") and notice.get("enabled", True) is not False:
        link = ""
        if notice.get("link_label"):
            href = notice.get("link_href", "/about/")
            link = (f'<a class="notice-link" href="{esc(href)}">'
                    f'{esc(notice["link_label"])}<span aria-hidden="true">→</span></a>')
        notice_html = f"""<section class="notice" aria-label="Publication status">
  <div class="shell notice-inner">
    <p class="notice-label"><span class="notice-dot" aria-hidden="true"></span>{esc(notice.get('label', 'Status'))}</p>
    <p class="notice-text">{esc(notice['text'])} {link}</p>
  </div>
</section>

"""

    content = f"""<section class="hero">
  <div class="shell hero-grid">
    <div class="hero-main">
      <p class="eyebrow"><span class="pulse"></span>{esc(hero['eyebrow'])}</p>
      <h1 class="hero-title">{headline}</h1>
      <p class="hero-lede">{esc(hero['lede'])}</p>
      <div class="hero-actions">
        <a class="btn btn--primary" href="{esc(hero['primary_href'])}">{esc(hero['primary_label'])}{ICON['arrow']}</a>
        <a class="btn btn--ghost" href="{gh}" target="_blank" rel="noopener">{ICON['github']}{esc(hero['secondary_label'])}</a>
      </div>
    </div>
    <aside class="hero-side" aria-label="Latest post">
      {side}
    </aside>
  </div>
</section>

{notice_html}<section class="shell band band--areas">
  {section_head('01', 'What is here')}
  <div class="area-grid">{sections_html}</div>
</section>

<section class="shell band">
  {section_head('02', 'Writing', '/writing/', 'All posts')}
  {post_rows(posts, 5)}
</section>
"""
    if projects:
        content += f"""<section class="shell band">
  {section_head('03', 'Projects', '/projects/', 'All projects')}
  {work_cards(projects[:4])}
</section>
"""
    if papers:
        items = "".join(paper_row(p, i) for i, p in enumerate(papers[:3], start=1))
        num = "04" if projects else "03"
        content += f"""<section class="shell band">
  {section_head(num, 'Papers', '/papers/', 'All papers')}
  <ol class="papers">{items}</ol>
</section>
"""
    return page(cfg, title="", description=cfg["description"], path="/",
                content=content, body_class="page-home")


def paper_row(paper: Doc, index: int) -> str:
    authors = paper.meta.get("authors", "")
    venue = paper.meta.get("venue", "")
    status = paper.meta.get("status", "preprint")
    links = []
    for key, label in (("pdf", "PDF"), ("code", "Code"), ("doi", "DOI"), ("arxiv", "arXiv")):
        value = paper.meta.get(key)
        if value:
            links.append(f'<a href="{esc(value)}" target="_blank" rel="noopener">{label}</a>')
    return f"""<li class="paper">
  <div class="paper-side"><span class="paper-num">{index:02d}</span><span class="paper-year">{esc(paper.year)}</span></div>
  <div class="paper-main">
    <h3 class="paper-title"><a href="{paper.url}">{esc(paper.title)}</a></h3>
    <p class="paper-authors">{esc(authors)}</p>
    <p class="paper-venue">{esc(venue)}</p>
    <p class="paper-links">{' '.join(links)}</p>
  </div>
  <span class="chip chip--{esc(str(status))}">{esc(str(status))}</span>
</li>"""


def build_listing(cfg: dict, posts: list[Doc], tags: dict[str, list[Doc]],
                  active_tag: str = "", tag_label: str = "") -> str:
    if active_tag:
        items = tags.get(active_tag, [])
        heading = f'<h1 class="page-title">Tagged <em>{esc(tag_label or active_tag)}</em></h1>'
        sub = (f'<p class="page-lede">{len(items)} post{"s" if len(items) != 1 else ""}. '
               f'<a href="/writing/">Back to all writing</a>.</p>')
        path = f"/writing/tag/{active_tag}/"
    else:
        heading = '<h1 class="page-title">Writing</h1>'
        sub = ('<p class="page-lede">Working notes, method write-ups, and technical posts. '
               'Long-form results land here after the numbers hold up.</p>')
        path = "/writing/"
        items = posts
    tag_cloud = "".join(
        f'<a class="tag-pill{" is-active" if t == active_tag else ""}" href="/writing/tag/{t}/">'
        f'{esc(label)}<span>{len(tags[t])}</span></a>'
        for label, t in sorted(((LABELS.get(t, t), t) for t in tags), key=lambda x: x[0].lower())
    ) if tags else ""
    content = f"""<section class="shell page-head">
  <p class="kicker">Index</p>
  {heading}
  {sub}
  <div class="tag-cloud">{tag_cloud}</div>
</section>
<section class="shell band band--tight">
  {post_rows(items)}
</section>"""
    return page(cfg, title=f"Writing · {active_tag}" if active_tag else "Writing",
                description=cfg["description"], path=path, content=content,
                body_class="page-listing")


def build_post(cfg: dict, post: Doc, prev: Doc | None, nxt: Doc | None) -> str:
    tags = "".join(f'<a class="tag" href="/writing/tag/{quote(t)}/">{esc(t)}</a>' for t in post.tags)
    share = f"{cfg['url'].rstrip('/')}{post.url}"
    nav = []
    if prev:
        nav.append(f'<a class="art-nav-item" href="{prev.url}"><span>Newer</span>{esc(prev.title)}</a>')
    if nxt:
        nav.append(f'<a class="art-nav-item art-nav-item--next" href="{nxt.url}"><span>Older</span>{esc(nxt.title)}</a>')
    toc = f'<nav class="toc" aria-label="Contents"><p class="toc-h">Contents</p>{post.toc}</nav>' if post.toc else ""
    content = f"""<article class="article">
  <div class="shell">
    <header class="art-head">
      <p class="kicker"><a href="/writing/">Writing</a> <span aria-hidden="true">/</span> {esc(post.date.strftime('%Y') if post.date else '')}</p>
      <h1 class="art-title">{esc(post.title)}</h1>
      {f'<p class="art-lede">{esc(post.summary)}</p>' if post.summary else ''}
      <dl class="art-meta">
        <div><dt>Published</dt><dd>{fmt_date(post.date) if post.date else '—'}</dd></div>
        <div><dt>Reading</dt><dd>{post.minutes} min</dd></div>
        <div><dt>Tags</dt><dd class="art-tags">{tags or '—'}</dd></div>
      </dl>
    </header>
    <div class="art-grid">
      <aside class="art-rail">{toc}</aside>
      <div class="prose" data-prose>{post.body}</div>
    </div>
    <footer class="art-foot">
      <div class="art-cite">
        <p class="kicker">Cite</p>
        <code>{esc(cfg['author'])}. “{esc(post.title)}.” {esc(cfg['title'])}, {post.date.isoformat() if post.date else ''}. {esc(share)}</code>
      </div>
      <nav class="art-nav" aria-label="More posts">{''.join(nav)}</nav>
    </footer>
  </div>
</article>"""
    head = f"""<meta property="article:published_time" content="{post.date.isoformat() if post.date else ''}">
<script type="application/ld+json">{json.dumps({
        "@context": "https://schema.org", "@type": "BlogPosting",
        "headline": post.title, "datePublished": post.date.isoformat() if post.date else "",
        "author": {"@type": "Person", "name": cfg["author"]},
        "description": post.summary, "url": cfg["url"].rstrip("/") + post.url})}</script>"""
    return page(cfg, title=post.title, description=post.summary or cfg["description"],
                path=post.url, content=content, body_class="page-article", head=head,
                math='class="math' in post.body)


def build_projects(cfg: dict, projects: list[Doc]) -> str:
    content = f"""<section class="shell page-head">
  <p class="kicker">Index</p>
  <h1 class="page-title">Projects</h1>
  <p class="page-lede">Research software and the experiments it runs. Each entry links to a repository, a
  reproducible command, and — where it exists — the write-up.</p>
</section>
<section class="shell band band--tight">{work_cards(projects)}</section>"""
    return page(cfg, title="Projects", description="Research software and experiments.",
                path="/projects/", content=content, body_class="page-listing")


def build_project(cfg: dict, project: Doc) -> str:
    repo = project.meta.get("repo")
    repo_html = ""
    if repo:
        repo_html = f'<a class="btn btn--ghost" href="{esc(repo)}" target="_blank" rel="noopener">{ICON["github"]}Repository</a>'
    content = f"""<article class="article article--project">
  <div class="shell">
    <header class="art-head">
      <p class="kicker"><a href="/projects/">Projects</a> <span aria-hidden="true">/</span> {project.year}</p>
      <h1 class="art-title">{esc(project.title)}</h1>
      {f'<p class="art-lede">{esc(project.summary)}</p>' if project.summary else ''}
      <div class="art-actions">{repo_html}</div>
    </header>
    <div class="art-grid">
      <aside class="art-rail"></aside>
      <div class="prose" data-prose>{project.body}</div>
    </div>
  </div>
</article>"""
    return page(cfg, title=project.title, description=project.summary,
                path=project.url, content=content, body_class="page-article",
                math='class="math' in project.body)


def build_papers(cfg: dict, papers: list[Doc]) -> str:
    if papers:
        body = f'<ol class="papers">{"".join(paper_row(p, i) for i, p in enumerate(papers, 1))}</ol>'
    else:
        body = empty_state(
            "In preparation",
            "Manuscripts appear here once they are posted. Preprints will link to their code and data.",
            f"https://github.com/{cfg['github']}", "Follow on GitHub",
        )
    content = f"""<section class="shell page-head">
  <p class="kicker">Publications</p>
  <h1 class="page-title">Papers</h1>
  <p class="page-lede">Preprints and published work, each paired with the code that produced its figures.</p>
</section>
<section class="shell band band--tight">{body}</section>"""
    return page(cfg, title="Papers", description="Preprints and publications.",
                path="/papers/", content=content, body_class="page-listing")


def build_about(cfg: dict, about: Doc | None) -> str:
    body = about.body if about else "<p>About page coming soon.</p>"
    gh = f"https://github.com/{cfg['github']}"
    contact = [(gh, "GitHub", ICON["github"]), ("/feed.xml", "RSS", ICON["rss"])]
    if cfg.get("email"):
        contact.insert(0, (f"mailto:{cfg['email']}", "Email", ICON["mail"]))
    contact_html = "".join(
        f'<a class="contact" href="{esc(href)}">{icon}<span>{esc(label)}</span></a>'
        for href, label, icon in contact
    )
    content = f"""<section class="shell page-head">
  <p class="kicker">About</p>
  <h1 class="page-title">Who writes this</h1>
</section>
<section class="shell band band--tight">
  <div class="about-grid">
    <div class="prose" data-prose>{body}</div>
    <aside class="about-side">
      <p class="kicker">Elsewhere</p>
      <div class="contact-list">{contact_html}</div>
      <p class="kicker kicker--spaced">License</p>
      <p class="about-note">Prose: {esc(cfg['license_prose'])}. Code: {esc(cfg['license_code'])}. Cite with a link back to the original page.</p>
    </aside>
  </div>
</section>"""
    return page(cfg, title="About", description=cfg["description"], path="/about/",
                content=content, body_class="page-about", math=bool(about and 'class="math' in about.body))


def build_search(cfg: dict) -> str:
    content = """<section class="shell page-head">
  <p class="kicker">Search</p>
  <h1 class="page-title">Find something</h1>
  <p class="page-lede">Press <kbd>/</kbd> anywhere to search. Titles, tags, and summaries are indexed — no server, no analytics.</p>
</section>
<section class="shell band band--tight">
  <div class="search-inline">
    <div class="search-bar"><span class="search-icon">""" + ICON['search'] + """</span>
      <label class="visually-hidden" for="page-search-input">Search</label>
      <input id="page-search-input" type="search" placeholder="Search writing, projects, papers…" autocomplete="off">
    </div>
    <div class="search-results" id="page-search-results"></div>
  </div>
</section>"""
    return page(cfg, title="Search", description="Search this site.", path="/search/",
                content=content, body_class="page-listing")


def build_404(cfg: dict) -> str:
    content = f"""<section class="shell page-head page-head--404">
  <p class="kicker">404</p>
  <h1 class="page-title">This page is not in the index.</h1>
  <p class="page-lede">The link may be old, or the page was renamed. Try <a href="/writing/">writing</a>,
  <a href="/projects/">projects</a>, or <a href="/search/">search</a>.</p>
  <a class="btn btn--primary" href="/">Back to the front page{ICON['arrow']}</a>
</section>"""
    return page(cfg, title="Not found", description="Page not found.", path="/404.html",
                content=content, body_class="page-404")


# --------------------------------------------------------------------------- #
# feeds, sitemap, assets
# --------------------------------------------------------------------------- #


def build_feed(cfg: dict, posts: list[Doc]) -> str:
    updated = posts[0].date if posts and posts[0].date else dt.date.today()
    items = []
    for post in posts[:20]:
        date = (post.date or dt.date.today()).isoformat()
        items.append(f"""<item>
  <title>{esc(post.title)}</title>
  <link>{cfg['url'].rstrip('/')}{post.url}</link>
  <guid isPermaLink="true">{cfg['url'].rstrip('/')}{post.url}</guid>
  <pubDate>{dt.datetime.fromisoformat(date).strftime('%a, %d %b %Y 00:00:00 +0000')}</pubDate>
  <description>{esc(post.summary)}</description>
  <content:encoded><![CDATA[{post.body}]]></content:encoded>
</item>""")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
<title>{esc(cfg['title'])}</title>
<link>{cfg['url']}</link>
<description>{esc(cfg['description'])}</description>
<language>{cfg.get('locale', 'en')}</language>
<lastBuildDate>{dt.datetime.combine(updated, dt.time()).strftime('%a, %d %b %Y 00:00:00 +0000')}</lastBuildDate>
<atom:link href="{cfg['url']}/feed.xml" rel="self" type="application/rss+xml"/>
{''.join(items)}
</channel>
</rss>
"""


def build_sitemap(cfg: dict, urls: list[tuple[str, str]]) -> str:
    entries = "".join(
        f"<url><loc>{esc(cfg['url'].rstrip('/') + path)}</loc><lastmod>{date}</lastmod></url>"
        for path, date in urls
    )
    return f'<?xml version="1.0" encoding="utf-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>\n'


FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="12" fill="#14161a"/>
<g fill="none" stroke="#f4f2ec" stroke-width="2.6">
<circle cx="32" cy="32" r="18"/><circle cx="32" cy="32" r="6"/>
<path d="M32 6v6M32 52v6M6 32h6M52 32h6"/></g>
<circle cx="32" cy="32" r="2.4" fill="#ff7a3d"/></svg>
"""


def copy_assets() -> None:
    if (THEME / "css").exists():
        shutil.copytree(THEME, OUT / "theme", dirs_exist_ok=True)
    assets = CONTENT / "assets"
    if assets.exists():
        shutil.copytree(assets, OUT / "assets", dirs_exist_ok=True)
    for name in ("CNAME", "robots.txt", "og.png"):
        src = CONTENT / name
        if src.exists():
            shutil.copy2(src, OUT / name)


def git_id() -> str:
    for env in ("GITHUB_SHA",):
        sha = os.environ.get(env)
        if sha:
            return sha[:7]
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, timeout=5).stdout.strip() or "local"
    except Exception:
        return "local"


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #

BUILD_ID = "dev"
TITLES: list[str] = []
LABELS: dict[str, str] = {}
CFG: dict = {}


def reset_out() -> None:
    """Clear public/ tolerating Windows file locks held by a running preview server."""
    for old in ROOT.glob("public.stale.*"):
        shutil.rmtree(old, ignore_errors=True)
    if not OUT.exists():
        OUT.mkdir(parents=True)
        return
    for attempt in range(6):
        try:
            shutil.rmtree(OUT)
            OUT.mkdir(parents=True)
            return
        except OSError:
            for path in OUT.rglob("*"):
                try:
                    os.chmod(path, 0o666)
                except OSError:
                    pass
            time.sleep(0.12 * (attempt + 1))
    stale = OUT.with_name(f"public.stale.{int(time.time())}")
    try:
        OUT.rename(stale)
    except OSError:
        pass
    OUT.mkdir(parents=True, exist_ok=True)


def build(verbose: bool = True, clean: bool = True) -> int:
    global BUILD_ID, TITLES, CFG
    CFG = tomllib.loads(read_text(ROOT / "site.toml"))
    BUILD_ID = git_id()

    if clean:
        reset_out()
    else:
        # dev mode: the preview server may hold file handles, so never delete the tree
        OUT.mkdir(parents=True, exist_ok=True)
        for stale in OUT.rglob("*.html"):
            stale.unlink(missing_ok=True)

    posts = load_docs("posts", "post")
    projects = load_docs("projects", "project")
    papers = load_docs("papers", "paper")
    about_docs = load_docs("pages", "post")
    about = next((d for d in about_docs if d.slug == "about"), None)

    tags: dict[str, list[Doc]] = {}
    LABELS.clear()
    for post in posts:
        for tag in post.tags:
            key = slugify(tag)
            LABELS.setdefault(key, tag)
            tags.setdefault(key, []).append(post)

    TITLES = [p.title for p in posts + projects + papers]

    def write(path: str, text: str) -> None:
        target = OUT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    write("index.html", build_home(CFG, posts, projects, papers))
    write("writing/index.html", build_listing(CFG, posts, tags))
    for tag in tags:
        write(f"writing/tag/{tag}/index.html",
              build_listing(CFG, posts, tags, active_tag=tag, tag_label=LABELS.get(tag, tag)))
    for i, post in enumerate(posts):
        newer = posts[i - 1] if i > 0 else None
        older = posts[i + 1] if i + 1 < len(posts) else None
        write(f"writing/{post.slug}/index.html", build_post(CFG, post, newer, older))
    write("projects/index.html", build_projects(CFG, projects))
    for project in projects:
        write(f"projects/{project.slug}/index.html", build_project(CFG, project))
    write("papers/index.html", build_papers(CFG, papers))
    write("about/index.html", build_about(CFG, about))
    write("search/index.html", build_search(CFG))
    write("404.html", build_404(CFG))
    write("feed.xml", build_feed(CFG, posts))
    write(".nojekyll", "")
    write("favicon.svg", FAVICON)

    urls = [("/", (posts[0].date if posts else dt.date.today()).isoformat()), ("/writing/", (posts[0].date if posts else dt.date.today()).isoformat()),
            ("/projects/", dt.date.today().isoformat()), ("/papers/", dt.date.today().isoformat()),
            ("/about/", dt.date.today().isoformat())]
    urls += [(p.url, (p.date or dt.date.today()).isoformat()) for p in posts]
    urls += [(p.url, dt.date.today().isoformat()) for p in projects]
    write("sitemap.xml", build_sitemap(CFG, urls))

    index = [
        {"t": p.title, "u": p.url, "k": p.kind, "s": p.summary, "g": p.tags,
         "d": p.date.isoformat() if p.date else ""}
        for p in posts + projects + papers
    ]
    write("search-index.json", json.dumps(index, ensure_ascii=False, indent=0))

    copy_assets()
    if verbose:
        total = sum(1 for _ in OUT.rglob("*") if _.is_file())
        print(f"built {total} files → public/  ({len(posts)} posts, {len(projects)} projects, {len(papers)} papers)")
    return 0


def check_links() -> int:
    bad = []
    pages = list(OUT.rglob("*.html"))
    for path in pages:
        text = path.read_text(encoding="utf-8")
        for href in re.findall(r'(?:href|src)="(/[^"#?]*)"', text):
            if href.startswith("//"):
                continue
            target = OUT / href.lstrip("/")
            if href.endswith("/"):
                target = target / "index.html"
            if not target.exists():
                bad.append((path.relative_to(OUT), href))
    if bad:
        print(f"{len(bad)} broken internal link(s):")
        for page_path, href in bad[:40]:
            print(f"  {page_path} → {href}")
        return 1
    print(f"links ok across {len(pages)} pages")
    return 0


def serve(port: int) -> None:
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class Quiet(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(OUT), **kw)

        def log_message(self, fmt, *args):
            if " 404 " in (fmt % args):
                sys.stderr.write(f"404 {self.path}\n")

    server = ThreadingHTTPServer(("127.0.0.1", port), Quiet)

    def snapshot() -> dict[Path, float]:
        roots = [ROOT / "site.toml", ROOT / "build.py"]
        for folder in ("content", "theme"):
            roots.extend((ROOT / folder).rglob("*"))
        return {p: p.stat().st_mtime for p in roots if p.is_file()}

    def watch() -> None:
        stamps = snapshot()
        while True:
            time.sleep(1.2)
            current = snapshot()
            if current != stamps:
                stamps = current
                try:
                    build(verbose=False, clean=False)
                    print("rebuilt", flush=True)
                except Exception as exc:
                    print("build failed:", exc, flush=True)

    threading.Thread(target=watch, daemon=True).start()
    print(f"serving http://127.0.0.1:{port}/  (ctrl-c to stop)", flush=True)
    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the research notebook.")
    parser.add_argument("--serve", nargs="?", const=8000, type=int, metavar="PORT")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    build()
    if args.check:
        return check_links()
    if args.serve:
        serve(args.serve)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
