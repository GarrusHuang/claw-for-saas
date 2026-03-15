/**
 * Shared Markdown rendering config for react-markdown.
 * Exports MARKDOWN_COMPONENTS (code block → HighlightedCode) and REMARK_PLUGINS.
 */
import type { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import HighlightedCode from './HighlightedCode';

/**
 * Custom components for react-markdown.
 * - Block code (```lang ... ```) → <HighlightedCode> with syntax highlighting
 * - Inline code (`foo`) → plain <code> with default styling
 */
export const MARKDOWN_COMPONENTS: Components = {
  code({ className, children, ...rest }) {
    // react-markdown adds className="language-xxx" for fenced code blocks
    const match = /language-(\w+)/.exec(className || '');
    if (match) {
      const code = String(children).replace(/\n$/, '');
      return <HighlightedCode code={code} language={match[1]} />;
    }
    // Inline code — render as normal <code>
    return <code className={className} {...rest}>{children}</code>;
  },
};

export const REMARK_PLUGINS = [remarkGfm];
