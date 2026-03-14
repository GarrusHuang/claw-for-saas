/**
 * WebSocket 通知 Hook — 连接后端全局推送通道。
 *
 * 处理 pipeline_event 事件:
 * - 当前活跃 session: 通过 dispatcher 更新 store → UI 实时刷新
 * - 非活跃 session: 静默更新缓存 + 追踪未读状态
 */

import { useEffect, useRef, useCallback } from 'react';
import { getAIConfig } from '../config.ts';
import { usePipelineStore } from '../stores/pipeline.ts';
import { useSessionStatusStore } from '../stores/session-status.ts';
import { dispatchPipelineEvent } from '../services/pipeline-dispatcher.ts';
import { fetchRunningSessions } from '../services/ai-api.ts';

export type NotificationHandler = (event: { type: string; data: Record<string, unknown> }) => void;

/**
 * 连接 WebSocket 通知通道，接收服务端推送。
 *
 * @param onNotification - 收到通知时的回调 (非 pipeline_event 类型)
 * @param enabled - 是否启用 (默认 true)
 */
export function useNotifications(onNotification: NotificationHandler, enabled = true): void {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const handlerRef = useRef(onNotification);
  handlerRef.current = onNotification;

  const connect = useCallback(() => {
    if (!enabled) return;

    const config = getAIConfig();
    const baseUrl = config.aiBaseUrl || window.location.origin;

    // HTTP → WS protocol
    const wsBase = baseUrl.replace(/^http/, 'ws');

    // Get auth token
    let token = '';
    if (config.getAuthToken) {
      token = config.getAuthToken() || '';
    } else if (config.authToken) {
      token = config.authToken;
    }

    const url = `${wsBase}/api/ws/notifications${token ? `?token=${encodeURIComponent(token)}` : ''}`;

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        // 首次连接 or 重连：拉取运行中的 session 列表恢复蓝点
        fetchRunningSessions()
          .then((ids) => {
            for (const id of ids) {
              useSessionStatusStore.getState().addRunning(id);
            }
          })
          .catch(() => {});

        // 连接成功，启动心跳
        const pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send('ping');
          } else {
            clearInterval(pingInterval);
          }
        }, 30_000);

        ws.addEventListener('close', () => clearInterval(pingInterval));
      };

      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          // 忽略 pong/ping 心跳
          if (msg.type === 'pong' || msg.type === 'ping') return;

          // ── Pipeline 事件路由 ──
          if (msg.type === 'pipeline_event') {
            const payload = msg.data as Record<string, unknown>;
            const sessionId = payload.session_id as string;
            const eventType = payload.event_type as string;
            const eventData = (payload.data as Record<string, unknown>) || {};

            const currentSessionId = usePipelineStore.getState().sessionId;
            const storeStatus = usePipelineStore.getState().status;

            // 判断是否属于当前活跃 session:
            // 1. session_id 完全匹配
            // 2. store 正在 running 且 sessionId 为 null (新建会话，POST 返回前后端还没分配 session_id)
            //    + trace_id 匹配 (避免多 tab 竞态)
            const storeTraceId = usePipelineStore.getState().traceId;
            const isActiveSession =
              sessionId === currentSessionId ||
              (!currentSessionId && storeStatus === 'running' &&
               (!storeTraceId || eventData.trace_id === storeTraceId));

            if (isActiveSession) {
              // 当前活跃 session → 直接更新 store
              // 如果 store 还没有 sessionId，从事件中捕获
              if (!currentSessionId && sessionId) {
                usePipelineStore.getState().setSessionId(sessionId);
                useSessionStatusStore.getState().addRunning(sessionId);
              }
              dispatchPipelineEvent(eventType, eventData);
              // 活跃 session 完成/出错时也要清理 runningIds
              if (eventType === 'pipeline_complete' || eventType === 'error') {
                useSessionStatusStore.getState().removeRunning(sessionId);
              }
            } else {
              // 非活跃 session → 追踪状态
              if (eventType === 'pipeline_complete' || eventType === 'error') {
                useSessionStatusStore.getState().removeRunning(sessionId);
                useSessionStatusStore.getState().addUnread(sessionId);
              } else if (eventType !== 'keepalive' && eventType !== 'heartbeat') {
                // 任何非终结事件都说明该 session 还在跑
                // (F5 后 pipeline_started 不会重发，靠中途事件恢复 runningIds)
                useSessionStatusStore.getState().addRunning(sessionId);
              }
            }
            return;
          }

          // 其他通知类型 → 传递给外部回调
          handlerRef.current(msg);
        } catch {
          // ignore parse errors
        }
      };

      ws.onclose = () => {
        wsRef.current = null;
        // 5 秒后重连
        reconnectTimer.current = setTimeout(connect, 5_000);
      };

      ws.onerror = () => {
        // onerror 后会触发 onclose，由 onclose 处理重连
      };
    } catch {
      // 连接失败，5 秒后重试
      reconnectTimer.current = setTimeout(connect, 5_000);
    }
  }, [enabled]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        wsRef.current.onclose = null; // 防止 cleanup 触发重连
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);
}
