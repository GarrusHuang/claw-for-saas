---
name: reimbursement_create
version: "2.0"
description: 报销创建场景领域知识
type: scenario
applies_to: [universal]
business_types: [reimbursement]
depends_on: [reimbursement-knowledge]
tags: [报销, 创建, 场景]
token_estimate: 1800
---

# 报销创建 — 领域知识

## 场景概述

报销创建是最常用的业务场景。用户上传报销材料（发票、行程单等），系统自动完成：识别报销类型、智能填写表单、执行合规审计。

## 类型推断知识

常见报销类型及匹配关键词：
- **差旅报销**: 出差、差旅、住宿、机票、火车票、交通费
- **日常办公报销**: 办公用品、打印、文具、日常采购
- **会议费报销**: 会议、培训、场地费、茶歇
- **科研报销**: 课题、科研、试剂、实验耗材

推断规则：
- 从用户材料中提取关键词，与 `<candidate_types>` 中的类型匹配
- confidence > 0.7 直接使用；0.5-0.7 标记低置信度；< 0.5 请求用户确认
- 不可擅自创造候选列表中不存在的类型
- reasoning 字段要说明匹配依据

## 表单填写知识

### 字段来源优先级
1. `<known_values>` 中的值 → 直接使用，不可覆盖
2. 用户画像 (`get_user_profile`) → 姓名、科室、职级、城市
3. 费用标准 (`get_expense_standards`) → 住宿标准、交通标准、餐补标准
4. 材料中提取 → 金额、日期、发票号
5. LLM 推断 → 备注、事由等文本字段

### 字段填写策略
- **基础信息字段**（姓名、科室、日期）：从 known_values 或 user_profile 获取
- **金额字段**: 从材料中的发票/行程单提取，用 calculator 验证
- **标准字段**（住宿标准、交通标准）：从 expense_standards 获取
- **备注字段**: 从用户消息或材料摘要提取
- **必填字段未能填写时**: 标记为 unfilled 并说明原因

### 信息溯源
每个字段值标注来源 source：known_value / user_profile / expense_standard / material / llm_inferred

## 审计知识

### 审计维度
1. **金额合规性**（最高优先级）
   - 各项费用是否超出对应职级和城市的标准
   - 总金额是否等于各分项之和（用 `sum_values` + `numeric_compare`）
   - 预算余额是否充足（用 `get_budget_balance`）
   - 所有数值运算必须使用 calculator 工具

2. **票据完整性**
   - 发票金额与报销金额是否一致
   - 发票日期是否在合理范围内
   - 调用 `verify_invoice` 验证发票真伪

3. **政策合规性**
   - 差旅标准是否符合职级规定
   - 交通方式是否符合级别限制

### 审计结论分级
- pass: 完全符合规则
- warning: 存在超标但有合理解释（如特殊城市、紧急出差）
- fail: 违反强制性规则

## 质量保障要点

1. **数值准确性**: 所有金额比较、求和必须通过 calculator 工具完成
2. **已知值保护**: known_values 在整个流程中不可被修改
3. **信息溯源**: 每个字段值标注来源
4. **审计独立性**: 审计时独立重新获取标准数据，不依赖表单填写的中间值
