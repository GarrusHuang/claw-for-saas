import { useState, useEffect, lazy, Suspense } from 'react';
import { configureAI, useAIChatStore, useAuthStore } from '@claw/core';
import { AIChatDialog, ClawFloatingButton } from '@claw/ui';
import LoginPage from './LoginPage';

const AdminPage = lazy(() => import('./admin/AdminPage'));

export default function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const userId = useAuthStore((s) => s.userId);
  const isAdmin = useAuthStore((s) => s.isAdmin);
  const restore = useAuthStore((s) => s.restore);

  const [topView, setTopView] = useState<'chat' | 'admin'>('chat');

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

  // 非 admin 切回 chat
  useEffect(() => {
    if (!isAdmin && topView === 'admin') setTopView('chat');
  }, [isAdmin, topView]);

  // 路由守卫：未认证 → 登录页
  if (!isAuthenticated) {
    return <LoginPage />;
  }

  return (
    <div className={isAdmin ? 'app-root app-root--admin' : 'app-root'}>
      {isAdmin && (
        <div className="admin-tab-bar">
          <div className="admin-tab-bar-inner">
            <button
              className={`admin-tab-btn${topView === 'chat' ? ' admin-tab-btn--active' : ''}`}
              onClick={() => setTopView('chat')}
            >
              对话
            </button>
            <button
              className={`admin-tab-btn${topView === 'admin' ? ' admin-tab-btn--active' : ''}`}
              onClick={() => setTopView('admin')}
            >
              管理
            </button>
          </div>
        </div>
      )}
      <div className="app-content" style={{ display: topView === 'chat' ? undefined : 'none' }}>
        <AIChatDialog />
        <ClawFloatingButton />
      </div>
      {topView === 'admin' && (
        <div className="app-content app-content--admin">
          <Suspense fallback={<div style={{ padding: 40, textAlign: 'center', color: '#8c8c8c' }}>加载中...</div>}>
            <AdminPage />
          </Suspense>
        </div>
      )}
    </div>
  );
}
