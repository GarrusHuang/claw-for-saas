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
- 40 个内置工具 (只读并行 / 写入串行)
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

### 3.1 grep_files / list_dir 专用工具 ✅

**已完成** (2026-03-22): 新增 `tools/builtin/search_tools.py`，两个只读工具:

- `grep_files(pattern, path?, include?, max_results?, context_lines?)` — 纯 Python re + os.walk 搜索文件内容，跳过二进制文件 (前 8KB null 检测)，支持 glob 过滤和上下文行数，路径校验复用 SandboxManager
- `list_dir(path?, depth?, include?, offset?, limit?)` — 目录结构列出，含文件类型/大小/修改时间，目录优先排序，深度限制 (cap 10)，分页支持

注册到 `build_shared_registry()` (read-only)，`soul.md` 引导 Agent 优先使用而非 `run_command('grep/ls/find')`。18 个测试通过。

### 3.2 Collaboration Mode (简化版) ✅

**已完成** (2026-03-22): plan / execute 两种模式。

- `ChatRequest` 新增 `mode` 字段 (`plan` | `execute`，默认 `execute`)，含 pydantic validator
- plan 模式: Gateway 过滤写入工具 (只保留 read_only + propose_plan/update_plan_step)，`llm_tool_registry` 也只注入只读工具
- PromptBuilder 在 plan 模式下注入 "分析规划模式" 引导 prompt
- 前端: `usePipelineStore` 新增 `chatMode` 状态 + `setChatMode` action，请求体自动携带 `mode`
- 用户确认计划后手动发消息，默认 execute 模式执行
- 10 个测试通过

### 3.3 Multi-Agent 生命周期增强 ✅

**已完成** (2026-03-23): 子 Agent 完整生命周期管理。

1. **非阻塞启动** — `spawn_subagent(wait=False)` 返回 agent_id，后续用 `wait_subagent` 获取结果。`wait=True` (默认) 行为不变，向下兼容。
2. **等待/通信** — `wait_subagent(agent_id, timeout_s)` 等待完成，`send_to_subagent(agent_id, message)` 向运行中子 Agent 注入消息 (通过 Runtime `message_inbox` 队列)。
3. **安全守卫** — 最大嵌套深度 3 层 (`_MAX_DEPTH`)，per-user 并发上限 3 个 (`_MAX_CONCURRENT_PER_USER`)，超限直接返回错误。
4. **RequestContext** 新增 `subagent_depth` 字段，Gateway `CORE_TOOL_NAMES` 加入新工具名。

### 3.4 Guardian — AI 驱动的风险评估 ✅

**已完成** (2026-03-23): AI 风险评估 hook，高风险工具调用前 LLM 审查。

1. **新增 `agent/guardian.py`** — `GuardianAssessor` 类，对 `run_command`/`write_source_file`/`apply_patch` 三个高风险工具调用 LLM 评估 risk_score (0-100)，非高风险工具直接放行 (不调 LLM)。
2. **fail closed** — LLM 超时/返回非法 JSON/任何异常 → 阻止执行 (安全优先)。
3. **独立 LLM 配置** — 可用更便宜的模型: `guardian_model`/`guardian_base_url`/`guardian_api_key` (空=复用主配置)。
4. **Hook 集成** — `build_default_hooks()` 中在所有规则 Hook 之后注册，规则是第一道防线 (零成本)，Guardian 只评估规则放行的高风险调用。
5. **6 个配置项**: `guardian_enabled` (默认 false) / `guardian_model` / `guardian_base_url` / `guardian_api_key` / `guardian_risk_threshold` (默认 80) / `guardian_timeout_s` (默认 30)。

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

### 4.1 LLM Fallback 模型 ✅

**已完成** (2026-03-22): `LLMGatewayClient` 支持 fallback 模型自动降级。

- `__init__` 新增 `fallback_config: LLMClientConfig | None`，`max_retries=0` (单次尝试)
- `chat_completion()`: 主模型所有重试耗尽后，从错误消息提取 HTTP 状态码 + `classify_error()` 推断类别，仅 MODEL_UNAVAILABLE/OVERLOADED/NETWORK/LLM_ERROR/RATE_LIMIT 触发 fallback；AUTH 等不可恢复错误直接抛出
- `chat_completion_stream()`: 连接级失败 (ConnectError/ConnectTimeout) 时尝试 fallback
- 防止递归 fallback (临时置空 `_fallback_config`)
- `config.py` 新增 `llm_fallback_base_url` / `llm_fallback_api_key` (空=复用主配置)
- `dependencies.py` 当 `llm_fallback_model` 非空时构建 fallback_config
- fallback 成功时 `response.model` 追加 " (fallback)" 标记
- 8 个测试通过

### 4.2 SQLite 并发优化 ✅

**已完成** (2026-03-22): 线程本地连接复用 + PRAGMA 调优。

- `DatabaseService` 和 `UsageService` 改用 `threading.local()` 线程本地连接，同线程复用同一连接
- `_get_conn()` 新建连接时设置 PRAGMA: `busy_timeout=5000` (等待 5s) / `synchronous=NORMAL` (WAL 下安全) / `cache_size=-8000` (8MB) / `temp_store=MEMORY`
- 连接失效自动检测重建 (`SELECT 1` 探活)
- 新增 `close_all()` 方法关闭当前线程连接
- 删除所有方法中的 `conn.close()` (连接保持存活)
- 14 个测试通过

### 4.3 Session 自动过期清理 ✅

**已完成** (2026-03-22): 复制 `_file_cleanup_loop` 模式实现会话自动清理。

- `config.py` 新增 `session_retention_days` (默认 30，0=不清理)
- `SessionManager.cleanup_expired_sessions()` — 遍历 `*.jsonl` 文件，读取首行 metadata 的 `created_at`，超期则删除 JSONL + 同名 .lock 文件。损坏文件跳过不崩溃
- `main.py` lifespan 新增 `_session_cleanup_loop` 后台任务: 启动立即执行一次，之后每 6 小时清理。shutdown 时 cancel
- 7 个测试通过

### 4.4 Token 自动刷新 ✅

**已完成** (2026-03-22): 前端 token 自动刷新。

- `auth.ts` store 新增 `refreshToken()` action，调用 `POST /api/auth/refresh` 更新 token
- 模块级定时器 `_startRefreshTimer()`: 在 token 80% 过期时间点自动刷新 (最低 60s)
- `login` / `restore` 成功后自动启动定时器
- `logout` 自动清除定时器
- 刷新失败自动登出
- `ai-api.ts` `_tryRefreshToken()` 委托给 store 的 `refreshToken()`
- 初始加载时如有有效 token 也自动启动定时器
- 6 个测试通过

### 4.5 管理后台 UI ✅

**已完成** (2026-03-23): 完整管理后台 UI，顶部 Tab 切换对话/管理页面。

1. **后端** — login/register 响应加 `roles` 字段，前端可感知用户角色。
2. **Auth Store** — 新增 `roles: string[]` + `isAdmin: boolean`，login/register/restore 均写入 roles，旧数据自动调 `/api/auth/me` 补全。
3. **App.tsx** — admin 用户顶部显示 [对话] [管理] Tab bar，非 admin 无感知。AdminPage 使用 lazy 加载。
4. **Admin API 层** — `admin-api.ts` 封装 21 个 API 函数 (租户 5 + 用户 4 + API Key 4 + 邀请码 3 + 用量 5)，复用 `apiFetch` 认证逻辑。
5. **五个管理模块**:
   - TenantManager: 租户 CRUD (Table + Modal + Form)
   - UserManager: 用户 CRUD (密码/角色/状态编辑)
   - ApiKeyManager: Key 创建(一次性显示) + 撤销 + 删除
   - InviteCodeManager: 邀请码生成(copyable) + 撤销
   - UsageDashboard: 汇总卡片 + 日明细 + 用户排名 + 工具排名 + 存储用量
6. **超级管理员**: 顶部租户选择器可切换管理任意租户。

### 4.6 用户注册流程 ✅

**已完成** (2026-03-23): 邀请码制用户注册。

1. **invite_codes 表** — `DatabaseService` 新增 `invite_codes` 表 (schema v2 迁移) + `InviteCodeRecord` dataclass + 4 个方法 (create/consume/list/revoke)。消费时原子递增 `used_count`，支持多次使用、过期、撤销。
2. **注册端点** — `POST /api/auth/register` (invite_code + username + password)，校验邀请码 → 创建用户 → 签发 JWT → 返回与 login 相同格式。IP 级速率限制 (5次/5分钟)。
3. **管理员端点** — 3 个端点: 创建邀请码 / 列出邀请码 / 撤销邀请码，复用 API Key 端点模式。
4. **前端** — LoginPage 新增 login/register 模式切换 tab，注册表单含邀请码+用户名+密码+确认密码。auth store 新增 `register()` action。

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
| **第 7 批** | ~~2.3 Tool Search~~ ✅ + ~~2.4 OpenTelemetry~~ ✅ | 全部完成 |
| **第 8 批** | ~~3.1 grep_files/list_dir~~ ✅ + ~~4.1 LLM Fallback~~ ✅ + ~~4.3 Session 清理~~ ✅ | 全部完成 |
| **第 9 批** | ~~4.4 Token 自动刷新~~ ✅ + ~~3.2 Collaboration Mode~~ ✅ + ~~4.2 SQLite 并发优化~~ ✅ | 全部完成 |
| **第 10 批** | ~~3.3 Multi-Agent 增强~~ ✅ + ~~3.4 Guardian~~ ✅ + ~~4.6 用户注册~~ ✅ | Phase 3 全部关闭 |

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
├── 2.3 Tool Search (延迟加载, 阈值30) ✅ (2026-03-22)
└── 2.4 OpenTelemetry (opt-in, NoOp fallback) ✅ (2026-03-22)

Phase 3 (体验提升)        ← 每项 3-5 天，总计约 3 周
├── 3.1 grep_files / list_dir ✅ (2026-03-22)
├── 3.2 Collaboration Mode (plan / execute) ✅ (2026-03-22)
├── 3.3 Multi-Agent 增强 (wait + send + depth/并发 guard) ✅ (2026-03-23)
└── 3.4 Guardian (AI 风险评估，租户可选) ✅ (2026-03-23)

Phase 4 (产品完整性)      ← 项目自身需求，非 Codex 对比
├── 4.1 LLM Fallback 模型 ✅ (2026-03-22)
├── 4.2 SQLite 并发优化 ✅ (2026-03-22)
├── 4.3 Session 自动过期清理 ✅ (2026-03-22)
├── 4.4 Token 自动刷新 ✅ (2026-03-22)
├── 4.5 管理后台 UI ✅ (2026-03-23)
└── 4.6 用户注册流程 (邀请码制) ✅ (2026-03-23)
```
