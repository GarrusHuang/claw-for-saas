---
name: workflow-automation
description: 工作流自动化能力，支持多步骤业务流程的自动编排、状态追踪和异常处理
type: capability
version: 1.0
applies_to: [universal]
business_types: [reimbursement, contract, procurement, hr, inventory]
tags: [工作流, 自动化, 编排, 流程]
token_estimate: 900
---

# 工作流自动化能力

## 核心能力

### 1. 流程编排
- 根据业务场景自动确定执行步骤
- 识别步骤间的依赖关系
- 支持条件分支（如：金额超限走加签流程）
- 自动跳过不适用的步骤

### 2. 状态追踪
- 实时报告当前执行进度
- 记录每个步骤的输入输出
- 计算累计耗时和预估剩余时间

### 3. 异常处理
- 工具调用失败时自动重试（最多 2 次）
- 非关键步骤失败时继续执行
- 关键步骤失败时暂停并报告

### 4. 结果汇总
- 自动生成执行报告
- 标注成功/失败/跳过的步骤
- 提供后续操作建议

## 自主决策策略

| 信号 | 行为 |
|------|------|
| candidate_types 存在 | 先进行类型推断 |
| form_fields 存在 | 需要表单填写 |
| audit_rules 存在 | 需要审计检查 |
| 类型推断 + 表单填写同时存在 | 复杂任务，先出方案 |
| 仅 audit_rules | 简单任务，直接执行 |
