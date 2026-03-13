/**
 * WebSocket 通知 Hook — 连接后端全局推送通道。
 *
 * 自动管理 WebSocket 连接生命周期 (连接/重连/心跳)，
 * 收到事件时触发注册的回调。
 */

import { useEffect, useRef, useCallback } from 'react';
import { getAIConfig } from '../config.ts';

export type NotificationHandler = (event: { type: string; data: Record<string, unknown> }) => void;

/**
 * 连接 WebSocket 通知通道，接收服务端推送。
 *
 * @param onNotification - 收到通知时的回调
 * @param enabled - 是否启用 (默认 true)
 */
export function useNotifications(onNotification: NotificationHandler, enabled = true): void {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();
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
          const data = JSON.parse(evt.data);
          // 忽略 pong/ping 心跳
          if (data.type === 'pong' || data.type === 'ping') return;
          handlerRef.current(data);
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
