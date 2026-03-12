---
name: smart-form-fill
description: 智能表单填写能力，根据上下文、历史数据和用户偏好自动推断和填充表单字段
type: capability
version: 1.0
applies_to: [universal, universal_form_agent]
business_types: [reimbursement, contract, procurement, hr]
tags: [表单, 填写, 智能, 推荐]
token_estimate: 1100
---

# 智能表单填写能力

## 核心原则

1. **已知值保护**: known_values 中的字段不可修改，直接采用
2. **确定性计算**: 涉及数值的字段必须使用 calculator 工具
3. **偏好优先**: 用户历史修正过的字段，优先采用用户偏好值

## 填写优先级

```
P1: known_values (系统预设，不可覆盖)
P2: user_preferences (用户历史修正偏好)
P3: mcp_data (从 MCP 工具查询到的实时数据)
P4: material_extract (从材料/附件中提取)
P5: default_value (字段默认值)
P6: inference (Agent 推断)
```

## 字段类型处理策略

### 文本类 (text, textarea)
- 直接从材料提取关键信息
- 保持简洁、规范的表述

### 选择类 (select, radio)
- 严格匹配可选项
- 不在选项列表中的值标记为需人工确认

### 数值类 (number, currency)
- 必须使用 calculator 工具计算
- 金额精确到分 (两位小数)

### 日期类 (date, dateRange)
- 格式统一为 YYYY-MM-DD
- 使用 date_diff 工具计算天数差

### 联动类
- 根据上级字段值确定下级可选范围
- 科室→预算中心，职级→费用标准

## 置信度标准

- 1.0: 来自 known_values 或精确匹配
- 0.9: 来自 MCP 查询或材料明确提取
- 0.7-0.8: 来自推断或模糊匹配
- <0.7: 需人工确认
