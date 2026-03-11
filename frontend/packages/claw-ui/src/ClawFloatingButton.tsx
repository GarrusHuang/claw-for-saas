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
      onClick={() => openChat('')}
      title="Click to open Claw AI Assistant"
    >
      <img src="/assets/claw-icon.svg" alt="Claw AI" />
    </div>
  );
}
