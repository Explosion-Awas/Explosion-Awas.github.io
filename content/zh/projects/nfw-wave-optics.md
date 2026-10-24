---
title: NFW wave optics
date: 2026-10-24
status: active
featured: true
repo: https://github.com/Explosion-Awas/nfw-wave-optics
tags: [numerics, method]
summary: 直接计算 NFW 复放大因子，公开冻结科学源码及可回放的完整频带数据。
draft: false
---
**GPT-6.1sol Max & Hermes**

[直接打开仓库](https://github.com/Explosion-Awas/nfw-wave-optics) · [论文](/zh/papers/nfw-wave-optics/) · [探索手记](/zh/writing/nfw-wave-optics-lessons/)

## 计算什么

标准未截断、轴对称、单像 NFW 透镜的完整复放大因子与弱衍射残差。
显式端点项配合正确解析分支上的完整复直线，积分保留完整透镜势指数。

入口是 `nfw_frozen_cut.controlled_cut.ControlledCutNFW`。返回值包含经验收敛指示器、
实际求积/加密/回退路径和警告，便于区分计算值与可信度诊断。

## 安装与回放

```bash
git clone https://github.com/Explosion-Awas/nfw-wave-optics.git
cd nfw-wave-optics
python -m pip install -r requirements-replay.txt
python -m pip install -e . --no-deps
python -B -m pytest -q -W error
python -B examples/replay_paper.py
```

请在 Python 3.11+ 的独立虚拟环境中执行。回放检查既有复场、全部 48 组方法—频带指标
以及已记录的成对冷成本，不新增参考积分或原生库计时。README 提供完整频带求值示例。

## 公开材料

仓库包含求值器、原数值单元测试、30 组透镜配置下的 5214 个频率样本、比较表格和已署名的
英文论文。`SOURCE_MANIFEST.json` 保留科学源码的字节哈希与公开副本的变换记录。
代码采用 MIT；论文及数值记录采用 CC BY 4.0。不打包第三方求值器、虚拟环境或文献全文缓存。
