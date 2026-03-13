/**
 * DocumentPresenter — 文档展示卡片 (Cowork 风格)。
 *
 * Phase 23B: 紧凑卡片，预览文档内容 + 下载/全屏 按钮。
 * 替代旧的 DocumentCard 作为主要文档展示组件。
 */

import { useState } from 'react';
import { Typography, Button, Tag } from 'antd';
import {
  FileTextOutlined,
  ExpandOutlined,
  DownloadOutlined,
  CopyOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { GeneratedDocument } from '@claw/core';
import DocumentPreviewModal from './DocumentPreviewModal';
import { downloadAsFile, downloadFromUrl, copyToClipboard } from '../utils/download';
import { getAIConfig } from '@claw/core';

const { Text } = Typography;

interface DocumentPresenterProps {
  document: GeneratedDocument;
  maxPreviewLines?: number;
  onAdopt?: (doc: GeneratedDocument) => void;
}

export default function DocumentPresenter({
  document: doc,
  maxPreviewLines = 8,
  onAdopt,
}: DocumentPresenterProps) {
  const [previewOpen, setPreviewOpen] = useState(false);

  // Truncate content for preview
  const lines = doc.content.split('\n');
  const isTruncated = lines.length > maxPreviewLines;
  const previewContent = isTruncated
    ? lines.slice(0, maxPreviewLines).join('\n') + '\n...'
    : doc.content;

  const hasDocx = !!(doc.metadata?.docx_download_url);
  const filename = hasDocx
    ? (doc.metadata?.docx_filename as string) || `${doc.title || 'document'}.docx`
    : `${doc.title || 'document'}.md`;

  const handleDownload = () => {
    if (hasDocx) {
      const token = getAIConfig().getAuthToken?.() ?? getAIConfig().authToken ?? '';
      downloadFromUrl(doc.metadata.docx_download_url as string, filename, token ? { 'Authorization': `Bearer ${token}` } : undefined);
    } else {
      downloadAsFile(doc.content, filename);
    }
  };

  return (
    <>
      <div className="document-presenter">
        {/* Header */}
        <div className="document-presenter-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
            <FileTextOutlined style={{ color: '#722ed1', fontSize: 14, flexShrink: 0 }} />
            <Text strong style={{ fontSize: 13 }} ellipsis>
              {doc.title || '文档已生成'}
            </Text>
            <Tag color="purple" style={{ fontSize: 10, flexShrink: 0 }}>{doc.documentType}</Tag>
          </div>
          <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
            {onAdopt && (
              <Button
                type="text"
                size="small"
                icon={<CheckCircleOutlined style={{ fontSize: 12, color: '#52c41a' }} />}
                onClick={() => onAdopt(doc)}
                title="采纳到表单"
              />
            )}
            <Button
              type="text"
              size="small"
              icon={<CopyOutlined style={{ fontSize: 12 }} />}
              onClick={() => copyToClipboard(doc.content)}
              title="复制"
            />
            <Button
              type="text"
              size="small"
              icon={<DownloadOutlined style={{ fontSize: 12 }} />}
              onClick={handleDownload}
              title={hasDocx ? '下载 DOCX' : '下载'}
            />
            <Button
              type="text"
              size="small"
              icon={<ExpandOutlined style={{ fontSize: 12 }} />}
              onClick={() => setPreviewOpen(true)}
              title="全屏预览"
            />
          </div>
        </div>

        {/* Preview */}
        <div
          className="document-presenter-preview markdown-body"
          onClick={() => setPreviewOpen(true)}
        >
          <Markdown remarkPlugins={[remarkGfm]}>{previewContent}</Markdown>
        </div>

        {/* Footer */}
        {isTruncated && (
          <div className="document-presenter-footer">
            <Button
              type="link"
              size="small"
              onClick={() => setPreviewOpen(true)}
              style={{ fontSize: 11, padding: 0 }}
            >
              查看完整文档 ({lines.length} 行)
            </Button>
          </div>
        )}

        {/* Metadata */}
        {doc.metadata && Object.keys(doc.metadata).length > 0 && (
          <div className="document-presenter-meta">
            {Object.entries(doc.metadata)
              .filter(([k, v]) => v != null && v !== '' && k !== 'originalContent')
              .slice(0, 3)
              .map(([key, value]) => (
                <Tag key={key} style={{ fontSize: 10 }}>
                  {key}: {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                </Tag>
              ))}
          </div>
        )}
      </div>

      {/* Preview Modal */}
      <DocumentPreviewModal
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        document={doc}
      />
    </>
  );
}
