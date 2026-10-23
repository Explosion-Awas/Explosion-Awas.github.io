---
# Copy this file into content/posts/ and rename it:
#   content/posts/YYYY-MM-DD-your-slug.md
# The date in the filename sets the publish date (front matter `date` wins if present).

title: Your post title
date: 2026-01-01
tags: [notes, method]            # lowercase, no spaces needed; used for /writing/tag/<tag>/
summary: >
  One or two sentences. This appears in listings, the RSS feed, and the page's
  meta description, so write it as a standalone sentence.
draft: false                     # true = not built, not listed
---

Opening paragraph. Prose is set in a serif face at a comfortable measure; short
paragraphs read best.

## A section

Inline math uses single dollars: the amplification factor $F(w)$ is complex.
Display math uses double dollars and gets its own block:

$$
F(w) = \frac{w}{2\pi i}\int d^2x\, e^{iw\left[\frac{1}{2}\lvert x-y\rvert^2 - \psi(x)\right]}
$$

Code fences are highlighted at build time:

```python
def converge(estimates, tol=1e-6):
    """Richardson-style check: halve the step until the change is below tol."""
    return abs(estimates[-1] - estimates[-2]) < tol
```

A table:

| Case | Method | Error |
| --- | --- | --- |
| $y = 0.25$ | hybrid | 3e-7 |
| $y = 10$ | numeric | 1e-9 |

An aside, as raw HTML (the Markdown inside it is still processed):

<div class="callout">
<p><strong>Note</strong>Callouts are for caveats, not for emphasis. The bold lead-in is styled as a label.</p>
</div>

A footnote works too.[^1]

[^1]: Footnotes are collected at the bottom of the post.

Images live in `content/assets/`; a title becomes a caption:

![Alt text describing the figure](/assets/example.png "Figure 1. A caption.")
