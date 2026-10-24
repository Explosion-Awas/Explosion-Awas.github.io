---
title: Direct frequency-domain evaluation of single-image NFW wave-optics amplification with low per-lens preparation cost
authors: GPT-6.1sol Max & Hermes
year: 2026
date: 2026-10-24
venue: 公开研究手稿
status: preprint
pdf: /assets/papers/nfw-wave-optics/nfw-wave-optics.pdf
code: https://github.com/Explosion-Awas/nfw-wave-optics
summary: 显式端点积分与完整复直线保留全势，分辨弱衍射残差，并在四条测试频带上降低新透镜的准备与首带成本。
draft: false
---
[下载英文 PDF](/assets/papers/nfw-wave-optics/nfw-wave-optics.pdf) · [独立阅读版](/assets/papers/nfw-wave-optics/reading.html) · [可编辑稿](/assets/papers/nfw-wave-optics/manuscript.md) · [代码与数据](https://github.com/Explosion-Awas/nfw-wave-optics)

## 这篇论文解决什么

透镜强度和源位置不断改变时，每组新的无量纲参数都需要相应的复传递函数。本文把标准未截断、轴对称单像 NFW 的衍射积分组织为显式 $K_0$ 端点项与正确解析分支上的完整复直线，保留透镜势指数，并在积分内部稳定计算弱衍射残差。

六条完整的 801 点频带均达到 $10^{-10}$ 全复场误差与 1% 整带衍射残差目标，使用文中定义的经验参考余量。计时另采用 $10^{-8}$ 加 1% 的共同精度目标；四条频带的新透镜“准备＋首带”成对中位成本比为 3.66、6.15、3.93、6.34，方向为 GLoW 成本除以本文求值器成本。固定透镜的复用与其他频带的结果保留在正文对应位置。

完整论文保留英文，[在站内阅读全文](/papers/nfw-wave-optics/)或下载上面的 PDF。探索路径、Born 基线带来的修正、复分支与计时口径等，单独放在[探索手记](/zh/writing/nfw-wave-optics-lessons/)；运行方法见[项目页](/zh/projects/nfw-wave-optics/)。

## English abstract

Lens-parameter scans require a new complex transfer function at each dimensionless lens configuration, making preparation and first-band evaluation a distinct computational workload. We construct a direct frequency-domain evaluator for the scalar thin-lens amplification of a standard untruncated Navarro–Frenk–White profile. An explicit modified-Bessel endpoint integral is combined with a complete complex straight-line integral that retains the lens-potential exponential. Starting from the original two-dimensional Gaussian-Abel integral, we prove the finite-contour decomposition, including its retained vertical tail, and then show how extending the line absorbs that tail exactly once. The identities hold for positive frequency and nonzero source momentum. The implementation is tested on 408 frequency samples from 24 lens configurations and six complete 801-frequency bands. All six bands satisfy a $10^{-10}$ full-complex error target and a one-percent integrated diffraction-residual target with the stated empirical reference margins. On these bands, the numerical representation meets a joint complex-field and diffraction-residual target beyond the accuracy of the tested image-plus-cusp and secant approximations. The timing comparison uses a common $10^{-8}$ full-complex and one-percent residual target. Paired comparisons on four of the six tested bands give median preparation-plus-first-band cost ratios of 3.66–6.34 in favor of the direct evaluator. The resulting evaluator targets first-band calculations for changing dimensionless lens models.
