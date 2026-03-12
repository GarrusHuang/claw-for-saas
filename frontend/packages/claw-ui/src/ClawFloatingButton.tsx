import { useAIChatStore } from '@claw/core';

/**
 * Claw AI floating button — always visible at bottom-right corner, opens AI chat dialog on click.
 * Hidden when the chat dialog is already open.
 */
export default function ClawFloatingButton() {
  const chatDialogState = useAIChatStore((s) => s.chatDialogState);
  const openChat = useAIChatStore((s) => s.openChat);

  // Hide floating button when dialog is open
  if (chatDialogState !== 'closed') return null;

  return (
    <div
      className="claw-floating-btn"
      role="button"
      tabIndex={0}
      onClick={() => openChat('')}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openChat(''); } }}
      aria-label="点击打开 Claw AI 助手"
    >
      <img src="/assets/claw-icon.svg" alt="Claw AI" />
    </div>
  );
}
