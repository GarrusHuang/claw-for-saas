import { useState } from 'react';
import { useAuthStore } from '@claw/core';

export default function LoginPage() {
  const login = useAuthStore((s) => s.login);
  const register = useAuthStore((s) => s.register);
  const loading = useAuthStore((s) => s.loading);
  const error = useAuthStore((s) => s.error);

  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [inviteCode, setInviteCode] = useState('');
  const [success, setSuccess] = useState(false);
  const [localError, setLocalError] = useState('');

  const switchMode = (m: 'login' | 'register') => {
    setMode(m);
    setLocalError('');
    setSuccess(false);
    useAuthStore.setState({ error: null });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLocalError('');
    if (!username.trim()) return;

    if (mode === 'register') {
      if (password !== confirmPassword) {
        setLocalError('两次输入的密码不一致');
        return;
      }
      if (!inviteCode.trim()) {
        setLocalError('请输入邀请码');
        return;
      }
      const ok = await register(inviteCode.trim(), username.trim(), password);
      if (ok) setSuccess(true);
    } else {
      const ok = await login(username.trim(), password);
      if (ok) setSuccess(true);
    }
  };

  const displayError = localError || error;
  const isLogin = mode === 'login';

  const canSubmit = isLogin
    ? !loading && !success && !!username.trim() && !!password
    : !loading && !success && !!username.trim() && !!password && !!confirmPassword && !!inviteCode.trim();

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-header">
          <span className="login-logo">Claw for SaaS</span>
          <span className="login-subtitle">AI Agent 运行时</span>
        </div>

        <div className="login-tabs" style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          <button
            type="button"
            className={`login-tab ${isLogin ? 'active' : ''}`}
            onClick={() => switchMode('login')}
            style={{
              flex: 1, padding: '8px 0', border: 'none', cursor: 'pointer',
              borderBottom: isLogin ? '2px solid #1677ff' : '2px solid transparent',
              background: 'transparent', fontWeight: isLogin ? 600 : 400,
              color: isLogin ? '#1677ff' : '#666',
            }}
          >
            登录
          </button>
          <button
            type="button"
            className={`login-tab ${!isLogin ? 'active' : ''}`}
            onClick={() => switchMode('register')}
            style={{
              flex: 1, padding: '8px 0', border: 'none', cursor: 'pointer',
              borderBottom: !isLogin ? '2px solid #1677ff' : '2px solid transparent',
              background: 'transparent', fontWeight: !isLogin ? 600 : 400,
              color: !isLogin ? '#1677ff' : '#666',
            }}
          >
            注册
          </button>
        </div>

        <form onSubmit={handleSubmit} className="login-form">
          {!isLogin && (
            <div className="login-field">
              <label htmlFor="inviteCode">邀请码</label>
              <input
                id="inviteCode"
                type="text"
                value={inviteCode}
                onChange={(e) => setInviteCode(e.target.value)}
                placeholder="请输入邀请码"
                autoFocus={!isLogin}
                autoComplete="off"
              />
            </div>
          )}

          <div className="login-field">
            <label htmlFor="username">用户名</label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="请输入用户名"
              autoFocus={isLogin}
              autoComplete="username"
            />
          </div>

          <div className="login-field">
            <label htmlFor="password">密码</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="请输入密码"
              autoComplete={isLogin ? 'current-password' : 'new-password'}
            />
          </div>

          {!isLogin && (
            <div className="login-field">
              <label htmlFor="confirmPassword">确认密码</label>
              <input
                id="confirmPassword"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="请再次输入密码"
                autoComplete="new-password"
              />
            </div>
          )}

          {displayError && <div className="login-error">{displayError}</div>}

          <button type="submit" className="login-btn" disabled={!canSubmit}>
            {success
              ? (isLogin ? '登录成功！' : '注册成功！')
              : loading
                ? (isLogin ? '登录中...' : '注册中...')
                : (isLogin ? '登录' : '注册')}
          </button>
        </form>
      </div>
    </div>
  );
}
