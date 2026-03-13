/**
 * FileArtifactCard — Agent 生成文件的内联卡片。
 *
 * 紧凑展示: 文件图标 + 文件名 + 类型标签 + 预览/下载按钮。
 */
import { useState } from 'react';
import { Button, Tag } from 'antd';
import {
  FileOutlined,
  FilePdfOutlined,
  FileExcelOutlined,
  FileWordOutlined,
  FileImageOutlined,
  FileZipOutlined,
  EyeOutlined,
  DownloadOutlined,
} from '@ant-design/icons';
import { getAIConfig } from '@claw/core';
import type { FileArtifact } from '@claw/core';
import FilePreviewModal from './FilePreviewModal';

function getArtifactIcon(filename: string) {
  const ext = filename.split('.').pop()?.toLowerCase() || '';
  if (['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'svg'].includes(ext))
    return <FileImageOutlined style={{ color: '#1890ff', fontSize: 16 }} />;
  if (ext === 'pdf')
    return <FilePdfOutlined style={{ color: '#ff4d4f', fontSize: 16 }} />;
  if (['doc', 'docx'].includes(ext))
    return <FileWordOutlined style={{ color: '#2f54eb', fontSize: 16 }} />;
  if (['xls', 'xlsx', 'csv'].includes(ext))
    return <FileExcelOutlined style={{ color: '#52c41a', fontSize: 16 }} />;
  if (['zip', 'tar', 'gz', 'rar', '7z'].includes(ext))
    return <FileZipOutlined style={{ color: '#faad14', fontSize: 16 }} />;
  return <FileOutlined style={{ color: '#8c8c8c', fontSize: 16 }} />;
}

function getTypeLabel(filename: string, contentType: string): string {
  const ext = filename.split('.').pop()?.toLowerCase() || '';
  if (ext) return ext.toUpperCase();
  const sub = contentType.split('/').pop() || '';
  return sub.toUpperCase() || 'FILE';
}

function formatSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function getAuthHeaders(): Promise<Record<string, string>> {
  const config = getAIConfig();
  const headers: Record<string, string> = {};
  if (config.getAuthToken) {
    const token = await config.getAuthToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
  } else if (config.authToken) {
    headers['Authorization'] = `Bearer ${config.authToken}`;
  }
  return headers;
}

interface FileArtifactCardProps {
  artifact: FileArtifact;
}

export default function FileArtifactCard({ artifact }: FileArtifactCardProps) {
  const [previewOpen, setPreviewOpen] = useState(false);
  const { filename, path, contentType, sizeBytes, sessionId } = artifact;
  const typeLabel = getTypeLabel(filename, contentType);

  const downloadUrl = `${getAIConfig().aiBaseUrl}/api/workspace/${sessionId}/files/${encodeURIComponent(path)}/download`;

  const handleDownload = async () => {
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(downloadUrl, { headers });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
      }
    } catch (e) {
      console.warn('[FileArtifactCard] download failed:', e);
    }
  };

  return (
    <>
      <div
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 8,
          padding: '6px 12px',
          background: '#fafafa',
          border: '1px solid #e8e8e8',
          borderRadius: 8,
          fontSize: 13,
          marginBottom: 8,
          maxWidth: '100%',
        }}
      >
        {getArtifactIcon(filename)}
        <span
          style={{
            fontWeight: 500,
            color: '#333',
            maxWidth: 200,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={path}
        >
          {filename}
        </span>
        <Tag
          color="default"
          style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px', margin: 0 }}
        >
          {typeLabel}
        </Tag>
        {sizeBytes > 0 && (
          <span style={{ color: '#bfbfbf', fontSize: 11 }}>{formatSize(sizeBytes)}</span>
        )}
        <Button
          type="text"
          size="small"
          icon={<EyeOutlined />}
          onClick={() => setPreviewOpen(true)}
          style={{ fontSize: 12, padding: '0 4px' }}
        >
          预览
        </Button>
        <Button
          type="text"
          size="small"
          icon={<DownloadOutlined />}
          onClick={handleDownload}
          style={{ fontSize: 12, padding: '0 4px' }}
        >
          下载
        </Button>
      </div>

      {previewOpen && (
        <FilePreviewModal
          open={previewOpen}
          fileId={`workspace/${sessionId}/files/${encodeURIComponent(path)}`}
          filename={filename}
          onClose={() => setPreviewOpen(false)}
          apiBase="/api"
        />
      )}
    </>
  );
}
