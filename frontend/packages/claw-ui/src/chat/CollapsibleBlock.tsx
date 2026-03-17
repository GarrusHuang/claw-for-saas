import { useState } from 'react';

interface CollapsibleBlockProps {
  icon?: React.ReactNode;
  summary: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

export default function CollapsibleBlock({
  icon,
  summary,
  defaultOpen = false,
  children,
}: CollapsibleBlockProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="collapsible-block">
      <div
        className="collapsible-summary"
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen((v) => !v); } }}
        style={{ display: 'flex', alignItems: 'center', gap: 4 }}
      >
        {icon && <span className="collapsible-icon">{icon}</span>}
        <span className="collapsible-label" style={{ flex: 1 }}>{summary}</span>
        <span className="collapsible-chevron" style={{ color: '#999', fontSize: 12, flexShrink: 0 }}>
          {open ? '\u2304' : '\u203A'}
        </span>
      </div>
      {open && <div className="collapsible-body">{children}</div>}
    </div>
  );
}
