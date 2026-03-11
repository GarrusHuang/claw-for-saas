/**
 * DocumentPreviewModal — 全屏文档预览 Modal。
 *
 * Phase 23B: Markdown 渲染预览 + 下载功能。
 * 类似 Claude Cowork 的文档展示。
 */

import { Modal, Button, Typography, Tag } from 'antd';
import {
  DownloadOutlined,
  FileTextOutlined,
  CopyOutlined,
} from '@ant-design/icons';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { GeneratedDocument } from '@claw/core';

const { Text } = Typography;

interface DocumentPreviewModalProps {
  open: boolean;
  onClose: () => void;
  document: GeneratedDocument | null;
}

function downloadAsFile(content: string, filename: string) {
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function downloadFromUrl(url: string, filename: string) {
  fetch(url)
    .then((res) => {
      if (!res.ok) throw new Error(`Download failed: ${res.status}`);
      return res.blob();
    })
    .then((blob) => {
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(blobUrl);
    })
    .catch((err) => console.error('Download error:', err));
}

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text).catch(() => {
    // Fallback for non-secure contexts
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  });
}

export default function DocumentPreviewModal({
  open,
  onClose,
  document: doc,
}: DocumentPreviewModalProps) {
  if (!doc) return null;

  const hasDocx = !!(doc.metadata?.docx_download_url);
  const filename = hasDocx
    ? (doc.metadata?.docx_filename as string) || `${doc.title || 'document'}.docx`
    : `${doc.title || 'document'}.md`;

  const handleDownload = () => {
    if (hasDocx) {
      downloadFromUrl(doc.metadata.docx_download_url as string, filename);
    } else {
      downloadAsFile(doc.content, filename);
    }
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      width="80vw"
      style={{ top: 40 }}
      title={
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <FileTextOutlined style={{ color: '#722ed1' }} />
          <span>{doc.title || '文档预览'}</span>
          <Tag color="purple" style={{ fontSize: 10 }}>{doc.documentType}</Tag>
        </div>
      }
      footer={
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {doc.content.length} 字符
          </Text>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button
              size="small"
              icon={<CopyOutlined />}
              onClick={() => copyToClipboard(doc.content)}
            >
              复制
            </Button>
            <Button
              size="small"
              icon={<DownloadOutlined />}
              onClick={handleDownload}
            >
              {hasDocx ? '下载 DOCX' : '下载'}
            </Button>
            <Button size="small" onClick={onClose}>
              关闭
            </Button>
          </div>
        </div>
      }
    >
      <div
        className="document-preview-content markdown-body"
        style={{
          maxHeight: '70vh',
          overflow: 'auto',
          padding: '16px 24px',
          background: '#fafafa',
          borderRadius: 8,
          border: '1px solid #f0f0f0',
        }}
      >
        <Markdown remarkPlugins={[remarkGfm]}>{doc.content}</Markdown>
      </div>
    </Modal>
  );
}
