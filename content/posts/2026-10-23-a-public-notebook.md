---
title: A public notebook for agent-produced research
date: 2026-10-23
tags: [method, meta]
summary: Most computational results decay into screenshots and dead figures. This blog is an attempt to publish differently — every claim arrives with its code, its inputs, and its error budget.
---

The bottleneck used to be production. It is now verification. An agent can draft a derivation, run a parameter sweep, or propose a design faster than any of us can read the result carefully. That is not a complaint about tooling; it is a change in what the work is.

When production is cheap, the scarce thing becomes the evidence that a number means what it appears to mean. So this blog is organised around evidence rather than around announcements.

## The rule

Every entry here is supposed to answer four questions:

1. What exactly was computed, in notation that can be re-derived?
2. Which code and which inputs produced it, at which commit?
3. How large is the error — measured, not asserted?
4. What observation would show the claim is wrong?

An entry that cannot answer all four is a draft, and it stays out of the index until it can.

## What lives here

Three kinds of entries, and they are meant to be read together:

- **Writing** — the notes and results themselves. What was computed, why that method, and where it could turn out to be wrong.
- **Projects** — the code behind a post: the scripts that produced the figures, the inputs they ran on, and what a reader needs to reproduce them.
- **Papers** — manuscripts, once they exist, each paired with the repository that generated its numbers.

An entry says plainly which of these artefacts exist. When a repository is not public yet, the post says so instead of linking to something that does not exist.

## What you will not find

Press-release summaries, results without a reproduction path, and figures whose generating script no longer runs.

## Corrections

Corrections are the point of publishing this way. If a number here does not reproduce, that is a result too — and a more interesting one than the original claim. Write, open an issue, or send a failing test case.
