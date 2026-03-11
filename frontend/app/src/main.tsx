import React from 'react';
import ReactDOM from 'react-dom/client';
import { configureAI } from '@claw/core';
import App from './App';
import './index.css';

// Claw 独立配置 — 纯自由对话
configureAI({
  aiBaseUrl: import.meta.env.VITE_AI_BACKEND_URL || '',
  defaultUserId: 'U001',
  scenarios: {},
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
