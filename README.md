<div align="center">

# Claw-for-SaaS

**通用 AI Agent 运行时，可嵌入任意 SaaS 系统**

基于 [OpenClaw](https://github.com/openclaw/openclaw) 设计模式 · ReAct 循环引擎 · 流式 SSE · 多层记忆 · 全链路 Hook

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.x-3178C6?logo=typescript&logoColor=white)](https://typescriptlang.org)
[![Tests](https://img.shields.io/badge/Tests-1884_passed-brightgreen?logo=pytest&logoColor=white)](#测试)
[![License](https://img.shields.io/badge/License-Internal-lightgrey)](#license)

</div>

---

## 为什么选 Claw？

大多数 AI 集成方案只是 "套壳 ChatGPT"——单轮调用、无状态、工具能力受限。Claw 提供的是一个**完整的 Agent 执行引擎**：

- **多轮自主推理** — ReAct 循环最多 25 轮迭代，Agent 自主规划、调用工具、验证结果
- **即插即用** — 注册自定义工具只需一个装饰器，注入自定义 Soul 只需替换一个 Markdown 文件
- **生产级可靠** — 三阶段上下文压缩、运行时沙箱、速率限制、SSRF 防护、PII 检测
- **零 vendor lock-in** — 兼容任意 OpenAI API 格式的 LLM（Ollama、vLLM、OpenAI、Azure、Anthropic…）

---

## 核心特性

| 特性 | 说明 |
|:-----|:-----|
| **ReAct 循环引擎** | 最多 25 轮 Thought → Action → Observation 迭代，支持并行工具调用 |
| **35 个内置工具** | 计算 · 文件 · 知识库 · 浏览器 · 代码执行 · 记忆 · 技能 · 子 Agent · 定时任务 |
| **8 层提示词架构** | Identity → Soul → Safety → Tools → Skills → Memory → Runtime → Extra |
| **三层 Markdown 记忆** | global / tenant / user 分层笔记，Agent 自主读写，跨会话持久化 |
| **20 个领域 Skill** | 合同 · 报销 · 审计 · 文件分析 · 文档生成等，YAML frontmatter + Markdown |
| **流式 SSE** | POST-based SSE，15+ 事件类型，实时展示思考过程和工具执行 |
| **运行时安全围栏** | 文件沙箱 · 命令黑名单 · 网络白名单 · 速率限制 · 数据锁定 · PII 检测 |
| **MCP 标准工具接口** | 可选启用，6 个标准工具，支持 HTTP 转发到宿主系统 |
| **定时调度 + Webhook** | Cron 定时任务 · 一次性任务 · Webhook HMAC 签名回调 |
| **全格式文件预览** | DOCX · PDF · Excel · 图片 · HTML · 代码 · Markdown |
| **用量统计** | SQLite 持久化，管理员看板 + 用户自助查询 |
| **多模态支持** | 可选启用图片/PDF 视觉理解（需模型支持） |

---

## 架构

```
┌──────────────────────────────────────────────────────────────┐
│  SaaS Application (宿主系统)                                  │
│                                                              │
│  ┌──────────────┐   ┌──────────────┐                         │
│  │  @claw/core  │   │  @claw/ui    │    ← npm packages       │
│  │  状态 / Hook  │   │  Chat 组件   │                         │
│  └──────┬───────┘   └──────┬───────┘                         │
│         └───────┬──────────┘                                 │
│                 ▼                                            │
│        POST /api/chat (SSE)                                  │
├──────────────────────────────────────────────────────────────┤
│  Claw Backend                                                │
│                                                              │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐                 │
│  │ Gateway  │ → │ Runtime  │ → │  Tools   │                 │
│  │  入口     │   │  ReAct   │   │  35 个   │                 │
│  └──────────┘   └──────────┘   └──────────┘                 │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐                 │
│  │ Prompt   │   │ Memory   │   │  Hooks   │                 │
│  │  8 层     │   │  3 层     │   │  4 类     │                 │
│  └──────────┘   └──────────┘   └──────────┘                 │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐                 │
│  │ Sandbox  │   │ Scheduler│   │  Skills  │                 │
│  │  安全围栏  │   │  定时调度  │   │  20 个   │                 │
│  └──────────┘   └──────────┘   └──────────┘                 │
└──────────────────────────────────────────────────────────────┘
```

---

## 快速开始

### 前置条件

- Python 3.11+
- Node.js 20+
- 一个 OpenAI 兼容的 LLM 服务（推荐 [Ollama](https://ollama.com) 本地部署）

### 1. 启动后端

```bash
cd backend
pip install -r requirements.txt

# 创建 .env 配置
cat > .env << 'EOF'
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5:14b
LLM_API_KEY=not-needed
EOF

uvicorn main:app --reload --port 8000
```

### 2. 启动前端

```bash
cd frontend
npm install
cd app && npx vite    # → http://localhost:3001
```

### 3. 开始使用

打开 http://localhost:3001 ，默认账号 `admin` / `admin123`。

### Docker 部署

```bash
docker compose up -d
# 后端: http://localhost:8000
# 前端: http://localhost:3001
```

---

## 项目结构

```
claw-for-saas/
├── backend/
│   ├── core/               # Agent 引擎 (runtime, tools, llm, events, sandbox, scheduler)
│   ├── agent/              # Gateway + 编排 (prompt, session, hooks, subagent, quality_gate)
│   ├── memory/             # 三层 Markdown 记忆 (global/tenant/user)
│   ├── tools/
│   │   ├── builtin/        # 29 个内置工具
│   │   └── mcp/            # MCP 标准工具接口
│   ├── skills/builtin/     # 20 个内置 Skill
│   ├── services/           # 文件 / 知识库 / 浏览器 / 用量统计
│   ├── models/             # Pydantic 请求/响应模型
│   ├── api/                # FastAPI 路由 (15 个模块)
│   ├── prompts/soul.md     # Agent 角色定义 (可替换)
│   ├── config.py           # 全局配置 (50+ 参数)
│   └── main.py             # FastAPI 入口
├── frontend/
│   ├── packages/
│   │   ├── claw-core/      # @claw/core — 状态管理 / 服务层 / Hook
│   │   └── claw-ui/        # @claw/ui — Chat / Schedule / Skills / Knowledge / Preview
│   └── app/                # 独立 SPA (Vite + React 19)
└── docs/                   # ROADMAP + 设计文档
```

---

## SaaS 集成

### 方式 1: 独立部署

直接部署 `frontend/app/` + `backend/`，开箱即用的 AI Agent 平台。

### 方式 2: 嵌入宿主系统

```bash
npm install @claw/core @claw/ui
```

```tsx
import { configureAI } from '@claw/core';
import { AIChatDialog, ClawFloatingButton } from '@claw/ui';

configureAI({
  aiBaseUrl: '/api',
  defaultUserId: currentUser.id,
});

function MyPage() {
  return (
    <>
      <MyBusinessForm />
      <AIChatDialog />
      <ClawFloatingButton />
    </>
  );
}
```

### 扩展点

| 扩展方式 | 做什么 | 怎么做 |
|:---------|:-------|:-------|
| **自定义工具** | 给 Agent 新能力 | `@registry.tool()` 装饰器，通过 `build_gateway()` 注入 |
| **自定义 Soul** | 改变 Agent 角色和行为 | 替换 `prompts/soul.md` |
| **自定义 Skill** | 注入领域知识 | 放入 `skills/` 目录，YAML frontmatter + Markdown body |
| **自定义 Hook** | 拦截/审计工具调用 | `HookRegistry.register()` 或 Hook Rule CRUD API |
| **Quality Gate** | 业务校验 Agent 输出 | 注册 `agent_stop` hook |
| **BusinessContext** | 传入业务上下文 | 请求中传入 opaque dict，prompt builder 自动序列化为 XML |

---

## API 概览

<details>
<summary><b>完整 API 端点列表（30+ 端点）</b></summary>

| Method | Path | 说明 |
|:-------|:-----|:-----|
| **核心** | | |
| POST | `/api/chat` | Agent SSE 流式对话 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/tools` | 已注册工具列表 |
| **会话** | | |
| GET | `/api/session/list` | 用户会话列表 |
| GET | `/api/session/search?q=` | 搜索会话 |
| GET | `/api/session/{id}` | 会话历史 |
| DELETE | `/api/session/{id}` | 删除会话 |
| **文件** | | |
| POST | `/api/files/upload` | 文件上传 |
| GET | `/api/workspace/{session_id}/files/*` | Workspace 文件预览/下载 |
| **知识库** | | |
| POST | `/api/knowledge/upload` | 上传知识库文件 |
| GET/DELETE | `/api/knowledge/{file_id}` | 知识库 CRUD |
| **Skill** | | |
| GET/POST/PUT/DELETE | `/api/skills/*` | Skill CRUD |
| POST | `/api/skills/import` | 导入 Skill |
| **定时任务** | | |
| GET/POST | `/api/schedules` | 定时任务列表/创建 |
| GET/PUT/DELETE | `/api/schedules/{id}` | 定时任务详情/更新/删除 |
| POST | `/api/schedules/{id}/pause` | 暂停 |
| POST | `/api/schedules/{id}/resume` | 恢复 |
| **Webhook** | | |
| GET/POST/DELETE | `/api/webhooks` | Webhook CRUD |
| POST | `/api/webhooks/test` | 发送测试 |
| **用量统计** | | |
| GET | `/api/admin/usage/tenant/{id}/*` | 管理员用量看板（7 端点） |
| GET | `/api/usage/me/*` | 自助用量查询（3 端点） |
| **其他** | | |
| GET/POST | `/api/corrections/*` | 修正记忆 |
| GET/POST/PUT/DELETE | `/api/hook-rules/*` | Hook 规则 |

</details>

---

## SSE 事件流

Agent 运行时通过 SSE 实时推送以下事件：

```
pipeline_started   → 会话开始
agent_progress     → 迭代进度 (iteration, phase)
text_delta         → 流式文本输出 (逐 chunk)
thinking           → Agent 思考过程
plan_proposed      → 执行计划
step_started       → 步骤开始
step_completed     → 步骤完成
tool_executed      → 工具执行结果
pipeline_complete  → 会话结束 (duration, summary)
error              → 错误 (category, recoverable, suggested_action)
request_upload     → Agent 请求用户上传文件
request_input      → Agent 请求用户输入
```

---

## 配置

通过环境变量或 `.env` 文件配置，完整参数 50+，以下为常用项：

| 变量 | 默认值 | 说明 |
|:-----|:-------|:-----|
| `LLM_BASE_URL` | `http://localhost:11434/v1` | LLM API 地址 |
| `LLM_MODEL` | *(必填)* | 模型名称 |
| `LLM_API_KEY` | `not-needed` | API Key（本地模型可留空） |
| `AGENT_MAX_ITERATIONS` | `25` | ReAct 最大迭代轮数 |
| `AGENT_MODEL_CONTEXT_WINDOW` | `32000` | 模型上下文窗口 |
| `AUTH_ENABLED` | `False` | 启用 JWT 认证 |
| `MCP_ENABLED` | `False` | 启用 MCP 标准工具 |
| `SCHEDULER_ENABLED` | `True` | 启用定时调度 |
| `LLM_SUPPORTS_VISION` | `False` | 启用多模态 |
| `SANDBOX_MAX_DISK_QUOTA_MB` | `500` | 单用户磁盘配额 |
| `MAX_FILE_UPLOAD_MB` | `100` | 文件上传大小限制 |

完整配置项见 [`backend/config.py`](backend/config.py)。

---

## 测试

```bash
# 后端单元测试（1675 用例）
cd backend && python3 -m pytest tests/ -m "not llm" -v

# 后端 + LLM 集成测试（1701 用例，需 LLM 服务在线）
cd backend && python3 -m pytest tests/ -v

# 前端单元测试（162 用例）
cd frontend && npm test

# 前端 E2E（21 用例）
cd frontend && npx playwright test
```

| 层级 | 测试数 | 覆盖范围 |
|:-----|:-------|:---------|
| 后端 Unit | 1,675 | 59 文件 · Core / Agent / Memory / Tools / Skills / API / Services |
| 后端 LLM 集成 | 26 | 多工具并行 · 上下文压缩 · 子 Agent · Gateway 全链路 |
| 前端 Unit | 162 | claw-core (73) · claw-ui (83) · app (6) |
| 前端 E2E | 21 | Playwright 关键用户流程 |
| **合计** | **1,884** | |

---

## 技术栈

| 层 | 技术 |
|:---|:-----|
| **Backend** | Python 3.11+ · FastAPI · Pydantic v2 · httpx · structlog · SQLite |
| **Frontend** | React 19 · TypeScript 5 · Vite 7 · Ant Design 6 · TailwindCSS v4 · Zustand |
| **LLM** | 任意 OpenAI 兼容 API（Ollama · vLLM · OpenAI · Azure · Anthropic） |
| **Testing** | pytest · Vitest · Playwright |

---

## 开发文档

| 文档 | 说明 |
|:-----|:-----|
| [`backend/CLAUDE.md`](backend/CLAUDE.md) | 后端架构详解 — ReAct 循环、工具系统、Hook、安全 |
| [`frontend/CLAUDE.md`](frontend/CLAUDE.md) | 前端架构详解 — 组件、状态管理、SSE 集成 |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | 20 Phase 开发路线图 (A1-A15 后端 + F1-F5 前端) |

---

## License

Internal use only.
