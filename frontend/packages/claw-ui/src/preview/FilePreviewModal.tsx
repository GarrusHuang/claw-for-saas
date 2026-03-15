/**
 * 文件预览 Modal — 包装 UniversalFilePreview。
 */
import { useState, useEffect } from 'react';
import { Modal, Spin, Tag, Button } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import { getAIConfig } from '@claw/core';
import UniversalFilePreview from './UniversalFilePreview';

interface FilePreviewModalProps {
  open: boolean;
  fileId: string;
  filename?: string;
  onClose: () => void;
  /** API base path: "/api/files" or "/api/knowledge" */
  apiBase?: string;
  /** Hide the download button in the title bar */
  hideDownload?: boolean;
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

export default function FilePreviewModal({ open, fileId, filename, onClose, apiBase = '/api/files', hideDownload = false }: FilePreviewModalProps) {
  const [previewData, setPreviewData] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !fileId) return;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const headers = await getAuthHeaders();
        headers['Content-Type'] = 'application/json';
        const res = await fetch(`${getAIConfig().aiBaseUrl}${apiBase}/${fileId}/preview`, { headers });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        setPreviewData(data);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Preview failed');
      }
      setLoading(false);
    })();
  }, [open, fileId, apiBase]);

  const ext = (filename || '').split('.').pop()?.toLowerCase() || '';
  const typeLabel = ext.toUpperCase() || 'FILE';

  return (
    <Modal
      open={open}
      footer={null}
      onCancel={onClose}
      width="80vw"
      style={{ maxWidth: '90vw' }}
      styles={{ body: { maxHeight: '75vh', overflow: 'auto' } }}
      centered
      title={
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span>{filename || fileId}</span>
          <Tag color="blue" style={{ fontSize: 11 }}>{typeLabel}</Tag>
          {!hideDownload && (
          <Button
            type="text" size="small" icon={<DownloadOutlined />}
            onClick={async () => {
              const headers = await getAuthHeaders();
              const res = await fetch(`${getAIConfig().aiBaseUrl}${apiBase}/${fileId}/download`, { headers });
              if (res.ok) {
                const blob = await res.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url; a.download = filename || 'download'; a.click();
                URL.revokeObjectURL(url);
              }
            }}
          >下载</Button>
          )}
        </div>
      }
    >
      {loading && <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>}
      {error && <div style={{ textAlign: 'center', padding: 40, color: '#ff4d4f' }}>{error}</div>}
      {previewData && !loading && (
        <UniversalFilePreview previewData={previewData as any} fileId={fileId} hideDownload={hideDownload} />
      )}
    </Modal>
  );
}
