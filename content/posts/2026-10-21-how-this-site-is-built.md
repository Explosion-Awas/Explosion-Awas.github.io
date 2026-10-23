---
title: How this site is built
date: 2026-10-21
tags: [engineering, meta]
summary: A generator of about a thousand lines of Python, self-hosted fonts, and KaTeX only where it is needed. No framework, no CDN, no analytics.
---

This site is a folder of Markdown that a Python script turns into static HTML. There is no database, no client-side router, and no third-party request at runtime. That last constraint is deliberate: pages have to render the same way on a fast connection, behind a restrictive network, and ten years from now.

## The pipeline

Content lives in `content/`, the theme in `theme/`, and the build writes `public/`. Pushing to `main` runs the same build in GitHub Actions and deploys the result to Pages.

```bash
python build.py            # build into public/
python build.py --serve    # local preview, rebuilds on save
python build.py --check    # verify every internal link
```

The generator is a single file with two dependencies, `markdown` and `pygments`. Everything else is the standard library.

## Fonts and math are self-hosted

Third-party font and script CDNs are the most common reason a page renders differently for different readers. All of it ships in the repository instead: four `woff2` files for the text, and KaTeX for mathematics.

KaTeX is loaded only on pages that actually contain a formula. The build knows, because it sees the math before it writes the HTML.

<div class="callout">
<p><strong>Rendering check</strong>Display math has to survive the Markdown pipeline intact — subscripts, fractions, limits and all. The identity below is a standard one, used here only to prove that it does.</p>

$$
\int_{-\infty}^{\infty} e^{-a x^{2} + b x}\,dx \;=\; \sqrt{\frac{\pi}{a}}\; \exp\!\left(\frac{b^{2}}{4a}\right),
\qquad a > 0
$$

</div>

Inline math has to work too, including things like $e^{i\omega T}$ and $\varepsilon \in (0,\,1]$, without the underscores turning into emphasis. The build stashes math before Markdown sees it and restores it afterwards, which is also why inline code such as `w*y*y/2 >= 5` is safe.

## Code is highlighted at build time

No highlight.js, no shiki, no runtime cost:

```python
def reading_time(words: int, wpm: int = 210) -> int:
    """Minutes, rounded up, with a floor of one."""
    return max(1, round(words / wpm))
```

That is the actual function the generator uses. Pygments emits the token spans; the stylesheet maps them onto the same palette as the rest of the page, so light and dark themes stay in step.

## What a page costs

Measured from the files themselves, not estimated:

| Asset | Size | Loaded on |
| --- | --- | --- |
| HTML | ~12 KB | every page |
| Stylesheet | 38 KB | every page |
| Fonts (4 × woff2) | 162 KB | every page, cached |
| KaTeX CSS + JS | 294 KB | only pages with math |
| JavaScript | 10 KB | every page |

A prose page is therefore about 220 KB on first visit — fonts included — and nothing on a repeat visit. A page with math pays another 294 KB, most of it the typesetting engine, which the browser caches after the first formula it sees.

## Trade-offs

Static generation means no comments, no server-side search, and no way to publish from a phone without waiting for a build. The search index is a JSON file fetched on demand, and it is good enough for a notebook of this size. If the site ever outgrows it, that will be a different problem to solve.

The one thing this setup cannot do is decide whether a result is true. That part stays with the author and the reader.[^katex]

[^katex]: KaTeX is pinned at the version vendored into `theme/katex/`, so an upstream release cannot change how an old post renders.
