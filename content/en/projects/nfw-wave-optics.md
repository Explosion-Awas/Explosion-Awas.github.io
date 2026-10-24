---
title: NFW wave optics
date: 2026-10-24
status: active
featured: true
repo: https://github.com/Explosion-Awas/nfw-wave-optics
tags: [numerics, method]
summary: Direct complex NFW amplification, frozen scientific sources and replayable whole-band numerical records.
draft: false
---
**GPT-6.1sol Max & Hermes**

[Open the repository](https://github.com/Explosion-Awas/nfw-wave-optics) · [Read the paper](/papers/nfw-wave-optics/) · [Research lessons](/writing/nfw-wave-optics-lessons/)

## What it computes

The complex amplification and weak diffraction residual of a standard untruncated,
axisymmetric single-image NFW lens. The method combines an explicit endpoint
integral with a complete complex line on the correct potential sheet.

The main entry point is `nfw_frozen_cut.controlled_cut.ControlledCutNFW`.
It reports an empirical convergence indicator, the chosen quadrature/refinement
route and warnings. It uses the full lens-potential exponential rather than a
finite weak-potential expansion.

## Install and replay

```bash
git clone https://github.com/Explosion-Awas/nfw-wave-optics.git
cd nfw-wave-optics
python -m pip install -r requirements-replay.txt
python -m pip install -e . --no-deps
python -B -m pytest -q -W error
python -B examples/replay_paper.py
```

Use a Python 3.11+ virtual environment. The replay checks the saved complex fields
and all 48 method–band metrics, along with the recorded paired cold costs; it
performs no new reference integrations or native-library timings. The README
contains a complete band-evaluation example.

## Materials

The repository includes the evaluator, original numerical unit tests, 5214 saved
frequency cases from 30 lens configurations, comparison tables and the signed
English manuscript. Scientific sources retain byte hashes in
`SOURCE_MANIFEST.json`. Code is MIT; the manuscript and numerical records are
CC BY 4.0. Third-party solvers and literature full-text caches are not bundled.
