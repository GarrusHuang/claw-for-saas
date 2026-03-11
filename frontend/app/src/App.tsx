import { useEffect } from 'react';
import { useAIChatStore } from '@claw/core';
import { AIChatDialog, ClawFloatingButton } from '@claw/ui';

export default function App() {
  // 启动时自动打开全屏对话
  useEffect(() => {
    useAIChatStore.getState().openChat('');
  }, []);

  return (
    <>
      <AIChatDialog />
      <ClawFloatingButton />
    </>
  );
}
