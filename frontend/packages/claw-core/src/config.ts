/**
 * AI 配置注入 — 宿主应用通过 configureAI() 注入场景数据和回调。
 *
 * 这使 ai-core 包与具体业务场景解耦，任何应用都可以通过此配置注入自己的场景。
 */

import type { ScenarioConfig } from './types/scenario.ts';

export interface AIConfig {
  /** AI 后端 API 基地址 (默认空 = 当前 origin) */
  aiBaseUrl: string;
  /** 默认用户 ID */
  defaultUserId: string;
  /** 场景配置映射 (key → ScenarioConfig) */
  scenarios: Record<string, ScenarioConfig>;
  /** 场景完成后的回调 (替代直接 navigate) */
  onScenarioComplete?: (scenarioKey: string, status: string) => void;
  /** SPA 导航函数 — 由 React Router 注入，避免 window.location.href 硬刷新 */
  navigateFn?: (path: string) => void;
  /** 认证 token — 注入后所有 API 请求自动携带 Authorization header */
  authToken?: string;
  /** 动态获取 token 的函数 (优先于 authToken 静态值) */
  getAuthToken?: () => string | null | Promise<string | null>;
}

let _config: AIConfig = {
  aiBaseUrl: '',
  defaultUserId: 'U001',
  scenarios: {},
};

/** 注入 AI 配置 — 应在应用启动时调用 */
export function configureAI(config: Partial<AIConfig>): void {
  _config = { ..._config, ...config };
}

/** 获取当前 AI 配置 */
export function getAIConfig(): AIConfig {
  return _config;
}

/** 获取所有已注册场景列表 (用于 PromptCards 等) */
export function getAllScenarios(): ScenarioConfig[] {
  return Object.values(_config.scenarios);
}

/** 注入 SPA 导航函数 — 供 React 组件在 Router 上下文中调用 */
export function setNavigate(fn: (path: string) => void): void {
  _config.navigateFn = fn;
}
