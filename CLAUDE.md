# Claw-for-SaaS 内部架构文档

## 项目定位

通用 AI Agent 运行时，可嵌入任意 SaaS 系统。面向 5000 用户的正式产品，非 demo/MVP。
兼容任意 OpenAI API 格式的 LLM（Ollama、vLLM、OpenAI、Azure、Anthropic 等）。

## 技术栈

- **后端**: Python 3.11+ / FastAPI / SQLite / httpx / pydantic-settings
- **前端**: React 19 / TypeScript 5.x / Vite 7 / Tailwind CSS 4 / Ant Design 6 / Zustand 5
- **测试**: pytest (asyncio_mode=auto) / Vitest / Playwright
- **认证**: JWT (HS256) + bcrypt / API Key
- **通信**: WebSocket 实时推送 (替代原 SSE)

## 目录结构

```
backend/
  main.py              — FastAPI 入口 (uvicorn main:app --reload --port 8000)
  config.py            — pydantic-settings 全局配置 (读 .env)
  dependencies.py      — DI 组装中心 (lru_cache 单例)
  prompts/
    soul.md            — Agent 角色定义
    compact_prompt.md  — 上下文压缩交接摘要指令
    compact_prefix.md  — 压缩摘要前缀标记
  agent/
    gateway.py         — AgentGateway: 单一入口处理所有用户请求
    session.py         — JSONL 会话存储 (data/sessions/{tenant}/{user}/{session}.jsonl)
    prompt.py          — 8 层模块化系统提示构建器 (含 per-tenant Soul/Personality 覆盖)
    hooks.py           — Hook 系统 (pre_tool_use / post_tool_use / agent_stop / pre_compact / user_prompt_submit / session_start + inject action)
    hook_rules.py      — 可配置 Hook 规则引擎
    security_hooks.py  — PII 检测 / SSRF 防护等安全 Hook
    subagent.py        — 子 Agent 派发 + 生命周期管理 (start/wait/send + depth/并发控制 + fork 父历史 + registry 缓存)
    guardian.py        — Guardian AI 风险评估 (高风险工具 LLM 审查)
    plan_tracker.py    — 执行计划进度追踪
    quality_gate.py    — 输出质量门控
    safe_eval.py       — 安全表达式求值
    skill_validator.py — Skill YAML 校验
    skill_generator.py — WorkflowAnalyzer: 重复工作流检测 + Skill 建议生成
    pre_compact.py     — 压缩前关键信息保护
  core/
    runtime.py         — AgenticRuntime: ReAct 循环引擎 (核心)
    llm_client.py      — 异步 OpenAI 兼容 LLM 客户端 (httpx + 重试)
    event_bus.py       — 异步事件总线 (asyncio.Queue)
    ws_bridge.py       — EventBus → WebSocket 桥接
    text_utils.py      — 文本处理工具 (smart_truncate head+tail 截断)
    tool_registry.py   — 工具注册表 (schema + 执行 + search_tools + subset)
    tool_protocol.py   — ToolCallParser: 原生 tool_calls + Hermes XML 双模式解析
    context.py         — RequestContext 统一上下文 (含 deferred_tools, subagent_depth, memory_id_map)
    tracing.py         — OpenTelemetry 分布式追踪 (opt-in) + MetricsCollector (counter/histogram)
    sandbox.py         — 文件沙箱 + Docker 沙箱 + symlink TOCTOU 防护
    file_diff_tracker.py — TurnDiffTracker: 单 turn 文件变更追踪
    exec_policy.py     — ExecPolicy: 命令执行安全策略 (三层防御 + per-user 审批持久化)
    tool_orchestrator.py — ToolOrchestrator: 统一工具执行编排 (approval→sandbox→execute→retry)
    secret_redactor.py — SecretRedactor: Secret 输出脱敏
    data_lock.py       — 字段锁定 (防止 Agent 覆盖关键数据)
    token_estimator.py — Token 估算
    scheduler.py       — Cron 定时调度引擎
    webhook.py         — Webhook HMAC 签名回调
    prompt_templates.py — Prompt 模板 CRUD (per-user JSON)
    notification.py    — WebSocket 通知管理
    plugin.py          — 插件系统 (目录加载 + entry_points)
    errors.py          — 错误分类 (RATE_LIMIT/OVERLOADED/NETWORK/CONTEXT_OVERFLOW 等)
    auth.py            — FastAPI 认证依赖
    logging.py         — structlog 日志配置
  api/
    routes.py          — POST /api/chat, GET /api/health, GET /api/tools
    ws_routes.py       — WebSocket /api/ws/notifications
    auth.py            — POST /api/auth/login, /register
    admin.py           — 管理员 API
    session_routes.py  — 会话 CRUD
    file_routes.py     — 文件上传/下载
    memory_routes.py   — 记忆管理 API
    skill_routes.py    — Skill CRUD API
    schedule_routes.py — 定时任务 API
    webhook_routes.py  — Webhook 管理 API
    usage_routes.py    — 管理员用量统计 API
    my_usage_routes.py — 用户自助用量查询
    knowledge_routes.py — 知识库管理
    correction_routes.py — 纠正反馈 API
    hook_rule_routes.py — Hook 规则配置 API
    plugin_routes.py   — 插件管理 API
    sse.py             — SSE 端点 (已迁移到 WebSocket，保留兼容)
  tools/
    registry_builder.py — 工具集组装 (shared + capability + plan + mcp)
    builtin/           — 内置工具 (calculator/file/browser/code/apply_patch/memory/skill/plan/subagent/schedule/interaction/tool_search/search_tools)
    mcp/               — MCP 标准工具接口 (条件注册)
    contrib/            — 社区贡献工具
  skills/
    loader.py          — Skill 加载器 (builtin→plugin→tenant→user 四级优先级)
    builtin/           — 20 个内置 Skill (YAML frontmatter + Markdown)
    tenant/            — 租户级 Skill
    user/              — 用户级 Skill
  memory/
    markdown_store.py  — Markdown 分层笔记 (global/tenant/user 三级 + _meta.json 引用追踪 + 过期清理)
  services/
    database.py        — SQLite 数据库 (tenants/users/api_keys)
    file_service.py    — 文件服务 (上传/下载/过期清理)
    content_processor.py — 文件内容处理 (PDF/DOCX/图片压缩)
    usage_service.py   — 用量统计服务
    knowledge_service.py — 知识库服务 (元数据缓存 + _index.md 自动生成 + search_knowledge)
    batch_service.py   — 批量任务服务 (并发执行 + 汇总)
    browser_service.py — Playwright 浏览器自动化
  models/
    request.py         — API 请求模型
    response.py        — API 响应模型
    usage.py           — 用量数据模型
  plugins/             — 插件目录
  tests/               — 78+ 测试文件
  data/                — 运行时数据 (gitignored)

frontend/
  package.json         — npm workspaces 根 (packages/* + app)
  packages/
    claw-core/         — @claw/core: 状态管理 + 服务 + Hook
      src/
        config.ts      — configureAI() 场景配置注入
        stores/
          ai-chat.ts   — 对话状态 (Zustand)
          pipeline.ts  — Pipeline 状态
          auth.ts      — 认证状态 (含 roles/isAdmin)
          session-status.ts — 会话状态
          pipeline-cache.ts — 会话快照缓存
        hooks/
          useAIChat.ts — 对话 Hook (组合 useChatMessages + useSessionManager)
          useChatMessages.ts — 消息状态 + streaming 效果
          useSessionManager.ts — Session CRUD + 切换 + cache + F5 保护
          usePipeline.ts — Pipeline Hook
          useNotifications.ts — WebSocket 通知 Hook
        services/
          ai-api.ts    — 后端 API 调用
          pipeline-dispatcher.ts — Pipeline 事件分发
        types/
          pipeline.ts  — Pipeline 类型定义
          scenario.ts  — 场景配置类型
    claw-ui/           — @claw/ui: UI 组件库
      src/
        AIChatDialog.tsx     — 主对话窗口
        ClawFloatingButton.tsx — 悬浮按钮入口
        chat/                — 对话相关组件 (消息列表/输入框/进度面板/搜索/Sidebar)
        results/             — 结果展示组件 (审计/文档/Diff/类型推断)
        schedule/            — 定时任务 UI
        skills/              — Skill 管理 UI
        knowledge/           — 知识库管理 UI
        preview/             — 文件预览组件
        shared/              — 共享组件 (代码高亮/Markdown 渲染)
  app/                 — 示例宿主应用
    src/
      App.tsx          — 入口 (顶部 Tab 切换对话/管理 + LoginPage)
      LoginPage.tsx    — 登录页
      admin/
        AdminPage.tsx      — 管理后台主页 (租户选择器 + Tabs)
        TenantManager.tsx  — 租户 CRUD
        UserManager.tsx    — 用户 CRUD
        ApiKeyManager.tsx  — API Key 管理
        InviteCodeManager.tsx — 邀请码管理
        UsageDashboard.tsx — 用量统计面板
        admin-api.ts       — Admin API 调用层 (21 个函数)
    vite.config.ts     — dev server port 3001, proxy /api → localhost:8000
```

## 核心架构

### 请求流程

```
用户消息 → POST /api/chat
  → AgentGateway.chat()
    → 构建 RequestContext + 设置 ContextVars (tenant/user/session/sandbox/...)
    → 创建/恢复 Session (JSONL)
    → 获取 session 级文件锁 (fcntl.flock, 跨 worker 互斥)
    → 加载 Skills + Memory + 知识库索引
    → 构建 8 层 System Prompt
    → 构建 User Message (含 materials/多模态)
    → 创建 AgenticRuntime → run()
      → ReAct 循环 (最多 25 轮)
        → 上下文预算检查 + 四阶段压缩
        → 流式调用 LLM (httpx SSE)
        → 解析 tool_calls (原生 + Hermes XML)
        → 执行工具 (只读并行 / 写入串行)
        → Hook 链: pre_tool_use → execute → post_tool_use
        → 重复检测 + 无意义输出检测
        → Quality Gate (agent_stop hook)
        → 直到 final_answer 或 max_iterations
    → 持久化消息 + Timeline
    → 自动提取记忆 (auto-learning.md)
    → 记忆引用追踪 ([mem:ID] → increment_usage)
    → 工作流指纹记录 + Skill 建议 (skill_suggestion 事件)
    → 记录用量 (SQLite)
  → EventBus → WSBridge → WebSocket 推送到前端
```

### 8 层提示词架构

| 层级 | 名称 | 内容 |
|:-----|:-----|:-----|
| L0 | IDENTITY | `<identity>Claw AI Agent Runtime</identity>` |
| L1 | SOUL | prompts/soul.md (角色定义 + 工具使用规则) |
| L2 | SAFETY | 10 条安全约束 |
| L3 | TOOLS | `<tools>` XML 按 read_only 分组 |
| L4 | SKILLS | `<skills>` 领域知识索引 + 按需加载 |
| L5 | MEMORY | `<memory>` 三级记忆 (global/tenant/user, 段落带 [mN] ID, 按 usage_count 排序) |
| L5b | KNOWLEDGE | `<knowledge>` 知识库 _index.md |
| L6 | RUNTIME | user_id / session_id / timestamp / workspace_dir / timezone / platform |
| L7 | EXTRA | plan_guidance + 插件自定义 |

### 四阶段上下文压缩

1. **工具结果压缩** — 截断旧 tool 结果，保留工具名+状态+关键数值
2. **对话摘要** — LLM 生成结构化交接文档 (prompts/compact_prompt.md 指导，fallback: 启发式截取)
3. **元数据模式** — 只保留 system + 最近 4 条 + 摘要
4. **逐条删除** — 逐条删最旧非系统消息直到 fit

### 通信协议

- **HTTP**: POST /api/chat 发起对话 → 返回 `{session_id, trace_id}`
- **WebSocket**: `/api/ws/notifications` 全局通知通道
  - 服务端通过 EventBusWSBridge 将 pipeline 事件推送到用户 WS 连接
  - 事件类型: pipeline_started, text_delta, thinking, tool_executed, agent_progress, plan_proposed, step_started/completed/failed, agent_message, pipeline_complete, skill_suggestion, error 等
  - 心跳: 客户端 ping → 服务端 pong (60s 超时)

## 开发命令

```bash
# 后端
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000  # 或 python main.py

# 前端
cd frontend
npm install
cd app && npm run dev                   # dev server at http://localhost:3001

# 测试
cd backend && python -m pytest          # 后端单元测试
cd frontend && npm run test:unit        # 前端单元测试
cd frontend && npm run test:e2e         # E2E 测试 (Playwright)
```

## 环境配置

通过 `.env` 文件或环境变量配置 (pydantic-settings, case_sensitive=False):

**必须配置**:
- `LLM_MODEL` — LLM 模型名称
- `LLM_BASE_URL` — LLM API 地址 (默认 http://localhost:11434/v1)

**认证** (生产环境必须):
- `AUTH_ENABLED=True`
- `AUTH_JWT_SECRET` — JWT 密钥 (auth_enabled=True 时必须设置)

**常用可选**:
- `LLM_API_KEY` — API Key (本地模型不需要)
- `LLM_SUPPORTS_VISION` — 是否支持图片输入
- `LLM_ENABLE_THINKING` — 启用思考模式 (vLLM thinking)
- `LLM_FALLBACK_MODEL` — Fallback 模型名 (空=不启用)
- `LLM_FALLBACK_BASE_URL` — Fallback LLM API 地址 (空=复用主地址)
- `LLM_FALLBACK_API_KEY` — Fallback API Key (空=复用主 key)
- `SESSION_RETENTION_DAYS` — 会话 JSONL 保留天数 (默认 30, 0=不清理)
- `AGENT_MODEL_CONTEXT_WINDOW` — 模型上下文窗口大小 (默认 32000)
- `AGENT_MAX_ITERATIONS` — ReAct 最大迭代数 (默认 25)
- `MCP_ENABLED` — 启用 MCP 工具接口
- `SCHEDULER_ENABLED` — 启用定时调度 (默认 true)
- `SANDBOX_DOCKER_ENABLED` — 启用 Docker 沙箱
- `SANDBOX_WRITABLE_ROOTS` — 沙箱可写子目录 (逗号分隔，空=整个 workspace 可写)
- `AGENT_TOOL_DEFERRED_THRESHOLD` — 工具延迟加载阈值 (默认 30)
- `OTEL_ENABLED` — 启用 OpenTelemetry 追踪 (默认 false)
- `OTEL_ENDPOINT` — OTLP gRPC 端点 (默认 http://localhost:4317)
- `OTEL_SERVICE_NAME` — OTel 服务名 (默认 claw-for-saas)
- `APP_DEBUG` — 启用 debug/reload 模式
- `GUARDIAN_ENABLED` — 启用 Guardian AI 风险评估 (默认 false)
- `GUARDIAN_MODEL` — Guardian LLM 模型名 (空=复用主模型)
- `GUARDIAN_BASE_URL` — Guardian LLM API 地址 (空=复用主地址)
- `GUARDIAN_API_KEY` — Guardian LLM API Key (空=复用主 key)
- `GUARDIAN_RISK_THRESHOLD` — 风险评分阈值 (默认 80, 0-100)
- `GUARDIAN_TIMEOUT_S` — Guardian LLM 超时秒数 (默认 30)
- `LLM_FALLBACK_CONTEXT_WINDOW` — Fallback 模型上下文窗口 (0=与主模型相同，小于主模型时自动使用较小值)
- `MEMORY_RETENTION_DAYS` — 记忆条目过期天数 (默认 30, 0=不清理, 仅清理 usage_count==0)
- `MEMORY_WORKFLOW_TRACKING_ENABLED` — 启用工作流指纹追踪 (默认 true)
- `MEMORY_WORKFLOW_REPEAT_THRESHOLD` — 工作流重复触发 Skill 建议的阈值 (默认 3)

## 开发注意事项

- 后端代码改完必须自己重启服务 (`uvicorn --reload` 只覆盖 Python 文件变更)
- Zustand 恢复历史数据用 `setState` 不用 action；快照只恢复真正丢失的数据
- 修 bug 时先验证代码生效再改下一处；注意 action 可能有隐藏副作用
- 准确性优先于速度，不要急于修改未充分验证的代码
- 分支分配由用户决定，不要自己建分支
- 用中文沟通

## 数据持久化

| 数据 | 存储 | 路径 |
|:-----|:-----|:-----|
| 租户/用户/API Key | SQLite | data/claw.db |
| 会话消息 | JSONL (append-only) | data/sessions/{tenant}/{user}/{session}.jsonl |
| 用户记忆 | Markdown (三级) + _meta.json | data/memory/{global,tenant,user}/ |
| 工作流日志 | JSON | data/memory/user/{tenant}/{user}/_workflow_log.json |
| 上传文件 | 文件系统 | data/files/ |
| 知识库 | 文件系统 | data/knowledge/ |
| 定时任务 | JSON | data/schedules/{tenant}/{user}/tasks.json |
| Webhook | JSON | data/webhooks/ |
| Hook 规则 | JSON | data/hook_rules/ |
| 用量统计 | SQLite | data/claw.db (usage 表) |
| 命令审批 | JSON | data/exec_approvals/{tenant}/{user}.json |
| 工作空间 | 文件系统 (沙箱) | data/workspace/ |

## 内置工具列表

**只读 (可并行)**:
- calculator: numeric_compare, sum_values, calculate_ratio, arithmetic, date_diff
- skill_reference: read_reference (read_skill)
- file: read_uploaded_file, list_user_files, analyze_file, read_knowledge_file, search_knowledge
- browser: open_url, page_screenshot, page_extract_text
- code: read_source_file
- memory: recall_memory, search_memory
- tool_search: tool_search (BM25 延迟搜索), tool_suggest (任务描述→推荐工具)
- search_tools: grep_files, list_dir (工作空间文件搜索/目录列出)

**能力 (串行执行)**:
- code: write_source_file, apply_patch, run_command
- memory: save_memory
- skill: create_skill, update_skill
- plan: propose_plan, update_plan_step
- subagent: spawn_subagent, spawn_subagents, wait_subagent, send_to_subagent
- schedule: create_schedule, list_schedules, delete_schedule
- interaction: request_user_input, request_permissions
- mcp (条件注册): get_form_schema, get_business_rules, get_candidate_types, get_protected_values, submit_form_data, query_data

## Hook 系统

六类事件:
- `pre_tool_use` — 工具调用前检查 (可 block/modify/inject developer instructions)
- `post_tool_use` — 工具调用后审计
- `agent_stop` — Agent 完成前质量门控 (可 block 触发自我纠正)
- `pre_compact` — 压缩前保护关键信息
- `user_prompt_submit` — 用户消息提交时触发
- `session_start` — 新会话创建时触发

内置安全 Hook: PII 检测、SSRF DNS 检查、路径穿越防护 + symlink TOCTOU 防护、速率限制、ExecPolicy 三层命令防御 (复合命令拆分+CommandRule 规则表+管道末端检查 + per-user 审批持久化)、apply_patch 敏感文件检查、Guardian AI 风险评估 (可选，含对话上下文注入)、SecretRedactor (GitHub/GitLab/Google/Slack/npm 等 10+ 模式)。安全阻止消息附 request_permissions 工具提示。

## 插件系统

两种加载方式:
1. 目录加载: `plugins/` 目录下 Python 模块
2. Entry Points: `claw.plugins` entry_points

PluginContext 四维扩展点: tool_registry / hook_registry / prompt_builder / skill_loader
