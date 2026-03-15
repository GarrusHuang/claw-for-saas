/**
 * Shared syntax-highlighted code block.
 * Uses PrismLight + oneLight theme for consistent rendering
 * across file preview and chat markdown.
 */
import { useState, useCallback } from 'react';
import { PrismLight } from 'react-syntax-highlighter';
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { CopyOutlined, CheckOutlined } from '@ant-design/icons';
import { copyToClipboard } from '../utils/download';

// Side-effect: register languages
import './highlightLanguages';

interface HighlightedCodeProps {
  code: string;
  language?: string;
  showLineNumbers?: boolean;
  maxHeight?: string;
}

/** Capitalise language label for display */
function formatLanguageLabel(lang: string): string {
  const labels: Record<string, string> = {
    js: 'JavaScript', javascript: 'JavaScript',
    ts: 'TypeScript', typescript: 'TypeScript',
    tsx: 'TSX', jsx: 'JSX',
    py: 'Python', python: 'Python',
    go: 'Go', java: 'Java', rust: 'Rust',
    css: 'CSS', sql: 'SQL', c: 'C',
    yaml: 'YAML', yml: 'YAML',
    json: 'JSON', bash: 'Bash', sh: 'Bash', shell: 'Bash',
    markdown: 'Markdown', md: 'Markdown',
    xml: 'XML', html: 'HTML', diff: 'Diff',
  };
  return labels[lang] ?? lang.toUpperCase();
}

export default function HighlightedCode({
  code,
  language,
  showLineNumbers = false,
  maxHeight,
}: HighlightedCodeProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    copyToClipboard(code);
    setCopied(true);
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [code]);

  // No language → plain <pre> fallback
  if (!language) {
    return (
      <div className="highlighted-code">
        <div className="highlighted-code-header">
          <span style={{ color: '#8c8c8c' }}>Text</span>
          <button
            onClick={handleCopy}
            style={{
              border: 'none', background: 'none', cursor: 'pointer',
              fontSize: 12, color: copied ? '#52c41a' : '#8c8c8c',
              display: 'flex', alignItems: 'center', gap: 4,
            }}
          >
            {copied ? <CheckOutlined /> : <CopyOutlined />}
            {copied ? '已复制' : '复制'}
          </button>
        </div>
        <div className="highlighted-code-body">
          <pre style={{
            margin: 0, padding: 14, fontSize: 13, lineHeight: 1.6,
            fontFamily: 'monospace', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            background: '#fafafa',
            maxHeight: maxHeight, overflow: maxHeight ? 'auto' : undefined,
          }}>
            <code>{code}</code>
          </pre>
        </div>
      </div>
    );
  }

  return (
    <div className="highlighted-code">
      <div className="highlighted-code-header">
        <span style={{ color: '#8c8c8c' }}>{formatLanguageLabel(language)}</span>
        <button
          onClick={handleCopy}
          style={{
            border: 'none', background: 'none', cursor: 'pointer',
            fontSize: 12, color: copied ? '#52c41a' : '#8c8c8c',
            display: 'flex', alignItems: 'center', gap: 4,
          }}
        >
          {copied ? <CheckOutlined /> : <CopyOutlined />}
          {copied ? '已复制' : '复制'}
        </button>
      </div>
      <div className="highlighted-code-body" style={{ maxHeight: maxHeight, overflow: maxHeight ? 'auto' : undefined }}>
        <PrismLight
          language={language}
          style={oneLight}
          showLineNumbers={showLineNumbers}
          wrapLines
          customStyle={{
            margin: 0,
            padding: 14,
            fontSize: 13,
            lineHeight: 1.6,
            background: '#fafafa',
            borderRadius: 0,
          }}
        >
          {code}
        </PrismLight>
      </div>
    </div>
  );
}
