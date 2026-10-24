---
# Copy into content/en/projects/ (and optionally content/zh/projects/) and rename
# to <slug>.md. The filename is the URL:
#   content/en/projects/nfw-wave-optics.md  ->  /projects/nfw-wave-optics/
#
# Projects with `featured: true` also appear on the front page (up to four).

title: Project name
summary: One sentence on what it computes and why it exists.
date: 2026-01-01
status: active                   # active | queued | archived
featured: true
repo: ""                         # e.g. https://github.com/user/repo; leave empty if private
tags: [code, numerics]           # English slugs, same as posts
draft: false
---

What the code does, in the language of the problem rather than the language of
the repository. State the model and its assumptions, the numerical method, and
the validation strategy.

## Method

Describe the approach. Link to the corresponding post with a relative link when
one exists (use `/zh/writing/...` in the Chinese copy):

```markdown
See [the write-up](/writing/your-post/) for the derivation.
```

## Reproducing

```bash
python build.py --serve
```

State what a reader needs (data, compute, a particular solver) and what they
should expect to see at the end.
