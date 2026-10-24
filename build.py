#!/usr/bin/env python3
"""Static site generator for the atelier notebook.

Two languages, one source tree, no framework, no client-side rendering and no
external requests. Dependencies: markdown, pygments.

    python build.py              # build into public/
    python build.py --serve 8000 # build, serve, and rebuild on change
    python build.py --check      # build, then verify every internal link
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
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


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def fmt_date(value: dt.date | None, lang: str, style: str = "stamp") -> str:
    if not value:
        return "·"
    if style == "stamp":
        return f"{value.year}.{value.month:02d}.{value.day:02d}"
    if lang == "zh":
        return f"{value.year} 年 {value.month} 月 {value.day} 日"
    return f"{value.day} {value.strftime('%B')} {value.year}"


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


@dataclass
class Render:
    html: str
    toc: str
    words: int


def render_markdown(raw: str) -> Render:
    """Convert markdown, keeping math and inline code away from the parser."""
    store: list[tuple[str, str]] = []

    def stashed(kind: str, payload: str) -> str:
        store.append((kind, payload))
        return PH.format(len(store))

    def sub_math(text: str) -> str:
        def keep(kind: str):
            def _inner(m: re.Match) -> str:
                return stashed(kind, m.group(0))
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
    lang: str
    prefix: str
    date: dt.date | None = None
    summary: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def rel(self) -> str:
        base = {"post": "/writing", "project": "/projects", "paper": "/papers"}[self.kind]
        return f"{base}/{self.slug}/"

    @property
    def url(self) -> str:
        return self.prefix + self.rel

    @property
    def minutes(self) -> int:
        return max(1, round(self.words / 210))

    @property
    def year(self) -> str:
        return str(self.date.year) if self.date else str(self.meta.get("year", ""))


def load_docs(lang: str, prefix: str, folder: str, kind: str) -> list[Doc]:
    docs: list[Doc] = []
    base = CONTENT / lang / folder
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
                lang=lang,
                prefix=prefix,
                date=date,
                summary=str(meta.get("summary", "")),
                tags=[str(t) for t in tags],
            )
        )
    docs.sort(key=lambda d: (d.date or dt.date.min, d.slug), reverse=True)
    return docs


@dataclass
class Lang:
    code: str
    prefix: str
    cfg: dict
    ui: dict
    tag_labels: dict
    status_labels: dict
    posts: list[Doc]
    projects: list[Doc]
    papers: list[Doc]
    about: Doc | None
    tags: dict[str, list[Doc]]
    labels: dict[str, str]
    paths: set[str] = field(default_factory=set)

    def t(self, key: str, **kw) -> str:
        value = str(self.ui.get(key, key))
        return value.format(**kw) if kw else value

    def href(self, rel: str) -> str:
        if rel.startswith(("http", "#")):
            return rel
        return self.prefix + (rel if rel.startswith("/") else "/" + rel)

    def label(self, tag: str) -> str:
        return self.labels.get(slugify(tag), tag)

    def status(self, value: object) -> str:
        return str(self.status_labels.get(str(value), value))

    @property
    def locale(self) -> str:
        return str(self.cfg.get("locale", self.code))


def build_langs() -> dict[str, Lang]:
    langs: dict[str, Lang] = {}
    default = str(CFG.get("default_lang", "en"))
    for code in CFG.get("languages", [default]):
        prefix = "" if code == default else f"/{code}"
        cfg = CFG[code]
        posts = load_docs(code, prefix, "posts", "post")
        projects = load_docs(code, prefix, "projects", "project")
        papers = load_docs(code, prefix, "papers", "paper")
        pages = load_docs(code, prefix, "pages", "post")
        about = next((d for d in pages if d.slug == "about"), None)
        tags: dict[str, list[Doc]] = {}
        labels: dict[str, str] = {}
        for post in posts:
            for tag in post.tags:
                key = slugify(tag)
                labels.setdefault(key, str(cfg.get("tag_labels", {}).get(key, tag)))
                tags.setdefault(key, []).append(post)
        paths = {"/", "/writing/", "/projects/", "/papers/", "/about/", "/search/"}
        paths |= {p.rel for p in posts + projects + papers}
        paths |= {f"/writing/tag/{t}/" for t in tags}
        langs[code] = Lang(
            code=code, prefix=prefix, cfg=cfg, ui=cfg.get("ui", {}),
            tag_labels=cfg.get("tag_labels", {}), status_labels=cfg.get("status_labels", {}),
            posts=posts, projects=projects, papers=papers, about=about,
            tags=tags, labels=labels, paths=paths,
        )
    return langs


# --------------------------------------------------------------------------- #
# decoration
# --------------------------------------------------------------------------- #

ICON = {
    "arrow": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
    "github": '<svg viewBox="0 0 16 16" class="i-fill" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/></svg>',
    "rss": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 11a9 9 0 0 1 9 9M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1.6"/></svg>',
    "mail": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>',
    "search": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m16.5 16.5 4.5 4.5"/></svg>',
    "sun": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M19.1 4.9l-1.8 1.8M6.7 17.3l-1.8 1.8"/></svg>',
    "moon": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z"/></svg>',
    "pen": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20l4.5-1L20 7.5a2.1 2.1 0 0 0-3-3L5.5 16 4 20Z"/><path d="M14.5 6.5l3 3"/></svg>',
    "gear": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3.2"/><path d="M12 2.6v3M12 18.4v3M2.6 12h3M18.4 12h3M5.2 5.2l2.1 2.1M16.7 16.7l2.1 2.1M18.8 5.2l-2.1 2.1M7.3 16.7l-2.1 2.1"/></svg>',
    "scroll": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4h11a2 2 0 0 1 2 2v12a2 2 0 0 0 2 2H8a2 2 0 0 1-2-2V4Z"/><path d="M6 4a2 2 0 0 0-2 2v1h2M9 9h7M9 13h7M9 17h4"/></svg>',
    "copy": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/></svg>',
    "sigil": '<svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="12.4"/><circle cx="16" cy="16" r="5.4"/><path d="M16 1.6v4.2M16 26.2v4.2M1.6 16h4.2M26.2 16h4.2M5.6 5.6l3 3M23.4 23.4l3 3M26.4 5.6l-3 3M8.6 23.4l-3 3"/><path d="M16 10.6l1.6 3.8 3.8 1.6-3.8 1.6-1.6 3.8-1.6-3.8-3.8-1.6 3.8-1.6Z" class="i-fill"/></svg>',
}

NAV = [("writing", "/writing/"), ("projects", "/projects/"), ("papers", "/papers/"), ("about", "/about/")]

DOOR_ICONS = ("pen", "gear", "scroll")

MASCOT = """<svg class="mascot" viewBox="0 0 96 96" aria-hidden="true">
<ellipse cx="48" cy="88" rx="21" ry="3.6" fill="var(--ink)" opacity=".14"/>
<path d="M35 78v6M61 78v6" stroke="var(--ink)" stroke-width="3" stroke-linecap="round" opacity=".65"/>
<rect x="57" y="15" width="12" height="19" rx="4" fill="var(--ink-2)" stroke="var(--ink)" stroke-width="2.4"/>
<circle class="mascot-puff" cx="63" cy="9" r="4.4" fill="var(--ink)" opacity=".2"/>
<rect x="22" y="30" width="52" height="48" rx="14" fill="var(--brass)" stroke="var(--ink)" stroke-width="2.6"/>
<rect x="30" y="38" width="36" height="21" rx="8" fill="var(--bg)" stroke="var(--ink)" stroke-width="2.2"/>
<circle class="mascot-eye" cx="48" cy="48.5" r="5.2" fill="var(--accent)"/>
<circle cx="50" cy="46.5" r="1.5" fill="var(--bg)" opacity=".85"/>
<circle cx="30.5" cy="71.5" r="2" fill="var(--ink)" opacity=".45"/>
<circle cx="65.5" cy="71.5" r="2" fill="var(--ink)" opacity=".45"/>
<path d="M39 64.5h18" stroke="var(--ink)" stroke-width="2.4" stroke-linecap="round" opacity=".5"/>
</svg>"""


def magic_circle() -> str:
    """Concentric workshop sigil, drawn once at build time."""
    cx = cy = 200.0
    ticks = []
    for i in range(24):
        angle = math.radians(i * 15)
        long = i % 3 == 0
        r1 = 168
        r2 = 186 if long else 177
        x1, y1 = cx + r1 * math.cos(angle), cy + r1 * math.sin(angle)
        x2, y2 = cx + r2 * math.cos(angle), cy + r2 * math.sin(angle)
        ticks.append(f'<path d="M{x1:.1f} {y1:.1f}L{x2:.1f} {y2:.1f}"/>')
    runes = []
    for i in range(8):
        angle = math.radians(i * 45 + 22.5)
        r = 142
        x, y = cx + r * math.cos(angle), cy + r * math.sin(angle)
        runes.append(
            f'<path d="M{x - 5:.1f} {y:.1f}l5-7 5 7z" fill="currentColor" opacity=".55"/>'
        )
    spokes = []
    for i in range(12):
        angle = math.radians(i * 30)
        x, y = cx + 92 * math.cos(angle), cy + 92 * math.sin(angle)
        spokes.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3"/>')
    return f"""<svg class="sigil-circle" viewBox="0 0 400 400" aria-hidden="true">
<circle cx="200" cy="200" r="196"/>
<circle cx="200" cy="200" r="186" stroke-dasharray="2 9"/>
<circle cx="200" cy="200" r="168"/>
<g class="sigil-ticks">{"".join(ticks)}</g>
<circle cx="200" cy="200" r="142" stroke-dasharray="1 6"/>
<g class="sigil-runes">{"".join(runes)}</g>
<circle cx="200" cy="200" r="96"/>
<circle cx="200" cy="200" r="58"/>
<g class="sigil-spokes">{"".join(spokes)}</g>
<path d="M200 116l20 34-20 34-20-34Z"/>
<path d="M200 200l14 24-14 24-14-24Z" opacity=".65"/>
</svg>"""


def gauge(value: float, label: str) -> str:
    value = max(0.0, min(1.0, value))
    angle = -70 + 140 * value
    tag = f'<span class="gauge-tag">{esc(label)}</span>' if label else ""
    return f"""<div class="gauge" aria-hidden="true" style="--needle:{angle:.1f}deg">
  <span class="gauge-track"></span><span class="gauge-face"></span>
  <span class="gauge-needle"></span><span class="gauge-hub"></span>{tag}
</div>"""


def lang_switch(L: "Lang", rel: str) -> str:
    opts = []
    for code, other in LANGS.items():
        active = code == L.code
        target = other.href(rel if rel in other.paths else "/")
        short = "EN" if code == "en" else "中"
        aria = ' aria-current="true"' if active else ""
        opts.append(
            f'<a class="lang-opt{" is-active" if active else ""}" href="{target}"'
            f' hreflang="{esc(other.locale)}" lang="{code}"{aria}>{short}</a>'
        )
    return (f'<div class="lang-switch" role="group" aria-label="{esc(L.t("lang_switch"))}">'
            f'{"".join(opts)}</div>')


def nav_html(L: "Lang", rel: str) -> str:
    items = []
    for key, href in NAV:
        cur = ' aria-current="page"' if rel.startswith(href) else ""
        items.append(f'<a class="nav-link" href="{L.href(href)}"{cur}>{esc(L.t("nav_" + key))}</a>')
    return f'<nav class="nav" aria-label="{esc(L.t("nav_label"))}">{"".join(items)}</nav>'


# --------------------------------------------------------------------------- #
# layout
# --------------------------------------------------------------------------- #


def page(L: "Lang", *, title: str, description: str, rel: str, content: str,
         body_class: str = "", math: bool = False, head: str = "",
         alternates: bool = True) -> str:
    site_title = str(L.cfg["title"])
    full_title = esc(site_title) if not title else f"{esc(title)} · {esc(site_title)}"
    canonical = CFG["url"].rstrip("/") + L.href(rel)
    og_type = "article" if body_class == "page-article" else "website"
    katex_css = '<link rel="stylesheet" href="/theme/katex/katex.min.css">' if math else ""
    katex_js = ('<script src="/theme/katex/katex.min.js" defer></script>\n'
                '<script src="/theme/katex/auto-render.min.js" defer></script>\n' if math else "")
    year_now = dt.date.today().year
    start = int(CFG.get("start_year", year_now))
    years = str(year_now) if start >= year_now else f"{start}–{year_now}"
    sha = "" if BUILD_ID in ("dev", "local", "") else f" · {BUILD_ID}"

    alt = ""
    if alternates:
        for other in LANGS.values():
            target = other.href(rel if rel in other.paths else "/")
            alt += f'<link rel="alternate" hreflang="{esc(other.locale)}" href="{esc(CFG["url"].rstrip("/") + target)}">\n'
        default = LANGS[str(CFG.get("default_lang", "en"))]
        target = default.href(rel if rel in default.paths else "/")
        alt += f'<link rel="alternate" hreflang="x-default" href="{esc(CFG["url"].rstrip("/") + target)}">\n'

    gh = f"https://github.com/{CFG['github']}"
    ld = {
        "@context": "https://schema.org",
        "@type": "WebSite" if rel == "/" else "WebPage",
        "name": site_title,
        "url": CFG["url"],
        "description": str(L.cfg.get("description", "")),
        "inLanguage": L.locale,
        "publisher": {"@type": "Person", "name": CFG["author"], "url": gh},
    }
    return f"""<!doctype html>
<html lang="{esc(L.locale)}" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{full_title}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{esc(canonical)}">
{alt}<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#f3e9d7">
<meta property="og:type" content="{og_type}">
<meta property="og:title" content="{full_title}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(canonical)}">
<meta property="og:site_name" content="{esc(site_title)}">
<meta property="og:locale" content="{esc(L.locale.replace('-', '_'))}">
<meta property="og:image" content="{esc(CFG['url'])}/og.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="alternate" type="application/rss+xml" title="{esc(site_title)}" href="{esc(L.href('/feed.xml'))}">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
{katex_css}
<link rel="stylesheet" href="/theme/css/site.css?v={BUILD_ID}">
<script>try{{var q=new URLSearchParams(location.search).get("theme");var t=q||localStorage.getItem("theme");if(t){{document.documentElement.dataset.theme=t}}else if(matchMedia("(prefers-color-scheme: dark)").matches){{document.documentElement.dataset.theme="dark"}}}}catch(e){{}}</script>
<script type="application/ld+json">{json.dumps(ld)}</script>
{head}
</head>
<body class="{body_class}">
<a class="skip" href="#main">{esc(L.t('skip'))}</a>
<header class="site-head">
  <div class="shell head-inner">
    <a class="brand" href="{L.href('/')}" aria-label="{esc(site_title)}">
      <span class="brand-sigil">{ICON['sigil']}</span>
      <span class="brand-text">
        <span class="brand-name">{esc(site_title)}</span>
        <span class="brand-sub">{esc(L.cfg.get('tagline', ''))}</span>
      </span>
    </a>
    {nav_html(L, rel)}
    <div class="head-tools">
      {lang_switch(L, rel)}
      <button class="icon-btn" type="button" data-search-open aria-label="{esc(L.t('search_button'))}" title="{esc(L.t('search_button'))}">
        {ICON['search']}<kbd>/</kbd>
      </button>
      <button class="icon-btn" type="button" data-theme-toggle aria-label="{esc(L.t('theme_toggle'))}" title="{esc(L.t('theme_toggle'))}">
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
  <div class="shell foot-plate">
    <div class="foot-brand">
      <span class="brand-sigil">{ICON['sigil']}</span>
      <div>
        <p class="foot-name">{esc(site_title)}</p>
        <p class="foot-tag">{esc(L.cfg.get('tagline', ''))}</p>
      </div>
    </div>
    <p class="foot-note">{esc(L.t('footer_note', prose=CFG['license_prose'], code=CFG['license_code']))}</p>
    <p class="foot-stamp">EST. {esc(CFG.get('start_year', ''))}</p>
  </div>
  <div class="shell foot-grid">
    <div>
      <h2 class="foot-h">{esc(L.t('footer_rooms'))}</h2>
      <ul>
        {''.join(f'<li><a href="{L.href(href)}">{esc(L.t("nav_" + key))}</a></li>' for key, href in NAV)}
        <li><a href="{esc(L.href('/feed.xml'))}">{esc(L.t('contact_rss'))}</a></li>
      </ul>
    </div>
    <div>
      <h2 class="foot-h">{esc(L.t('footer_elsewhere'))}</h2>
      <ul>
        <li><a href="{gh}" target="_blank" rel="noopener">{ICON['github']}{esc(L.t('contact_github'))}</a></li>
        {f'<li><a href="mailto:{CFG["email"]}">{ICON["mail"]}{esc(L.t("contact_email"))}</a></li>' if CFG.get('email') else ''}
        <li><a href="{gh}/{CFG['github']}.github.io">{esc(L.t('footer_source'))}</a></li>
      </ul>
    </div>
  </div>
  <div class="shell foot-base">
    <span>{esc(L.t('footer_copyright', years=years, author=CFG['author']))}</span>
    <span>{esc(L.t('footer_built', date=dt.date.today().isoformat()))}{sha} · {esc(L.t('footer_plain'))}</span>
  </div>
</footer>
<div class="search" id="search" hidden>
  <div class="search-panel" role="dialog" aria-modal="true" aria-labelledby="search-label">
    <div class="search-bar">
      <span class="search-icon">{ICON['search']}</span>
      <label class="visually-hidden" id="search-label" for="search-input">{esc(L.t('search_label'))}</label>
      <input id="search-input" type="search" placeholder="{esc(L.t('search_placeholder'))}" autocomplete="off" spellcheck="false">
      <kbd class="search-esc">{esc(L.t('search_esc'))}</kbd>
    </div>
    <div class="search-results" id="search-results" data-empty="{esc(L.t('search_empty'))}" data-miss="{esc(L.t('search_miss'))}"></div>
    <div class="search-foot"><span>{esc(L.t('search_move'))}</span><span>{esc(L.t('search_enter'))}</span><span>{esc(L.t('search_count', n=len(L.posts) + len(L.projects) + len(L.papers)))}</span></div>
  </div>
</div>
{katex_js}<script src="/theme/js/site.js?v={BUILD_ID}" defer></script>
</body>
</html>
"""


def section_head(L: "Lang", title: str, note: str = "", href: str = "", label: str = "") -> str:
    link = (f'<a class="sec-link" href="{href}">{esc(label)}<span aria-hidden="true">→</span></a>'
            if href else "")
    note_html = f'<span class="sec-note">{esc(note)}</span>' if note else ""
    return f"""<div class="sec-head">
  <h2 class="sec-title"><span class="sec-glyph" aria-hidden="true">{ICON['gear']}</span>{esc(title)}</h2>
  {note_html}
  {link}
</div>"""


def tag_list(L: "Lang", tags: list[str]) -> str:
    return "".join(
        f'<a class="tag" href="{L.href(f"/writing/tag/{slugify(t)}/")}">#{esc(L.label(t))}</a>'
        for t in tags
    )


def tag_spans(L: "Lang", tags: list[str]) -> str:
    """Tags inside a row that is itself a link: plain text, never nested links."""
    return "".join(f'<span class="tag">#{esc(L.label(t))}</span>' for t in tags)


def entry_rows(L: "Lang", posts: list[Doc], limit: int = 0) -> str:
    items = posts[:limit] if limit else posts
    if not items:
        return empty_state(
            L.t("posts_empty_kicker"),
            L.t("posts_empty_text"),
            L.href("/feed.xml"), L.t("posts_empty_link"),
        )
    rows = []
    for post in items:
        stamp = fmt_date(post.date, L.code, "stamp")
        iso = post.date.isoformat() if post.date else ""
        rows.append(f"""<li class="entry">
    <a class="entry-link" href="{post.url}">
      <span class="entry-date"><time datetime="{iso}">{stamp}</time></span>
      <span class="entry-main">
        <span class="entry-title">{esc(post.title)}</span>
        <span class="entry-tags">{tag_spans(L, post.tags[:3])}</span>
      </span>
      <span class="entry-read">{esc(L.t('reading_time', n=post.minutes))}</span>
      <span class="entry-go" aria-hidden="true">→</span>
    </a>
  </li>""")
    return f'<ol class="entries">{"".join(rows)}</ol>'


def work_cards(L: "Lang", projects: list[Doc]) -> str:
    if not projects:
        return empty_state(
            L.t("work_empty_kicker"),
            L.t("work_empty_text"),
            f"https://github.com/{CFG['github']}", L.t("work_empty_link"),
        )
    cards = []
    for i, p in enumerate(projects, start=1):
        chip = p.meta.get("status", "active")
        cards.append(f"""<a class="card" href="{p.url}">
    <span class="card-top"><span class="card-id">No. {i:02d}</span><span class="chip chip--{esc(str(chip))}">{esc(L.status(chip))}</span></span>
    <h3 class="card-title">{esc(p.title)}</h3>
    <p class="card-sum">{esc(p.summary)}</p>
    <span class="card-foot">{''.join(f'<span class="tag">{esc(L.label(t))}</span>' for t in p.tags[:3])}</span>
  </a>""")
    return f'<div class="work-grid">{"".join(cards)}</div>'


def empty_state(kicker: str, text: str, href: str, label: str) -> str:
    return f"""<div class="empty">
  <p class="empty-kicker">{esc(kicker)}</p>
  <p class="empty-text">{esc(text)}</p>
  <a class="btn btn--ghost" href="{esc(href)}">{esc(label)}{ICON['arrow']}</a>
</div>"""


def paper_row(L: "Lang", paper: Doc, index: int) -> str:
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
  <span class="chip chip--{esc(str(status))}">{esc(L.status(status))}</span>
</li>"""


# --------------------------------------------------------------------------- #
# pages
# --------------------------------------------------------------------------- #


def build_home(L: "Lang") -> str:
    hero = L.cfg["hero"]
    lines = [ln.strip() for ln in str(hero["headline"]).split("|")]
    headline = "<br>".join(
        re.sub(r"\*(.+?)\*", r"<em>\1</em>", esc(ln)) for ln in lines
    )
    doors = "".join(
        f"""<a class="door" href="{esc(L.href(str(s.get('href', '/'))))}">
      <span class="door-kicker">{esc(s.get('note', ''))}</span>
      <span class="door-glyph" aria-hidden="true">{ICON[DOOR_ICONS[i % 3]]}</span>
      <h3 class="door-title">{esc(s['title'])}<span class="door-arrow" aria-hidden="true">→</span></h3>
      <p class="door-body">{esc(s.get('body', ''))}</p>
    </a>"""
        for i, s in enumerate(L.cfg.get("sections", []))
    )
    gh = f"https://github.com/{CFG['github']}"

    latest = L.posts[0] if L.posts else None
    count = len(L.posts)
    if latest:
        latest_html = f"""<a class="console-entry" href="{latest.url}">
      <span class="console-title">{esc(latest.title)}</span>
      <span class="console-sum">{esc(latest.summary)}</span>
      <span class="console-meta">{esc(fmt_date(latest.date, L.code, 'stamp'))} · {esc(L.t('reading_time', n=latest.minutes))}</span>
    </a>"""
        filed = fmt_date(latest.date, L.code, "stamp")
        needle = min(1.0, count / 12)
    else:
        latest_html = f'<p class="console-empty">{esc(L.t("console_empty"))}</p>'
        filed = "·"
        needle = 0.0

    console = f"""<aside class="console" aria-label="{esc(L.t('latest'))}">
    {f'<span class="console-stamp" aria-hidden="true">{esc(L.cfg["stamp"])}</span>' if L.cfg.get('stamp') else ''}
    <div class="console-head">
      <span class="plate-label">{esc(L.t('console_label'))}</span>
      <span class="console-no">No. {count:02d}</span>
    </div>
    {latest_html}
    <dl class="readouts">
      <div><dt>{esc(L.t('console_entries'))}</dt><dd>{count:02d}</dd></div>
      <div><dt>{esc(L.t('console_filed'))}</dt><dd>{esc(filed)}</dd></div>
      <div><dt>{esc(L.t('console_read'))}</dt><dd>{latest.minutes if latest else 0}</dd></div>
    </dl>
    <div class="console-foot">
      {gauge(needle, '')}
      <a class="console-rss" href="{esc(L.href('/feed.xml'))}">{ICON['rss']}<span>{esc(L.t('subscribe'))}</span></a>
    </div>
    <span class="console-mascot">{MASCOT}</span>
  </aside>"""

    notice = L.cfg.get("notice") or {}
    notice_html = ""
    if notice.get("text") and notice.get("enabled", True) is not False:
        link = ""
        if notice.get("link_label"):
            href = L.href(str(notice.get("link_href", "/about/")))
            link = (f'<a class="note-link" href="{esc(href)}">'
                    f'{esc(notice["link_label"])}<span aria-hidden="true">→</span></a>')
        notice_html = f"""<section class="notice" aria-label="{esc(notice.get('label', ''))}">
  <div class="shell">
    <div class="note">
      <span class="note-pin" aria-hidden="true"></span>
      <span class="note-mascot" aria-hidden="true">{MASCOT}</span>
      <p class="note-label">{esc(notice.get('label', ''))}</p>
      <p class="note-text">{esc(notice['text'])} {link}</p>
    </div>
  </div>
</section>
"""

    content = f"""<section class="hero">
  <div class="hero-grid-bg" aria-hidden="true"></div>
  <div class="hero-sigil" aria-hidden="true">{magic_circle()}</div>
  <div class="shell hero-grid">
    <div class="hero-main">
      <p class="eyebrow"><span class="spark" aria-hidden="true"></span>{esc(hero['eyebrow'])}</p>
      <h1 class="hero-title">{headline}</h1>
      <p class="hero-lede">{esc(hero['lede'])}</p>
      <div class="hero-actions">
        <a class="btn btn--primary" href="{esc(L.href(str(hero['primary_href'])))}">{esc(hero['primary_label'])}{ICON['arrow']}</a>
        <a class="btn btn--ghost" href="{gh}" target="_blank" rel="noopener">{ICON['github']}{esc(hero['secondary_label'])}</a>
      </div>
    </div>
    {console}
  </div>
</section>

{notice_html}<section class="shell band band--doors">
  {section_head(L, L.t('home_areas'), L.t('home_areas_note'))}
  <div class="door-grid">{doors}</div>
</section>

<section class="shell band">
  {section_head(L, L.t('home_log'), href=L.href('/writing/'), label=L.t('all_writing'))}
  {entry_rows(L, L.posts, 5)}
</section>
"""
    if L.projects:
        content += f"""<section class="shell band">
  {section_head(L, L.t('home_shop'), href=L.href('/projects/'), label=L.t('all_projects'))}
  {work_cards(L, L.projects[:4])}
</section>
"""
    if L.papers:
        items = "".join(paper_row(L, p, i) for i, p in enumerate(L.papers[:3], start=1))
        content += f"""<section class="shell band">
  {section_head(L, L.t('home_papers'), href=L.href('/papers/'), label=L.t('all_papers'))}
  <ol class="papers">{items}</ol>
</section>
"""
    return page(L, title="", description=str(L.cfg["description"]), rel="/",
                content=content, body_class="page-home")


def build_listing(L: "Lang", active_tag: str = "", tag_label: str = "") -> str:
    if active_tag:
        items = L.tags.get(active_tag, [])
        heading = f'<h1 class="page-title">{esc(L.t("tag_title", tag=tag_label or active_tag))}</h1>'
        sub = f'<p class="page-lede">{esc(L.t("tag_lede", n=len(items)))} <a href="{L.href("/writing/")}">{esc(L.t("tag_back"))}</a></p>'
        rel = f"/writing/tag/{active_tag}/"
    else:
        heading = f'<h1 class="page-title">{esc(L.t("writing_title"))}</h1>'
        sub = f'<p class="page-lede">{esc(L.t("writing_lede"))}</p>'
        rel = "/writing/"
        items = L.posts
    tag_cloud = "".join(
        f'<a class="tag-pill{" is-active" if t == active_tag else ""}" href="{L.href(f"/writing/tag/{t}/")}">'
        f'{esc(label)}<span>{len(L.tags[t])}</span></a>'
        for t, label in sorted(L.labels.items(), key=lambda kv: kv[1].lower())
    ) if L.tags else ""
    cloud = f'<div class="tag-cloud"><span class="tag-cloud-label">{esc(L.t("tag_cloud"))}</span>{tag_cloud}</div>' if tag_cloud else ""
    content = f"""<section class="shell page-head">
  <p class="kicker">{esc(L.t('list_kicker'))}</p>
  {heading}
  {sub}
  {cloud}
</section>
<section class="shell band">
  {entry_rows(L, items)}
</section>"""
    return page(L, title=L.t("tag_title", tag=tag_label or active_tag) if active_tag else L.t("writing_title"),
                description=str(L.cfg["description"]), rel=rel, content=content,
                body_class="page-listing")


def build_post(L: "Lang", post: Doc, prev: Doc | None, nxt: Doc | None, index: int) -> str:
    tags = "".join(f'<a class="tag" href="{L.href(f"/writing/tag/{quote(slugify(t))}/")}">#{esc(L.label(t))}</a>' for t in post.tags)
    share = CFG["url"].rstrip("/") + post.url
    nav = []
    if prev:
        nav.append(f'<a class="art-nav-item" href="{prev.url}"><span>{esc(L.t("newer"))}</span>{esc(prev.title)}</a>')
    if nxt:
        nav.append(f'<a class="art-nav-item art-nav-item--next" href="{nxt.url}"><span>{esc(L.t("older"))}</span>{esc(nxt.title)}</a>')
    toc = (f'<nav class="toc" aria-label="{esc(L.t("contents"))}">'
           f'<p class="toc-h">{esc(L.t("contents"))}</p>{post.toc}</nav>') if post.toc else ""
    citation = f"“{post.title}.” {L.cfg['title']}, {post.date.isoformat() if post.date else ''}. {share}"
    content = f"""<article class="article">
  <div class="shell">
    <header class="art-head">
      <p class="kicker"><a href="{L.href('/writing/')}">{esc(L.t('writing_title'))}</a> <span aria-hidden="true">/</span> {esc(L.t('cite_prefix'))} {index:02d}</p>
      <span class="art-sigil" aria-hidden="true">{magic_circle()}</span>
      <h1 class="art-title">{esc(post.title)}</h1>
      {f'<p class="art-lede">{esc(post.summary)}</p>' if post.summary else ''}
      <dl class="art-meta">
        <div><dt>{esc(L.t('filed'))}</dt><dd>{esc(fmt_date(post.date, L.code, 'long'))}</dd></div>
        <div><dt>{esc(L.t('read'))}</dt><dd>{esc(L.t('reading_time', n=post.minutes))}</dd></div>
        <div><dt>{esc(L.t('tag_cloud'))}</dt><dd class="art-tags">{tags or '·'}</dd></div>
      </dl>
    </header>
    <div class="art-grid">
      <aside class="art-rail">{toc}</aside>
      <div class="prose" data-prose>{post.body}</div>
    </div>
    <footer class="art-foot">
      <div class="art-cite">
        <p class="kicker">{esc(L.t('cite'))}</p>
        <code>{esc(citation)}</code>
      </div>
      <nav class="art-nav" aria-label="{esc(L.t('all_writing'))}">{''.join(nav)}</nav>
    </footer>
  </div>
</article>"""
    head = f"""<meta property="article:published_time" content="{post.date.isoformat() if post.date else ''}">
<script type="application/ld+json">{json.dumps({
        "@context": "https://schema.org", "@type": "BlogPosting",
        "headline": post.title, "datePublished": post.date.isoformat() if post.date else "",
        "inLanguage": L.locale,
        "author": {"@type": "Person", "name": CFG["author"]},
        "description": post.summary, "url": CFG["url"].rstrip("/") + post.url})}</script>"""
    return page(L, title=post.title, description=post.summary or str(L.cfg["description"]),
                rel=post.rel, content=content, body_class="page-article", head=head,
                math='class="math' in post.body)


def build_projects(L: "Lang") -> str:
    content = f"""<section class="shell page-head">
  <p class="kicker">{esc(L.t('projects_kicker'))}</p>
  <h1 class="page-title">{esc(L.t('projects_title'))}</h1>
  <p class="page-lede">{esc(L.t('projects_lede'))}</p>
</section>
<section class="shell band">{work_cards(L, L.projects)}</section>"""
    return page(L, title=L.t("projects_title"), description=L.t("projects_lede"),
                rel="/projects/", content=content, body_class="page-listing")


def build_project(L: "Lang", project: Doc) -> str:
    repo = project.meta.get("repo")
    repo_html = ""
    if repo:
        repo_html = f'<a class="btn btn--ghost" href="{esc(repo)}" target="_blank" rel="noopener">{ICON["github"]}Repository</a>'
    content = f"""<article class="article article--project">
  <div class="shell">
    <header class="art-head">
      <p class="kicker"><a href="{L.href('/projects/')}">{esc(L.t('projects_title'))}</a> <span aria-hidden="true">/</span> {esc(project.year)}</p>
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
    return page(L, title=project.title, description=project.summary,
                rel=project.rel, content=content, body_class="page-article",
                math='class="math' in project.body)


def build_papers(L: "Lang") -> str:
    if L.papers:
        body = f'<ol class="papers">{"".join(paper_row(L, p, i) for i, p in enumerate(L.papers, 1))}</ol>'
    else:
        body = empty_state(
            L.t("papers_empty_kicker"),
            L.t("papers_empty_text"),
            f"https://github.com/{CFG['github']}", L.t("papers_empty_link"),
        )
    content = f"""<section class="shell page-head">
  <p class="kicker">{esc(L.t('papers_kicker'))}</p>
  <h1 class="page-title">{esc(L.t('papers_title'))}</h1>
  <p class="page-lede">{esc(L.t('papers_lede'))}</p>
</section>
<section class="shell band">{body}</section>"""
    return page(L, title=L.t("papers_title"), description=L.t("papers_lede"),
                rel="/papers/", content=content, body_class="page-listing")


def build_about(L: "Lang") -> str:
    body = L.about.body if L.about else "<p>About page coming soon.</p>"
    gh = f"https://github.com/{CFG['github']}"
    contact = [(gh, L.t("contact_github"), ICON["github"]),
               (L.href("/feed.xml"), L.t("contact_rss"), ICON["rss"])]
    if CFG.get("email"):
        contact.insert(0, (f"mailto:{CFG['email']}", L.t("contact_email"), ICON["mail"]))
    contact_html = "".join(
        f'<a class="contact" href="{esc(href)}">{icon}<span>{esc(label)}</span></a>'
        for href, label, icon in contact
    )
    content = f"""<section class="shell page-head">
  <p class="kicker">{esc(L.t('about_kicker'))}</p>
  <h1 class="page-title">{esc(L.t('about_title'))}</h1>
</section>
<section class="shell band">
  <div class="about-grid">
    <div class="prose postcard" data-prose>{body}</div>
    <aside class="about-side">
      <div class="rail-plate">
        <p class="kicker">{esc(L.t('about_elsewhere'))}</p>
        <div class="contact-list">{contact_html}</div>
        <p class="kicker kicker--spaced">{esc(L.t('about_license'))}</p>
        <p class="about-note">{esc(L.t('about_license_note', prose=CFG['license_prose'], code=CFG['license_code']))}</p>
      </div>
    </aside>
  </div>
</section>"""
    return page(L, title=L.t("about_title"), description=str(L.cfg["description"]), rel="/about/",
                content=content, body_class="page-about",
                math=bool(L.about and 'class="math' in L.about.body))


def build_search(L: "Lang") -> str:
    content = f"""<section class="shell page-head">
  <p class="kicker">{esc(L.t('search_kicker'))}</p>
  <h1 class="page-title">{esc(L.t('search_title'))}</h1>
  <p class="page-lede">{esc(L.t('search_lede'))}</p>
</section>
<section class="shell band">
  <div class="search-inline">
    <div class="search-bar"><span class="search-icon">{ICON['search']}</span>
      <label class="visually-hidden" for="page-search-input">{esc(L.t('search_button'))}</label>
      <input id="page-search-input" type="search" placeholder="{esc(L.t('search_placeholder'))}" autocomplete="off">
    </div>
    <div class="search-results" id="page-search-results" data-empty="{esc(L.t('search_empty'))}" data-miss="{esc(L.t('search_miss'))}"></div>
  </div>
</section>"""
    return page(L, title=L.t("search_title"), description=L.t("search_lede"),
                rel="/search/", content=content, body_class="page-listing")


def build_404() -> str:
    en = LANGS[str(CFG.get("default_lang", "en"))]
    zh = LANGS.get("zh", en)
    content = f"""<section class="shell page-head page-head--404">
  <p class="kicker">404</p>
  <div class="lost">
    <div class="lost-mascot" aria-hidden="true">{MASCOT}</div>
    <div class="lost-copy">
      <h1 class="page-title">{esc(en.t('not_found_title'))}</h1>
      <p class="page-lede">{esc(en.t('not_found_lede'))}</p>
      <p class="lost-zh" lang="{esc(zh.locale)}">{esc(zh.t('not_found_title'))} {esc(zh.t('not_found_lede'))}</p>
      <div class="hero-actions">
        <a class="btn btn--primary" href="{en.href('/')}">{esc(en.t('not_found_button'))}{ICON['arrow']}</a>
        <a class="btn btn--ghost" href="{zh.href('/')}">{esc(zh.t('not_found_button'))}</a>
      </div>
    </div>
  </div>
</section>"""
    return page(en, title=en.t("not_found_kicker"), description=en.t("not_found_lede"),
                rel="/404.html", content=content, body_class="page-404", alternates=False)


# --------------------------------------------------------------------------- #
# feeds, sitemap, assets
# --------------------------------------------------------------------------- #


def build_feed(L: "Lang") -> str:
    posts = L.posts
    updated = posts[0].date if posts and posts[0].date else dt.date.today()
    items = []
    for post in posts[:20]:
        date = (post.date or dt.date.today()).isoformat()
        items.append(f"""<item>
  <title>{esc(post.title)}</title>
  <link>{CFG['url'].rstrip('/') + post.url}</link>
  <guid isPermaLink="true">{CFG['url'].rstrip('/') + post.url}</guid>
  <pubDate>{dt.datetime.fromisoformat(date).strftime('%a, %d %b %Y 00:00:00 +0000')}</pubDate>
  <description>{esc(post.summary)}</description>
  <content:encoded><![CDATA[{post.body}]]></content:encoded>
</item>""")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
<title>{esc(L.cfg['title'])}</title>
<link>{CFG['url'].rstrip('/') + L.href('/')}</link>
<description>{esc(L.cfg['description'])}</description>
<language>{esc(L.locale)}</language>
<lastBuildDate>{dt.datetime.combine(updated, dt.time()).strftime('%a, %d %b %Y 00:00:00 +0000')}</lastBuildDate>
<atom:link href="{CFG['url'].rstrip('/') + L.href('/feed.xml')}" rel="self" type="application/rss+xml"/>
{''.join(items)}
</channel>
</rss>
"""


def build_sitemap(urls: list[tuple[str, str]]) -> str:
    entries = "".join(
        f"<url><loc>{esc(CFG['url'].rstrip('/') + path)}</loc><lastmod>{date}</lastmod></url>"
        for path, date in urls
    )
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{entries}</urlset>\n")


FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="14" fill="#14110d"/>
<g fill="none" stroke="#d9a85c" stroke-width="2.4">
<circle cx="32" cy="32" r="18"/><circle cx="32" cy="32" r="7"/>
<path d="M32 6v6M32 52v6M6 32h6M52 32h6M13.6 13.6l4.2 4.2M46.2 46.2l4.2 4.2M50.4 13.6l-4.2 4.2M17.8 46.2l-4.2 4.2"/></g>
<path d="M32 22l3.4 6.6L42 32l-6.6 3.4L32 42l-3.4-6.6L22 32l6.6-3.4Z" fill="#6bd8ca"/></svg>
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
CFG: dict = {}
LANGS: dict[str, Lang] = {}


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
    global BUILD_ID, CFG, LANGS
    CFG = tomllib.loads(read_text(ROOT / "site.toml"))
    BUILD_ID = git_id()
    LANGS = build_langs()

    if clean:
        reset_out()
    else:
        # dev mode: the preview server may hold file handles, so never delete the tree
        OUT.mkdir(parents=True, exist_ok=True)
        for stale in OUT.rglob("*.html"):
            stale.unlink(missing_ok=True)

    def write(rel: str, text: str) -> None:
        target = OUT / rel.lstrip("/")
        if rel.endswith("/"):
            target = target / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    urls: list[tuple[str, str]] = []
    today = dt.date.today().isoformat()
    for L in LANGS.values():
        write(L.href("/"), build_home(L))
        write(L.href("/writing/"), build_listing(L))
        for tag in L.tags:
            write(L.href(f"/writing/tag/{tag}/"), build_listing(L, active_tag=tag, tag_label=L.labels.get(tag, tag)))
        for i, post in enumerate(L.posts):
            newer = L.posts[i - 1] if i > 0 else None
            older = L.posts[i + 1] if i + 1 < len(L.posts) else None
            write(post.url, build_post(L, post, newer, older, i + 1))
        write(L.href("/projects/"), build_projects(L))
        for project in L.projects:
            write(project.url, build_project(L, project))
        write(L.href("/papers/"), build_papers(L))
        write(L.href("/about/"), build_about(L))
        write(L.href("/search/"), build_search(L))
        write(L.href("/feed.xml"), build_feed(L))

        kind_key = {"post": "kind_post", "project": "kind_project", "paper": "kind_paper"}
        index = [
            {"t": d.title, "u": d.url, "k": L.t(kind_key[d.kind]), "s": d.summary,
             "g": [L.label(t) for t in d.tags], "d": d.date.isoformat() if d.date else ""}
            for d in L.posts + L.projects + L.papers
        ]
        write(L.href("/search-index.json"), json.dumps(index, ensure_ascii=False, indent=0))

        latest = (L.posts[0].date if L.posts and L.posts[0].date else dt.date.today()).isoformat()
        urls.append((L.href("/"), latest))
        urls.append((L.href("/writing/"), latest))
        urls.append((L.href("/projects/"), today))
        urls.append((L.href("/papers/"), today))
        urls.append((L.href("/about/"), today))
        urls += [(p.url, (p.date or dt.date.today()).isoformat()) for p in L.posts]
        urls += [(p.url, today) for p in L.projects]

    write("/404.html", build_404())
    write("/sitemap.xml", build_sitemap(urls))
    write("/.nojekyll", "")
    write("/favicon.svg", FAVICON)

    copy_assets()
    if verbose:
        total = sum(1 for _ in OUT.rglob("*") if _.is_file())
        counts = ", ".join(f"{L.code}: {len(L.posts)} posts" for L in LANGS.values())
        print(f"built {total} files -> public/  ({counts})")
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
            print(f"  {page_path} -> {href}")
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
    parser = argparse.ArgumentParser(description="Build the atelier notebook.")
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
