/**
 * FileCard — Refined file card for chat attachments and message display.
 *
 * Two variants:
 *   compact  — slim pill for ChatInput attachment bar (removable, previewable)
 *   standard — richer card for ChatMessageList (icon block + metadata + hover preview)
 */
import { useState, useRef, useEffect } from 'react';
import {
  FileOutlined,
  FileImageOutlined,
  FilePdfOutlined,
  FileWordOutlined,
  FileExcelOutlined,
  FileZipOutlined,
  FileMarkdownOutlined,
  CodeOutlined,
  EyeOutlined,
  CloseOutlined,
} from '@ant-design/icons';

/* ── palette ── */

interface FileMeta {
  icon: React.ReactNode;
  /** accent used for icon, label, and hover tint */
  accent: string;
  /** softer tint for icon block background */
  tint: string;
  /** extension label override (optional) */
  label?: string;
}

function getExtension(filename: string): string {
  return filename.split('.').pop()?.toLowerCase() || '';
}

function fileMeta(filename: string): FileMeta {
  const ext = getExtension(filename);

  const map: Record<string, FileMeta> = {
    // images
    png:  { icon: <FileImageOutlined />, accent: '#0ea5e9', tint: '#f0f9ff', label: 'PNG' },
    jpg:  { icon: <FileImageOutlined />, accent: '#0ea5e9', tint: '#f0f9ff', label: 'JPG' },
    jpeg: { icon: <FileImageOutlined />, accent: '#0ea5e9', tint: '#f0f9ff', label: 'JPEG' },
    gif:  { icon: <FileImageOutlined />, accent: '#0ea5e9', tint: '#f0f9ff', label: 'GIF' },
    bmp:  { icon: <FileImageOutlined />, accent: '#0ea5e9', tint: '#f0f9ff', label: 'BMP' },
    webp: { icon: <FileImageOutlined />, accent: '#0ea5e9', tint: '#f0f9ff', label: 'WEBP' },
    svg:  { icon: <FileImageOutlined />, accent: '#0ea5e9', tint: '#f0f9ff', label: 'SVG' },
    // pdf
    pdf:  { icon: <FilePdfOutlined />,   accent: '#ef4444', tint: '#fef2f2', label: 'PDF' },
    // word
    doc:  { icon: <FileWordOutlined />,  accent: '#3b82f6', tint: '#eff6ff', label: 'DOC' },
    docx: { icon: <FileWordOutlined />,  accent: '#3b82f6', tint: '#eff6ff', label: 'DOCX' },
    // excel
    xls:  { icon: <FileExcelOutlined />, accent: '#22c55e', tint: '#f0fdf4', label: 'XLS' },
    xlsx: { icon: <FileExcelOutlined />, accent: '#22c55e', tint: '#f0fdf4', label: 'XLSX' },
    csv:  { icon: <FileExcelOutlined />, accent: '#22c55e', tint: '#f0fdf4', label: 'CSV' },
    // archives
    zip:  { icon: <FileZipOutlined />,   accent: '#f59e0b', tint: '#fffbeb', label: 'ZIP' },
    tar:  { icon: <FileZipOutlined />,   accent: '#f59e0b', tint: '#fffbeb', label: 'TAR' },
    gz:   { icon: <FileZipOutlined />,   accent: '#f59e0b', tint: '#fffbeb', label: 'GZ' },
    // code
    js:   { icon: <CodeOutlined />,      accent: '#a855f7', tint: '#faf5ff', label: 'JS' },
    ts:   { icon: <CodeOutlined />,      accent: '#a855f7', tint: '#faf5ff', label: 'TS' },
    tsx:  { icon: <CodeOutlined />,      accent: '#a855f7', tint: '#faf5ff', label: 'TSX' },
    jsx:  { icon: <CodeOutlined />,      accent: '#a855f7', tint: '#faf5ff', label: 'JSX' },
    py:   { icon: <CodeOutlined />,      accent: '#a855f7', tint: '#faf5ff', label: 'PY' },
    css:  { icon: <CodeOutlined />,      accent: '#a855f7', tint: '#faf5ff', label: 'CSS' },
    scss: { icon: <CodeOutlined />,      accent: '#a855f7', tint: '#faf5ff', label: 'SCSS' },
    html: { icon: <CodeOutlined />,      accent: '#a855f7', tint: '#faf5ff', label: 'HTML' },
    // data / text
    json: { icon: <CodeOutlined />,      accent: '#a855f7', tint: '#faf5ff', label: 'JSON' },
    xml:  { icon: <CodeOutlined />,      accent: '#a855f7', tint: '#faf5ff', label: 'XML' },
    yaml: { icon: <FileOutlined />,      accent: '#6b7280', tint: '#f9fafb', label: 'YAML' },
    yml:  { icon: <FileOutlined />,      accent: '#6b7280', tint: '#f9fafb', label: 'YML' },
    md:   { icon: <FileMarkdownOutlined />, accent: '#6b7280', tint: '#f9fafb', label: 'MD' },
    txt:  { icon: <FileOutlined />,      accent: '#6b7280', tint: '#f9fafb', label: 'TXT' },
  };

  return map[ext] || { icon: <FileOutlined />, accent: '#9ca3af', tint: '#f9fafb' };
}

export function formatFileSize(bytes?: number): string {
  if (bytes === 0) return '0 B';
  if (!bytes) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/* ── types ── */

export interface FileCardFile {
  fileId: string;
  filename: string;
  contentType?: string;
  sizeBytes?: number;
}

interface FileCardProps {
  file: FileCardFile;
  onPreview?: (file: FileCardFile) => void;
  onRemove?: (fileId: string) => void;
  compact?: boolean;
}

/* ── component ── */

export default function FileCard({ file, onPreview, onRemove, compact = false }: FileCardProps) {
  const [hovered, setHovered] = useState(false);
  const meta = fileMeta(file.filename);
  const ext = getExtension(file.filename);
  const label = meta.label || ext.toUpperCase() || 'FILE';
  const cardRef = useRef<HTMLDivElement>(null);

  // inject keyframes once
  useEffect(() => {
    if (typeof document === 'undefined') return;
    const id = '__filecard_styles';
    if (document.getElementById(id)) return;
    const style = document.createElement('style');
    style.id = id;
    style.textContent = `
      @keyframes filecard-in {
        from { opacity: 0; transform: translateY(4px) scale(0.97); }
        to   { opacity: 1; transform: translateY(0) scale(1); }
      }
      .filecard-compact { animation: filecard-in 0.18s ease-out both; }
      .filecard-standard { animation: filecard-in 0.22s ease-out both; }
      .filecard-close:hover { background: rgba(0,0,0,0.06) !important; color: #666 !important; }
      .filecard-standard .filecard-eye {
        opacity: 0; transform: translateX(4px);
        transition: opacity 0.18s, transform 0.18s;
      }
      .filecard-standard:hover .filecard-eye { opacity: 1; transform: translateX(0); }
    `;
    document.head.appendChild(style);
  }, []);

  /* ── COMPACT variant ── */
  if (compact) {
    return (
      <div
        ref={cardRef}
        className="filecard-compact"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 7,
          padding: '5px 8px 5px 6px',
          background: hovered ? meta.tint : '#fff',
          borderRadius: 9,
          border: `1px solid ${hovered ? meta.accent + '30' : '#e5e7eb'}`,
          cursor: onPreview ? 'pointer' : 'default',
          transition: 'background 0.15s, border-color 0.15s, box-shadow 0.15s',
          maxWidth: 240,
          boxShadow: hovered ? `0 2px 8px ${meta.accent}12` : '0 1px 2px rgba(0,0,0,0.04)',
        }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onClick={() => onPreview?.(file)}
      >
        {/* icon dot */}
        <div style={{
          width: 26, height: 26, borderRadius: 7,
          background: meta.tint,
          border: `1px solid ${meta.accent}18`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0,
        }}>
          <span style={{ fontSize: 13, color: meta.accent, display: 'flex' }}>{meta.icon}</span>
        </div>
        {/* filename */}
        <span style={{
          fontSize: 12.5, fontWeight: 480,
          color: '#374151',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          flex: 1, minWidth: 0,
          letterSpacing: '-0.01em',
        }}>
          {file.filename}
        </span>
        {/* extension badge */}
        <span style={{
          fontSize: 9.5, fontWeight: 600,
          color: meta.accent,
          background: meta.tint,
          padding: '1px 5px',
          borderRadius: 4,
          letterSpacing: '0.03em',
          flexShrink: 0,
          lineHeight: '16px',
        }}>
          {label}
        </span>
        {/* close */}
        {onRemove && (
          <span
            className="filecard-close"
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              width: 18, height: 18, borderRadius: 5,
              color: '#b0b0b0', fontSize: 9,
              cursor: 'pointer', flexShrink: 0,
              transition: 'background 0.12s, color 0.12s',
            }}
            onClick={(e) => { e.stopPropagation(); onRemove(file.fileId); }}
          >
            <CloseOutlined />
          </span>
        )}
      </div>
    );
  }

  /* ── STANDARD variant ── */
  return (
    <div
      ref={cardRef}
      className="filecard-standard"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 11,
        padding: '10px 14px',
        background: hovered ? '#fff' : '#fafafa',
        borderRadius: 12,
        border: `1px solid ${hovered ? meta.accent + '28' : '#eee'}`,
        cursor: onPreview ? 'pointer' : 'default',
        transition: 'all 0.2s cubic-bezier(0.25, 0.46, 0.45, 0.94)',
        maxWidth: 300,
        boxShadow: hovered
          ? `0 4px 16px ${meta.accent}10, 0 1px 4px rgba(0,0,0,0.05)`
          : '0 1px 3px rgba(0,0,0,0.03)',
        transform: hovered ? 'translateY(-1px)' : 'none',
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={() => onPreview?.(file)}
    >
      {/* icon block */}
      <div style={{
        width: 40, height: 40, borderRadius: 10,
        background: `linear-gradient(135deg, ${meta.tint}, ${meta.accent}0d)`,
        border: `1px solid ${meta.accent}15`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0,
        transition: 'transform 0.2s',
        transform: hovered ? 'scale(1.05)' : 'none',
      }}>
        <span style={{ fontSize: 19, color: meta.accent, display: 'flex' }}>{meta.icon}</span>
      </div>

      {/* text */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 13.5, fontWeight: 520,
          color: '#1f2937',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          lineHeight: '18px',
          letterSpacing: '-0.01em',
        }}>
          {file.filename}
        </div>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6,
          marginTop: 2,
        }}>
          {/* type pill */}
          <span style={{
            fontSize: 10, fontWeight: 650,
            color: meta.accent,
            background: meta.tint,
            padding: '1px 6px',
            borderRadius: 4,
            letterSpacing: '0.04em',
            lineHeight: '16px',
          }}>
            {label}
          </span>
          {file.sizeBytes != null && file.sizeBytes > 0 && (
            <span style={{
              fontSize: 11, color: '#9ca3af',
              letterSpacing: '-0.01em',
            }}>
              {formatFileSize(file.sizeBytes)}
            </span>
          )}
        </div>
      </div>

      {/* preview hint */}
      {onPreview && (
        <span className="filecard-eye" style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          width: 28, height: 28, borderRadius: 7,
          background: meta.tint,
          color: meta.accent,
          fontSize: 13,
          flexShrink: 0,
        }}>
          <EyeOutlined />
        </span>
      )}
    </div>
  );
}
