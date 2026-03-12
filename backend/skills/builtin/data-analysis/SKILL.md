---
name: data-analysis
description: 数据分析与统计能力，支持对业务数据进行汇总、趋势分析、异常检测和报表生成
type: capability
version: 1.0
applies_to: [universal]
business_types: [reimbursement, contract, procurement, inventory]
tags: [数据, 分析, 统计, 报表]
token_estimate: 1200
---

# 数据分析能力

## 核心原则

所有数值计算必须使用 calculator 工具，严禁 LLM 心算。
分析结论必须基于数据事实，不得主观臆断。

## 分析策略

### 1. 汇总统计
- 求和、平均值、最大/最小值使用 `sum_values` 和 `arithmetic`
- 占比分析使用 `calculate_ratio`
- 数值比较使用 `numeric_compare`

### 2. 趋势分析
- 同比/环比变化率计算
- 月度/季度/年度趋势识别
- 异常波动检测（偏离均值超过 2 倍标准差）

### 3. 异常检测
- 金额异常：单笔超过历史平均 3 倍
- 频率异常：同一供应商/部门短期内高频交易
- 模式异常：不符合历史消费习惯

### 4. 报表输出
- 结果以结构化 JSON 输出
- 包含原始数据、计算过程、分析结论
- 关键指标标注红/黄/绿状态
