---
name: compliance-check
description: 合规性检查能力，对业务操作进行政策合规、流程规范、权限校验的综合检查
type: capability
version: 1.0
applies_to: [universal]
business_types: [reimbursement, contract, procurement, hr]
tags: [合规, 检查, 政策, 风控]
token_estimate: 1000
---

# 合规性检查能力

## 核心原则

合规检查结果必须明确标注 pass/fail/warning，不允许模糊结论。
检查过程必须引用具体的政策条款或规则依据。

## 检查维度

### 1. 政策合规
- 费用标准是否符合公司政策
- 审批流程是否完整
- 是否在预算范围内

### 2. 流程规范
- 必填字段是否完整
- 时间节点是否合理（如：报销是否超期）
- 审批层级是否正确

### 3. 权限校验
- 操作人是否有对应权限
- 金额是否在审批权限内
- 跨部门操作是否有授权

### 4. 风险预警
- 重复提交检测
- 关联交易识别
- 异常模式预警

## 输出规范

每条检查结果包含:
- rule_id: 规则编号
- status: pass | fail | warning
- message: 检查说明
- evidence: 依据数据
- suggestion: 改进建议（仅 fail/warning 时）
