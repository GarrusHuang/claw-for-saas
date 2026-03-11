import { useEffect } from 'react';
import { configureAI, useAIChatStore, useAuthStore } from '@claw/core';
import { AIChatDialog, ClawFloatingButton } from '@claw/ui';
import LoginPage from './LoginPage';

export default function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated());
  const userId = useAuthStore((s) => s.userId);
  const restore = useAuthStore((s) => s.restore);

  // 启动时从 localStorage 恢复 token
  useEffect(() => {
    restore();
  }, [restore]);

  // 认证后更新 defaultUserId 并自动打开全屏对话
  useEffect(() => {
    if (isAuthenticated && userId) {
      configureAI({ defaultUserId: userId });
      useAIChatStore.getState().openChat('');
    }
  }, [isAuthenticated, userId]);

  // 路由守卫：未认证 → 登录页
  if (!isAuthenticated) {
    return <LoginPage />;
  }

  return (
    <>
      <AIChatDialog />
      <ClawFloatingButton />
    </>
  );
}
