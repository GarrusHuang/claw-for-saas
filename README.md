# Claw-for-SaaS

通用 AI Agent 运行时，可嵌入任意 SaaS 系统。基于 [OpenClaw](https://github.com/openclaw/openclaw) 设计模式。

## 架构

```
┌─────────────────────────────────────────────────────────┐
│  SaaS Application (host)                                │
│  ┌───────────────┐  ┌────────────────┐                  │
│  │ @claw/core    │  │ @claw/ui       │  ← npm packages  │
│  │ state/hooks   │  │ chat components│                  │
│  └───────┬───────┘  └────────┬───────┘                  │
│          └────────┬──────────┘                          │
│                   ▼                                     │
│          POST /api/chat (SSE)                           │
├─────────────────────────────────────────────────────────┤
│  Claw Backend                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ Gateway  │→ │ Runtime  │→ │ Tools    │              │
│  │ (entry)  │  │ (ReAct)  │  │ (35 个)  │              │
│  └──────────┘  └──────────┘  └──────────┘              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ Prompt   │  │ Memory   │  │ Hooks    │              │
│  │ (8-layer)│  │ (3-layer)│  │ (4-point)│              │
│  └──────────┘  └──────────┘  └──────────┘              │
└─────────────────────────────────────────────────────────┘
```

## 核心能力

| 能力 | 说明 |
|------|------|
| **ReAct 循环** | 最多 25 轮迭代，三阶段渐进上下文压缩 |
| **35 个内置工具** | 计算 / 文件 / 知识库 / 浏览器 / 代码 / 记忆 / 技能 / 子 Agent / 定时任务 |
| **流式 SSE** | POST-based SSE，15+ 事件类型，实时流式输出 |
| **三层记忆** | global / tenant / user Markdown 分层笔记，对话自动保存 |
| **8 层提示词** | Identity → Soul → Safety → Tools → Skills → Memory → Runtime → Extra |
| **Hook 系统** | pre_tool_use / post_tool_use / agent_stop / pre_compact |
| **运行时围栏** | 文件沙箱 + 命令黑名单 + 网络白名单 + 速率限制 + 数据锁定 |
| **知识库** | global / user 双层知识库，Agent 可读写，支持全格式文件 |
| **文件预览** | DOCX / PDF / Excel / 图片 / HTML / 代码 / Markdown 全格式预览 |
| **19 个 Skills** | 合同 / 报销 / 审计 / 文件分析 / 文档生成 等领域知识 |

## 技术栈

- **Backend**: Python 3.11+ / FastAPI / Pydantic v2 / httpx
- **Frontend**: React 19 / TypeScript / Vite 7 / Ant Design 6 / Zustand
- **LLM**: 任意 OpenAI 兼容 API（默认 Ollama）

## 快速开始

### 1. 后端

```bash
cd backend
pip install -r requirements.txt

# 配置 .env
cat > .env << 'EOF'
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=your_model_name
LLM_API_KEY=not-needed
EOF

uvicorn main:app --reload --port 8000
```

### 2. 前端

```bash
cd frontend
npm install
cd app && npx vite    # http://localhost:3001
```

### 3. 访问

打开 http://localhost:3001 ，默认账号 `admin` / `admin123`。

## 项目结构

```
claw-for-saas/
├── backend/
│   ├── core/               # Agent 引擎 (runtime, tools, llm, events)
│   ├── agent/              # Gateway + 编排 (prompt, session, hooks)
│   ├── memory/             # 三层 Markdown 记忆
│   ├── tools/builtin/      # 29 个内置工具
│   ├── tools/mcp/          # MCP 标准工具接口
│   ├── skills/builtin/     # 19 个内置 Skills
│   ├── services/           # 文件 / 知识库 / 浏览器 / 用量统计
│   ├── api/                # FastAPI 路由
│   ├── prompts/soul.md     # Agent 角色定义
│   └── config.py           # 全局配置
├── frontend/
│   ├── packages/
│   │   ├── claw-core/      # @claw/core (状态/服务/Hook)
│   │   └── claw-ui/        # @claw/ui (Chat/Schedule/Skills/Knowledge/Preview)
│   └── app/                # 独立 SPA
└── docs/                   # 设计文档 + 参考图
```

## SaaS 集成

### 方式 1: 独立部署

直接部署 `frontend/app/` + `backend/`，开箱即用。

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

| 扩展方式 | 说明 |
|----------|------|
| 自定义工具 | `@registry.tool()` 装饰器注册 |
| 自定义 Soul | 替换 `prompts/soul.md` |
| 自定义 Skill | 放入 `skills/` 目录 (YAML frontmatter + Markdown) |
| 自定义 Hook | `HookRegistry.register()` 或 Hook Rule CRUD API |
| BusinessContext | 请求中传入 opaque dict，自动序列化为 XML |

## API 端点

| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/chat` | Agent SSE 流式对话 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/tools` | 列出已注册工具 |
| GET/POST/PUT/DELETE | `/api/skills/*` | Skill CRUD |
| GET/DELETE | `/api/session/*` | 会话管理 (列表/搜索/详情/删除) |
| POST | `/api/files/upload` | 文件上传 (支持 session_id 绑定) |
| GET/POST/DELETE | `/api/knowledge/*` | 知识库管理 (6 端点) |
| GET | `/api/workspace/{session_id}/files/*` | Workspace 文件 (预览/下载) |
| GET/POST/PUT/DELETE | `/api/schedules/*` | 定时任务 |
| GET/POST/DELETE | `/api/webhooks/*` | Webhook 配置 |
| GET | `/api/admin/usage/*` | 管理员用量统计 |
| GET | `/api/usage/me/*` | 自助用量查询 |

## 测试

```bash
# 后端 (1675 unit + 26 LLM = 1701 tests)
cd backend && python3 -m pytest tests/ -v

# 前端 (162 tests)
cd frontend && npm test
```

## 配置

通过环境变量或 `.env` 文件:

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_BASE_URL` | `http://localhost:11434/v1` | LLM API 地址 |
| `LLM_MODEL` | `your_model_name` | 模型名称 |
| `LLM_API_KEY` | `not-needed` | API Key |
| `AGENT_MAX_ITERATIONS` | `25` | ReAct 最大迭代 |
| `AGENT_MODEL_CONTEXT_WINDOW` | `32000` | 模型上下文窗口 |
| `MCP_ENABLED` | `False` | 启用 MCP 工具 |
| `SCHEDULER_ENABLED` | `True` | 启用定时调度 |
| `LLM_SUPPORTS_VISION` | `False` | 启用多模态 |
| `MAX_FILE_UPLOAD_MB` | `100` | 文件上传大小限制 (MB) |
| `FILE_RETENTION_DAYS` | `7` | 会话文件保留天数 (0=不清理) |

完整配置项见 `backend/config.py`。

## License

Internal use only.
