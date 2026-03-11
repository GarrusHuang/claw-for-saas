import React from 'react';
import ReactDOM from 'react-dom/client';
import { configureAI, useAuthStore } from '@claw/core';
import App from './App';
import './index.css';

// Claw 独立配置 — 动态 token 注入
configureAI({
  aiBaseUrl: import.meta.env.VITE_AI_BACKEND_URL || '',
  defaultUserId: 'U001',
  scenarios: {},
  getAuthToken: () => useAuthStore.getState().token,
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
