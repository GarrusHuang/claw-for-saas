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
        onClick={() => setOpen((v) => !v)}
      >
        <span className="collapsible-chevron">{open ? '▾' : '▸'}</span>
        {icon && <span className="collapsible-icon">{icon}</span>}
        <span className="collapsible-label">{summary}</span>
      </div>
      {open && <div className="collapsible-body">{children}</div>}
    </div>
  );
}
