---
name: skill-creator
description: "Skill 创建与管理指南。当用户要求创建新 Skill、修改已有 Skill、或扩展 Agent 能力时使用此技能。支持通过对话式协作完成 Skill 的设计、编写和注册。"
type: capability
version: 1.0
applies_to: [universal]
business_types: [reimbursement, contract, procurement, hr, inventory]
tags: [skill, 创建, 管理, 元技能]
token_estimate: 2000
---

# Skill Creator — Skill 创建与管理指南

## 关于 Skill

Skill 是模块化、自包含的知识单元，通过 SKILL.md 文件为 Agent 注入专业领域知识、业务流程和工具使用策略。每个 Skill 让通用 Agent 变成特定领域的专家。

### Skill 提供什么

1. **领域知识** — 行业规则、公司政策、业务逻辑
2. **工作流程** — 多步骤操作指南
3. **工具策略** — 何时使用什么工具、以什么顺序
4. **参考资料** — 按需加载的详细文档

## 核心原则

### 简洁是关键

上下文窗口是共享资源。Skill 与系统提示、对话历史、业务参数共享上下文。

**默认假设: Agent 已经很聪明。** 只添加 Agent 不具备的知识。每段内容都要思考："Agent 真的需要这个说明吗？" "这段内容值得它占用的 token 吗？"

优先用简洁的示例代替冗长的解释。

### 适度的自由度

根据任务的脆弱性和多样性匹配指导的具体程度:

- **高自由度**: 多种方法都可行时，给出原则和启发式策略
- **中自由度**: 有优选模式时，给出伪代码或参数化指导
- **低自由度**: 操作脆弱/一致性要求高时，给出精确步骤

## Skill 结构

```
skill-name/
├── SKILL.md (必须)
│   ├── YAML frontmatter (必须)
│   │   ├── name: Skill 名称 (小写+连字符)
│   │   ├── description: 触发描述 (说明何时使用)
│   │   ├── type: domain / scenario / capability
│   │   ├── version: 版本号
│   │   ├── applies_to: 适用 Agent [universal]
│   │   ├── business_types: 适用业务类型
│   │   ├── depends_on: 依赖列表
│   │   ├── tags: 标签
│   │   └── token_estimate: 预估 token
│   └── Markdown body (指导和知识)
└── references/ (可选)
    └── *.md — 按需加载的详细文档
```

### 三种 Skill 类型

| 类型 | 用途 | 示例 |
|------|------|------|
| `domain` | 领域基础知识，多场景共享 | hospital-finance, contract-knowledge |
| `scenario` | 特定场景策略，含完整工作流 | reimbursement_create, contract_draft |
| `capability` | 能力增强，跨场景通用 | data-analysis, compliance-check |

### 加载策略 (三级渐进加载)

1. **L1 元数据**: name + description — 始终在上下文中 (~100词)
2. **L2 正文**: Markdown body — 触发后加载 (建议 <500行)
3. **L3 参考资料**: references/ 下的文件 — Agent 按需通过 `read_reference` 工具读取

## Skill 创建流程

### 第 1 步: 理解需求 (收集具体用例)

通过对话理解用户想创建什么 Skill:

- "这个 Skill 要解决什么问题？"
- "能给一些具体使用场景的例子吗？"
- "用户会说什么话来触发这个 Skill？"
- "已有的 Skill 有哪些不能满足的？"

避免一次问太多问题。从最重要的开始，逐步深入。

### 第 2 步: 规划 Skill 内容

分析每个用例，确定 Skill 需要包含什么:

1. **核心知识**: Agent 不具备的领域专业知识
2. **工作流程**: 需要重复执行的多步骤操作
3. **决策策略**: 帮助 Agent 在模糊情况下做出正确判断
4. **参考资料**: 详细文档 (大文件放 references/)

### 第 3 步: 设计 Frontmatter

frontmatter 是 Skill 的触发机制，必须精心设计:

- **name**: 小写+连字符，动词短语优先 (如 `invoice-processing`, `budget-analysis`)
- **description**: 必须包含"何时使用"的触发条件。这是 Agent 决定是否加载 Skill 的唯一依据
- **type**: 根据用途选择 domain/scenario/capability
- **depends_on**: 如果依赖其他领域知识 Skill，列出依赖 (如 scenario 依赖 domain)
- **applies_to**: 通常填 `[universal]`
- **business_types**: 填写适用的业务类型

### 第 4 步: 编写正文

正文要简洁、可操作:

- 使用祈使句/不定式
- 用标题和列表组织内容
- 核心工作流放在前面
- 详细参考资料放 references/
- 控制在 500 行以内

### 第 5 步: 创建 Skill

使用 `create_skill` 工具将设计好的 Skill 写入系统:

```
create_skill(
    name="...",
    description="...",
    skill_type="...",
    body="...",
    applies_to=["universal"],
    business_types=["..."],
    depends_on=["..."],
    tags=["..."],
    token_estimate=...
)
```

### 第 6 步: 迭代改进

Skill 创建后可通过 `update_skill` 工具迭代优化:

1. 在实际场景中测试 Skill 效果
2. 观察 Agent 的执行是否符合预期
3. 根据反馈调整正文内容或元数据
4. 使用 `update_skill` 工具更新

## 正文编写模式

### 模式 1: 信号→行为映射 (适合 scenario 类型)

```markdown
## 自主决策策略

| 信号 | 行为 |
|------|------|
| 存在 XX 字段 | 调用 XX 工具 |
| 金额超过阈值 | 额外审批流程 |
```

### 模式 2: 分步工作流 (适合 capability 类型)

```markdown
## 工作流程

### 1. 数据收集
- 调用 get_user_profile 获取用户信息
- 调用 get_expense_standards 获取标准

### 2. 分析处理
- 使用 calculator 工具进行数值计算
- 比对标准和实际值

### 3. 结果输出
- 生成结构化报告
```

### 模式 3: 知识库 (适合 domain 类型)

```markdown
## 核心概念

### 1. 概念 A
定义和说明...

### 2. 概念 B
定义和说明...

## 业务规则

- 规则 1: ...
- 规则 2: ...
```

## 命名规范

- 仅使用小写字母、数字和连字符
- 长度不超过 64 个字符
- 优先使用动词短语 (如 `process-invoice` 而非 `invoice`)
- 按工具命名空间分组 (如 `budget-analysis`, `budget-forecast`)

## 质量检查

创建完成后确认:

- [ ] description 清晰描述了触发条件
- [ ] 正文不超过 500 行
- [ ] 没有重复 Agent 已有的通用知识
- [ ] depends_on 正确列出了依赖
- [ ] 关键决策有明确的判断标准
