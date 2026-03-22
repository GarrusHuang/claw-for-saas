# Claw Agent Framework Roadmap

> 基于 Codex (https://github.com/openai/codex) 源码级对比分析
> 创建日期: 2026-03-19

---

## 架构差异前提

**Codex** = 单用户本地 CLI，运行在开发者自己的机器上，直接操作本地文件系统和 shell。
**Claw** = 多租户服务端 SaaS，部署在服务器上，5000 用户共享同一套后端，通过 WebSocket 推送事件。

这个根本差异决定了哪些 Codex 功能值得借鉴、哪些不适用：

| Codex 特性 | 适用性 | 原因 |
|:-----------|:-------|:-----|
| apply_patch | **适用** | 文件编辑 token 节省与部署形态无关 |
| 工具输出截断 (head+tail) | **适用** | 通用优化 |
| 压缩 prompt (交接摘要) | **适用** | 通用优化 |
| TurnDiffTracker | **适用** | 沙箱 workspace 内的变更追踪 |
| Memory 提取 prompt 改进 | **适用 (需控制成本)** | 多用户场景需考虑 LLM 调用成本 |
| Tool Search (延迟加载) | **适用** | MCP/插件可能引入大量工具 |
| request_user_input | **适用** | WebSocket 天然支持异步交互 |
| grep_files / list_dir | **适用** | 沙箱 workspace 内的文件操作 |
| Secrets 输出脱敏 | **适用 (方案不同)** | 服务端从配置/数据库读取 secret pattern，不是用户 keyring |
| 命令安全策略 | **适用 (方案不同)** | 服务端由管理员通过 API 配置，不是本地 .rules 文件 |
| OpenTelemetry | **适用 (更重要)** | 服务端多用户运维比 CLI 更需要可观测性 |
| Collaboration Mode | **部分适用** | Plan/Execute 有价值，但 "交互式审批" 在 Web 场景要重新设计 |
| Tool Orchestrator | **部分适用** | 统一编排有价值，但 "沙箱自动升级" 在服务端意义不同 |
| Multi-Agent 完整生命周期 | **部分适用** | 有价值，但要加 per-user 并发限制防止资源滥用 |
| Guardian (LLM 审批) | **适用 (限高风险操作)** | 只对 run_command/write 等高风险操作触发，用小模型控制成本，租户可选 |
| OS 级沙箱 (landlock/seatbelt) | **不适用** | Claw 已有 Docker 沙箱，服务端不需要 macOS seatbelt |
| Shell Snapshot | **不适用** | 服务端没有用户 shell 环境需要捕获 |
| Config Layer Stack | **不适用** | Claw 已有 tenant 级配置 + .env，不需要 global→project→local 合并 |
| Network Proxy (MITM) | **不适用** | 服务端用 Docker 网络隔离 + 防火墙更合适 |
| Commit Attribution | **不适用** | CLI 概念，服务端不做 git commit |
| Personality 切换 | **不适用** | Claw 的 Soul.md + 租户级 Skill 已经覆盖 |
| Undo / Review | **低优先级** | 沙箱 workspace 是临时的，用户不像操作自己电脑那样需要回滚 |

---

## Claw 已具备的能力

- ReAct 循环引擎 (25 轮迭代)
- 流式输出 (EventBus → WSBridge → WebSocket)
- 四阶段上下文压缩
- 37 个内置工具 (只读并行 / 写入串行)
- Hook 系统 (pre/post_tool_use, agent_stop, pre_compact)
- 8 层模块化提示词架构
- Markdown 三层记忆系统 + 自动提取
- Skill 四级加载 (builtin→plugin→tenant→user)
- MCP 标准工具接口 (条件注册)
- 子 Agent 派发
- 定时调度 + Webhook
- 文件沙箱 + Docker 沙箱
- JSONL 会话持久化
- 用量统计 (SQLite)
- 多租户隔离 (tenant/user)
- JWT + API Key 认证

---

## Pre-Phase — 代码健康 (半天~1天/项)

后续功能开发的前提，降低改动时的认知负担和冲突风险。

### P.1 Gateway.chat() 拆分 ✅

**已完成** (2026-03-19): `chat()` 提取 `_setup_context_vars()`，`_chat_inner()` 拆出 `_load_prompt_sources()` / `_build_prompt_and_message()` / `_persist_results()` 三个方法，`_chat_inner()` 变为 ~60 行的 6 步流程。

### P.2 ContextVar 合并为 RequestContext ✅

**已完成** (2026-03-21): `core/context.py` 新增 `RequestContext` dataclass + `current_request` ContextVar + `get_request_context()` helper。Gateway `_setup_context_vars()` 构建 `RequestContext` 并返回，`_chat_inner()` / `_load_prompt_sources()` / `_build_prompt_and_message()` / `_persist_results()` 四个方法改用 `ctx: RequestContext` 替代 5-8 个 kwargs 透传。工具层全量迁移完成，旧 ContextVar 已删除 — 所有消费者 (10 个工具文件 + runtime/prompt/hooks/quality_gate/security_hooks) 统一使用 `get_request_context()` 或 `current_request.get()`。

### P.3 文件工具分页逻辑去重 ✅

**已完成** (2026-03-19): 提取 `paginate_text()` + `PaginationResult` 到 `core/text_utils.py`，`read_uploaded_file` 和 `read_knowledge_file` 各 ~25 行分页代码替换为调用公共函数。新增 `TestPaginateText` 测试类。

### P.4 smart_truncate 移位 ✅

**已完成** (2026-03-19): `smart_truncate()` 从 `core/tool_registry.py` 移到 `core/text_utils.py`，`tool_registry.py` 和 `tests/test_a4_context.py` 改为从新位置 import。随 0.1 一起完成。

### P.5 前端 useAIChat Hook 拆分 ✅

**已完成** (2026-03-22): `hooks/useAIChat.ts` (682 行) 拆分为三个职责清晰的 Hook。

- `useChatMessages` (~90 行) — 消息状态 + addMessage + streaming text 效果 + agent 完整回复效果
- `useSessionManager` (~220 行) — session CRUD + 切换 + 缓存恢复 + F5 保护 + 定期保存 + sessions 列表
- `useAIChat` (~180 行) — 组合 Hook: 调用上面两个 + pipeline dispatch + 场景选择 + 自动启动 + 完成转场

返回签名不变，AIChatDialog.tsx 无需改动。87 个前端测试通过。

---

## Phase 0 — 快速收益 (1~2 天/项)

实现简单、效果明显、不涉及架构变更。

### 0.1 工具输出截断改进 — 前缀+后缀保留 ✅

**已完成** (2026-03-19): head+tail 截断已在 A4 中实现，本次改进了截断 marker 格式。

- 截断 marker 从 `...[truncated N chars]...` 改为 `...[truncated N of M chars, L lines total]...`
- 增加原始总字符数和总行数，让模型知道完整输出有多大
- `smart_truncate` 移到 `core/text_utils.py` (P.4 一并完成)
- 81 个单元测试通过 + Playwright 端到端验证通过

### 0.2 压缩 prompt 改进 — "交接摘要"范式 ✅

**已完成** (2026-03-19): 参考 Codex 的 "交接摘要" 范式，重写了 stage2 压缩 prompt。

- 新建 `prompts/compact_prompt.md` — 结构化交接摘要指令 (任务目标/已完成/待完成/关键数据)
- 新建 `prompts/compact_prefix.md` — 摘要前缀标记
- `_generate_summary()` system prompt 从文件加载 (带类级缓存)，max_tokens 300→500
- 额外提取 middle 中的 user messages 传给 LLM，保留用户原始需求上下文
- heuristic fallback 逻辑不变
- 90 个单元测试通过 (含 7 个新增测试)

### 0.3 Environment Context 增强 ✅

**已完成** (2026-03-19): `_format_runtime_context()` 增加 3 个字段。

- `workspace_dir` — 从 `RequestContext` 获取沙箱工作目录 (有 sandbox 时才输出)
- `timezone` — 从 `Settings().scheduler_timezone` 读取 (默认 Asia/Shanghai)
- `platform` — `platform.system()` (Linux)
- 改为 `@staticmethod`，不依赖 self
- 5 个新增单元测试通过

---

## Phase 1 — 核心能力补齐 (3~5 天/项)

### 1.1 apply_patch 工具 ✅

**已完成** (2026-03-21): 新增 `tools/builtin/apply_patch.py`，采用与 Codex 相同的 patch 格式 (`*** Begin Patch` / `*** End Patch` 包裹，支持 Add/Delete/Update 三种操作)。核心算法: 解析 patch → 分离 hunks → 逐 chunk seek_sequence 定位 (三级 fuzzy matching: 精确 → trim trailing → trim both) → 计算 replacements → 逆序应用。安全: 路径校验复用 SandboxManager + 绝对路径/路径穿越拦截。`soul.md` 引导 Agent 优先使用 `apply_patch` 进行增量编辑。39 个测试通过。

### 1.2 TurnDiffTracker — 变更追踪 ✅

**已完成** (2026-03-22): 新增 `core/file_diff_tracker.py` (TurnDiffTracker 类)，在 Gateway `_chat_inner()` 中创建 (per-request)，挂载到 RequestContext。`write_source_file` / `apply_patch` 执行前自动捕获 baseline，写入后记录操作。turn 结束时 `generate_diffs()` 用 `difflib.unified_diff` 生成累积 diff，通过 EventBus 发射 `file_changes` 事件 + timeline 持久化。前端: `FileChange` 类型 + pipeline store `fileChanges` 状态 + dispatcher `file_changes` 事件处理。

### 1.3 Memory 系统升级 ✅

**已完成** (2026-03-22): 提取 prompt 改进 (第 3 批已含 no-op gate + 分类 + 安全规则) + 扩大输入范围 + 后台自动合并。

1. **扩大提取输入** — `_auto_save_memory()` 新增 `timeline_entries` 参数，`_persist_results()` 中 timeline 构建提前到 memory 提取之前执行。新增 `_summarize_timeline()` 静态方法，将 timeline 压缩为每行一条的摘要 (上限 1500 字)，注入提取 prompt 的 `<timeline>` 子块。
2. **后台定期合并** — `MarkdownMemoryStore.scan_and_merge_all()` 扫描 `data/memory/user/` 全部目录，对超 50KB 的 auto-learning.md 执行 LLM 合并，每轮上限 50 用户。`main.py` lifespan 新增 `_memory_merge_loop()` 后台循环 (先 sleep 再扫描，避免冷启动触发大量 LLM 调用)。新增配置: `memory_merge_interval_hours` (默认 6)、`memory_merge_max_per_run` (默认 50)。

1734 个后端测试通过。

### 1.5 超长文档完整读取 ✅

**已完成** (2026-03-22): 三项改进。

1. **DOCX 标题提取** — `file_service._extract_docx()` 检测 `p.style.name`，Heading 1-4 + Title/Subtitle 加 Markdown `#` 标记，额外提取表格为 Markdown 表格格式。
2. **analyze_file 返回大纲** — DOCX 分支新增 `outline` (标题层级 + char_offset) + `estimated_chars`，Agent 可定位目标章节再精准读取。
3. **PDF 页数上限** — `content_processor.py` 的 `max_pages` 从 50 提升到 500。
4. **soul.md 大文件阅读策略** — 引导 Agent 先 `analyze_file` 查看大小和结构，大文档用 outline 定位 + offset 分段读取。

### 1.4 request_user_input 工具 ✅

**已完成** (2026-03-22): 新增 `tools/builtin/interaction.py`，`request_user_input(question, options?, input_type?)` 工具。有 options (逗号分隔) 时发射 `request_confirmation` 事件显示按钮选择，无 options 时发射 `request_input` 事件显示文本输入框。注册到 `registry_builder.py`，`soul.md` 加使用引导。前端已有完整支持: InteractiveMessage 组件 + pipeline-dispatcher 事件处理 + inject 端点注入回复。

---

## Phase 2 — 安全与可观测 (3~5 天/项)

多用户 SaaS 的生产级安全和运维需求。

### 2.1 命令安全策略 ✅

**已完成** (2026-03-22): 新增 `core/exec_policy.py` (ExecPolicy 类)，提供结构化命令安全检查: 17 条危险命令正则黑名单 (原 12 + 新增 kill -9 -1 / pkill -9 / chown root / iptables / nc -l) + 30+ 安全命令前缀白名单 (ls/cat/grep/python/git status 等)。白名单优先跳过黑名单检查。支持 `extra_dangerous`/`extra_safe` 扩展参数供租户自定义。`hooks.py` 的 `code_safety_hook()` 重构为委托 ExecPolicy，同时新增 apply_patch 的敏感文件检查。

### 2.2 Secrets 输出脱敏 ✅

**已完成** (2026-03-22): 新增 `core/secret_redactor.py` (SecretRedactor 类)，双层脱敏策略: 字面值精确匹配 (从 Settings 收集 llm_api_key/auth_jwt_secret，最小 8 字符，排除 "not-needed" 默认值) + 正则模式兜底 (Bearer token / sk-* API key / AKIA AWS key / password=* 等)。通过 `dependencies.py` 工厂创建，传入 AgentGateway → AgenticRuntime → SubagentRunner，在两处关键路径应用: 工具结果序列化到 LLM messages + tool_executed SSE 事件推送到前端。

### 2.3 Tool Search — 延迟工具加载 ✅

**已完成** (2026-03-22): 工具总数超过阈值 (默认 30) 时自动切换延迟加载模式。新增 `tools/builtin/tool_search.py` (tool_search 工具，关键词搜索延迟工具)。`ToolRegistry` 新增 `search_tools()` + `subset()` 方法。`Gateway._build_prompt_and_message()` 按 `CORE_TOOL_NAMES` 分割核心/延迟工具，延迟工具存入 `RequestContext.deferred_tools`。`Runtime` 新增 `llm_tool_registry` 参数，延迟模式下 LLM 只收到核心工具 schema，执行仍走全量 registry。`PromptBuilder` 在 `<tools>` 末尾追加延迟工具数量提示。

### 2.4 OpenTelemetry 集成 ✅

**已完成** (2026-03-22): 新增 `core/tracing.py` — 完全 opt-in 的 OTel 集成，`otel_enabled=False` (默认) 时零开销 (NoOp tracer/span，不 import OTel 包)。未安装 OTel 包时自动 fallback 到 NoOp。4 个关键 span: `gateway.chat` (session_id/tenant_id) → `runtime.react_loop` (max_iterations) → `runtime.tool_call` (tool.name/success/latency_ms) + `llm.stream_call` (llm.model)。配置项: `OTEL_ENABLED` / `OTEL_ENDPOINT` / `OTEL_SERVICE_NAME`。`main.py` lifespan 中初始化和关闭。

---

## Phase 3 — 体验提升 (3~5 天/项)

### 3.1 grep_files / list_dir 专用工具

**现状**: 通过 `run_command` 间接执行，不受沙箱保护。
**Codex 做法**: 专用工具，参数结构化，结果格式化，有分页和深度控制。

**服务端适配**:
- 重要: `run_command` 在服务端需要沙箱保护，专用工具绕过 shell 更安全
- 结果受 `max_tool_result_chars` 控制

**要做的事**:
- 新增 `grep_files` 工具: pattern / include / path / limit 参数，沙箱路径限制
- 新增 `list_dir` 工具: dir_path / depth (默认 2) / offset / limit 参数
- 标记为只读 (可并行)
- 直接用 Python os/re 实现，不依赖外部 rg 命令

**收益**: 比 run_command 更安全、结果更可控。

### 3.2 Collaboration Mode (简化版)

**现状**: Agent 总是全自主。
**Codex 做法**: Plan / Execute / Default / Pair Programming 四种模式。

**服务端适配**:
- ~~Default (交互式审批)~~ — Web 场景不适合每个工具调用都弹窗审批
- ~~Pair Programming~~ — CLI 概念，Web 不适用
- **Plan Mode** — 有价值: 用户先看计划再确认执行
- **Execute Mode** — 就是现在的默认行为

**只做两种模式**:

| 模式 | 行为 |
|:-----|:-----|
| **plan** | Agent 只做分析和规划 (只允许只读工具)，产出 `<proposed_plan>`，用户确认后切换到 execute 执行 |
| **execute** | 全自主 (当前行为，默认) |

**要做的事**:
- `ChatRequest` 增加 `mode` 字段 (plan / execute，默认 execute)
- plan mode: Gateway 过滤掉写入工具，PromptBuilder 注入 plan mode 引导
- 前端: 收到 plan 后展示确认按钮 (已有 InteractiveMessage 基础)
- 确认后前端自动发起 execute mode 请求

**收益**: 复杂任务先看计划再执行，减少试错成本。

### 3.3 Multi-Agent 生命周期增强

**现状**: 只有 `spawn_subagent`。
**Codex 做法**: spawn + wait + send_input + close + resume 五个操作。

**服务端适配**:
- 关键: per-user 并发限制 (防止一个用户 spawn 大量子 Agent 耗尽服务器资源)
- depth limit (防止无限嵌套)
- ~~resume~~ — 服务端子 Agent 是异步任务，不存在 "暂停/恢复" 概念
- ~~fork parent context~~ — 服务端可以通过 session 历史实现，不需要特殊机制

**只做三个增强**:

| 操作 | 说明 |
|:-----|:-----|
| `wait_subagent(agent_id)` | 等待子 Agent 完成，获取结果 |
| `send_to_subagent(agent_id, message)` | 向运行中的子 Agent 发消息 |
| depth limit + 并发 guard | 最大深度 3，每用户同时最多 3 个子 Agent |

**收益**: 子 Agent 可控可通信，复杂任务分解更有效。

### 3.4 Guardian — AI 驱动的风险评估

**现状**: Hook 系统有 pre_tool_use 可以 block，但判定逻辑是规则式的。
**Codex 做法**: `guardian/` — 用专门的 LLM 会话评估工具调用风险 (risk_score 0-100，< 80 放行)。

**服务端适配**:
- 不是每次工具调用都触发 — 只对高风险操作 (run_command、write_source_file) 触发
- 只读工具 + 规则 Hook 已放行的操作跳过 Guardian
- 用小模型 + 低 max_tokens (如 200) 控制单次成本
- 作为租户级可选功能 (管理员通过配置开启)
- 规则 Hook 作为第一道防线 (零成本)，Guardian 作为第二道 (仅在规则无法判定时)

**要做的事**:
- 新增 `agent/guardian.py` 模块
- Guardian 判定逻辑: 重建精简上下文 → 调 LLM → 解析 JSON → risk_score 判定
- 在 pre_tool_use hook 链中注册，排在规则 Hook 之后
- 配置项: `guardian_enabled` (默认 false)、`guardian_model` (可用比主模型更便宜的)、`guardian_risk_threshold` (默认 80)
- 超时 30 秒，失败 → 拒绝 (fail closed)

**收益**: 多租户场景安全性提升 — 规则覆盖不到的边界 case 由 AI 兜底。

---

## 不适用于服务端的 Codex 功能

以下功能是 Codex 作为本地 CLI 工具的特有设计，在服务端 SaaS 架构下没有对应的需求场景：

| Codex 功能 | 不适用原因 |
|:-----------|:-----------|
| **OS 级沙箱 (landlock/seatbelt/windows-sandbox)** | 这是保护开发者本地文件系统的机制。Claw 服务端已有 Docker 沙箱 + 应用层路径校验 |
| **Shell Snapshot** | Codex 捕获用户本地 shell 的环境变量 (PATH/GOPATH 等)。服务端没有用户 shell，命令在沙箱中执行 |
| **Network Proxy (MITM 透明代理)** | Codex 在用户机器上拦截所有网络流量。服务端用 Docker 网络隔离 + `sandbox_network_whitelist` 即可 |
| **Config Layer Stack (global→project→local)** | Codex 按 ~/.codex → 项目目录 → 命令行参数 合并配置。Claw 已有 tenant 级配置 + .env |
| **Commit Attribution (Co-authored-by)** | Codex 在用户本地做 git commit 时注入署名。服务端不做 git 操作 |

---

## Phase 4 — 产品完整性 (非 Codex 对比，项目自身需求)

以下问题来自代码审查，与 Codex 对比无关，是 5000 用户 SaaS 产品自身需要解决的。

### 4.1 LLM Fallback 模型未实现

**现状**: `config.py` 定义了 `llm_fallback_model` 字段，但代码中没有任何地方使用它。主模型不可用时直接失败。

**要做的事**:
- `core/llm_client.py` 在主模型连续失败时 (如 3 次超时/503) 自动切换到 fallback 模型
- 切换时通过 EventBus 通知前端 "已降级到备用模型"
- fallback 模型可用后自动切回主模型

**收益**: 服务可用性提升，生产环境对单一 LLM 提供商的依赖降低。

### 4.2 SQLite 并发瓶颈

**现状**: `DatabaseService` 和 `UsageService` 每次操作都 `sqlite3.connect() → execute → close()`，没有连接池。5000 用户并发写入 `usage_events` 会产生锁竞争。

**要做的事**:
- 方案 A (简单): 使用连接池 (如 `aiosqlite` 或维护一个线程本地连接)
- 方案 B (长期): usage_events 高频写入改为内存缓冲 + 批量刷盘 (每 N 秒或每 M 条)
- 可选: 预留切换到 PostgreSQL 的接口 (用户规模继续增长时)

**收益**: 减少数据库锁竞争，提升高并发写入性能。

### 4.3 Session 自动过期清理

**现状**: 文件上传有过期清理 (`file_retention_days`)，但 `data/sessions/` 下的 JSONL 会话文件没有自动清理机制。5000 用户持续使用会累积大量文件。

**要做的事**:
- 类似 file_cleanup_loop，在 lifespan 中启动 session_cleanup_loop
- 配置项: `session_retention_days` (默认 30)
- 清理策略: 超过保留期的 JSONL + timeline + plan 文件一并删除
- 可选: 只删消息文件，保留 metadata (用于历史记录列表)

**收益**: 控制磁盘增长。

### 4.4 Token 自动刷新

**现状**: 前端 `auth.ts` 在 token 过期后静默登出。没有主动刷新机制 — 用户正在操作时 token 过期会中断体验。

**要做的事**:
- 前端增加定时器: token 到期前 5 分钟自动调用 `/api/auth/refresh`
- 如果 refresh 失败 (后端重启、secret 变更)，提示用户重新登录而非静默登出
- WebSocket 断开重连时也检查 token 有效性

**收益**: 用户长时间使用不会被突然踢出。

### 4.5 管理后台 UI

**现状**: 租户/用户/API Key/配额管理只有后端 API (`api/admin.py`)，没有前端管理界面。管理员只能用 curl 或 Postman。

**要做的事**:
- 新增 `frontend/app/src/AdminPage.tsx`
- 页面: 租户管理 / 用户管理 / 用量仪表盘 / Skill 管理 / 系统设置
- 基于角色的路由守卫 (admin role)

**收益**: 管理员操作效率提升，不依赖开发者协助配置。

### 4.6 用户注册流程

**现状**: 只有管理员通过 API 创建用户 (`db.create_user`)。没有自助注册。

**要做的事**:
- 可选: 管理员邀请制 (生成邀请链接 → 用户设置密码) 或开放注册 (租户管理员控制)
- 前端 LoginPage 增加 "注册" 入口
- 后端 `/api/auth/register` 端点 (需要邀请码或租户管理员审批)

**收益**: 降低用户 onboarding 成本。

---

## 依赖关系

```
P.1 Gateway 拆分 ──→ P.2 ContextVar 合并 (P.1 拆完再改注入更清晰)
                 ──→ 1.2 TurnDiffTracker (Gateway 层创建 tracker)
                 ──→ 2.4 OpenTelemetry (Gateway 拆完后 span 粒度更合理)

P.3 文件分页去重 ──→ 3.1 grep_files/list_dir (复用分页函数)
                 ──→ 1.5 超长文档完整读取 (复用分页函数 + 基于 offset 精准定位)

P.5 useAIChat 拆分 ──→ 1.4 request_user_input (前端交互组件需要拆分后的 Hook)
                   ──→ 3.2 Collaboration Mode (plan 确认交互需要拆分后的 Hook)

1.1 apply_patch ──→ 1.2 TurnDiffTracker (追踪 patch 产生的变更)

2.1 命令安全策略 ──→ 3.4 Guardian (规则是第一道防线，Guardian 是第二道)

无依赖 (可随时启动):
  0.2 压缩 prompt、0.3 Environment Context
  P.1、P.3、P.5
  1.1 apply_patch、1.3 Memory 改进
  2.1 命令安全、2.2 Secrets 脱敏、2.3 Tool Search
  3.3 Multi-Agent 增强
  4.1~4.6 全部独立
```

### 推荐执行顺序

基于依赖关系和收益，建议按以下顺序推进：

| 批次 | 项目 | 理由 |
|:-----|:-----|:-----|
| **第 1 批** | ~~0.2 压缩 prompt + 0.3 Environment Context~~ ✅ | Phase 0 全部完成 |
| **第 2 批** | ~~P.1 Gateway 拆分 + P.3 文件分页去重~~ ✅ | 无依赖、解锁后续多项 |
| **第 3 批** | ~~P.2 ContextVar 合并~~ ✅ + ~~P.5 useAIChat 拆分~~ ✅ | 全部完成 |
| **第 4 批** | ~~1.1 apply_patch~~ ✅ + ~~1.3 Memory 改进~~ ✅ | 全部完成 |
| **第 5 批** | ~~1.2 TurnDiffTracker~~ ✅ + ~~1.4 request_user_input~~ ✅ + ~~1.5 超长文档完整读取~~ ✅ | 全部完成 |
| **第 6 批** | ~~2.1 命令安全~~ ✅ + ~~2.2 Secrets 脱敏~~ ✅ | 全部完成 |
| **第 7 批** | 2.3 Tool Search + 2.4 OpenTelemetry | 可观测性，2.4 受益于 P.1 |
| **第 8 批** | Phase 3 + Phase 4 | 按需排列 |

> 同一批次内的项目互相独立，可并行开发。

---

## 里程碑总结

```
Pre-Phase (代码健康)      ← 每项半天~1天，总计约 3 天
├── P.1 Gateway.chat() 拆方法 ✅ (2026-03-19)
├── P.2 ContextVar 合并为 RequestContext ✅ (2026-03-21)
├── P.3 文件工具分页去重 ✅ (2026-03-19)
├── P.4 smart_truncate 移位 ✅ (2026-03-19)
└── P.5 前端 useAIChat Hook 拆分 ✅ (2026-03-22)

Phase 0 (快速收益)        ← 每项 1-2 天，总计约 1 周
├── 0.1 工具输出截断 (head+tail) + P.4 ✅ (2026-03-19)
├── 0.2 压缩 prompt (交接摘要范式) ✅ (2026-03-19)
└── 0.3 Environment Context (workspace_dir + timezone) ✅ (2026-03-19)

Phase 1 (核心补齐)        ← 每项 3-5 天，总计约 3 周
├── 1.1 apply_patch 工具 ✅ (2026-03-21)
├── 1.2 TurnDiffTracker ✅ (2026-03-22)
├── 1.3 Memory 提取改进 (prompt + 输入范围 + 后台合并) ✅ (2026-03-22)
├── 1.4 request_user_input ✅ (2026-03-22)
└── 1.5 超长文档完整读取 (outline + 标题层级 + 阅读策略) ✅ (2026-03-22)

Phase 2 (安全与可观测)    ← 每项 3-5 天，总计约 3 周
├── 2.1 命令安全策略 (ExecPolicy 白名单+黑名单) ✅ (2026-03-22)
├── 2.2 Secrets 输出脱敏 (SecretRedactor 字面值+正则) ✅ (2026-03-22)
├── 2.3 Tool Search (延迟加载)
└── 2.4 OpenTelemetry

Phase 3 (体验提升)        ← 每项 3-5 天，总计约 3 周
├── 3.1 grep_files / list_dir
├── 3.2 Collaboration Mode (plan / execute)
├── 3.3 Multi-Agent 增强 (wait + send + guard)
└── 3.4 Guardian (AI 风险评估，租户可选)

Phase 4 (产品完整性)      ← 项目自身需求，非 Codex 对比
├── 4.1 LLM Fallback 模型实现
├── 4.2 SQLite 并发优化 (连接池 / 批量写入)
├── 4.3 Session 自动过期清理
├── 4.4 Token 自动刷新
├── 4.5 管理后台 UI
└── 4.6 用户注册流程
```
