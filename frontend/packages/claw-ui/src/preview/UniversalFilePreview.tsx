/**
 * 统一文件预览组件 — 按文件类型路由到子渲染器。
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { Spin, Table, Button, Tabs } from 'antd';
import { DownloadOutlined, CodeOutlined, EyeOutlined } from '@ant-design/icons';
import { renderAsync } from 'docx-preview';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { getAIConfig } from '@claw/core';
import HighlightedCode from '../shared/HighlightedCode';

interface PreviewData {
  type: string;
  filename?: string;
  url?: string;
  content?: string;
  source?: string;
  render_url?: string;
  language?: string;
  sheets?: Array<{ name: string; headers: string[]; rows: string[][] }>;
  html?: string;
  content_type?: string;
  size_bytes?: number;
}

interface UniversalFilePreviewProps {
  previewData: PreviewData;
  fileId?: string;
  hideDownload?: boolean;
}

/** Get auth headers for fetch requests */
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

function ImagePreview({ url }: { url: string }) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const headers = await getAuthHeaders();
      const res = await fetch(`${getAIConfig().aiBaseUrl}${url}`, { headers });
      if (res.ok && !cancelled) {
        const blob = await res.blob();
        setBlobUrl(URL.createObjectURL(blob));
      }
    })();
    return () => { cancelled = true; if (blobUrl) URL.revokeObjectURL(blobUrl); };
  }, [url]); // eslint-disable-line
  if (!blobUrl) return <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>;
  return <img src={blobUrl} alt="" style={{ maxWidth: '100%', maxHeight: '70vh', objectFit: 'contain', display: 'block', margin: '0 auto' }} />;
}

function PdfPreview({ url, hideDownload }: { url: string; hideDownload?: boolean }) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const headers = await getAuthHeaders();
      const res = await fetch(`${getAIConfig().aiBaseUrl}${url}`, { headers });
      if (res.ok && !cancelled) {
        const blob = await res.blob();
        setBlobUrl(URL.createObjectURL(blob));
      }
    })();
    return () => { cancelled = true; if (blobUrl) URL.revokeObjectURL(blobUrl); };
  }, [url]); // eslint-disable-line
  if (!blobUrl) return <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>;
  const src = hideDownload ? `${blobUrl}#toolbar=0&navpanes=0` : blobUrl;
  return <iframe src={src} style={{ width: '100%', height: '70vh', border: 'none' }} title="PDF Preview" />;
}

function DocxPreview({ url }: { url: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const render = useCallback(async () => {
    if (!containerRef.current) return;
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`${getAIConfig().aiBaseUrl}${url}`, { headers });
      if (!res.ok) { setError(`HTTP ${res.status}`); setLoading(false); return; }
      const blob = await res.blob();
      const arrayBuffer = await blob.arrayBuffer();
      await renderAsync(arrayBuffer, containerRef.current, undefined, {
        className: 'docx-preview-body',
        inWrapper: true,
        ignoreWidth: false,
        ignoreHeight: true,
        ignoreFonts: false,
        breakPages: true,
        ignoreLastRenderedPageBreak: true,
        experimental: false,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'DOCX 渲染失败');
    }
    setLoading(false);
  }, [url]);

  useEffect(() => { render(); }, [render]);

  if (error) return <div style={{ textAlign: 'center', padding: 40, color: '#ff4d4f' }}>{error}</div>;
  return (
    <div style={{ maxHeight: '70vh', overflow: 'auto' }}>
      {loading && <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>}
      <div ref={containerRef} />
    </div>
  );
}

function CodePreview({ content, language }: { content: string; language?: string }) {
  return (
    <HighlightedCode
      code={content}
      language={language}
      showLineNumbers
      maxHeight="70vh"
    />
  );
}

function ExcelPreview({ sheets }: { sheets: Array<{ name: string; headers: string[]; rows: string[][] }> }) {
  if (!sheets || sheets.length === 0) return <div>No data</div>;
  const items = sheets.map((sheet) => ({
    key: sheet.name,
    label: sheet.name,
    children: (
      <Table
        dataSource={sheet.rows.map((row, i) => {
          const record: Record<string, string> = { _key: String(i) };
          sheet.headers.forEach((h, j) => { record[h || `col_${j}`] = row[j] || ''; });
          return record;
        })}
        columns={sheet.headers.map((h, j) => ({
          title: h || `Column ${j + 1}`,
          dataIndex: h || `col_${j}`,
          key: h || `col_${j}`,
          ellipsis: true,
        }))}
        rowKey="_key"
        size="small"
        scroll={{ x: 'max-content', y: 400 }}
        pagination={{ pageSize: 50, showSizeChanger: false }}
      />
    ),
  }));
  return sheets.length === 1 ? <>{items[0].children}</> : <Tabs items={items} />;
}

function SvgPreview({ source, url }: { source: string; url: string }) {
  const [mode, setMode] = useState<'preview' | 'source'>('preview');
  const [blobUrl, setBlobUrl] = useState<string | null>(null);

  useEffect(() => {
    if (mode === 'preview') {
      let cancelled = false;
      (async () => {
        const headers = await getAuthHeaders();
        const res = await fetch(`${getAIConfig().aiBaseUrl}${url}`, { headers });
        if (res.ok && !cancelled) {
          const blob = await res.blob();
          setBlobUrl(URL.createObjectURL(blob));
        }
      })();
      return () => { cancelled = true; if (blobUrl) URL.revokeObjectURL(blobUrl); };
    }
  }, [mode, url]); // eslint-disable-line

  return (
    <div>
      <div style={{ marginBottom: 8, display: 'flex', gap: 8 }}>
        <Button size="small" type={mode === 'preview' ? 'primary' : 'default'} icon={<EyeOutlined />} onClick={() => setMode('preview')}>效果预览</Button>
        <Button size="small" type={mode === 'source' ? 'primary' : 'default'} icon={<CodeOutlined />} onClick={() => setMode('source')}>查看源码</Button>
      </div>
      {mode === 'preview' ? (
        blobUrl ? (
          <div style={{ textAlign: 'center', padding: 20, maxHeight: '60vh', overflow: 'auto', background: '#fafafa', borderRadius: 4, border: '1px solid #e8e8e8' }}>
            <img src={blobUrl} alt="SVG" style={{ maxWidth: '100%', maxHeight: '55vh', objectFit: 'contain' }} />
          </div>
        ) : (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        )
      ) : (
        <CodePreview content={source} language="xml" />
      )}
    </div>
  );
}

function HtmlPreview({ source, renderUrl }: { source: string; renderUrl?: string }) {
  const [mode, setMode] = useState<'preview' | 'source'>('preview');
  const [blobUrl, setBlobUrl] = useState<string | null>(null);

  useEffect(() => {
    if (mode === 'preview' && renderUrl) {
      let cancelled = false;
      (async () => {
        const headers = await getAuthHeaders();
        const res = await fetch(`${getAIConfig().aiBaseUrl}${renderUrl}`, { headers });
        if (res.ok && !cancelled) {
          const blob = await res.blob();
          setBlobUrl(URL.createObjectURL(blob));
        }
      })();
      return () => { cancelled = true; if (blobUrl) URL.revokeObjectURL(blobUrl); };
    }
  }, [mode, renderUrl]); // eslint-disable-line

  return (
    <div>
      <div style={{ marginBottom: 8, display: 'flex', gap: 8 }}>
        <Button size="small" type={mode === 'preview' ? 'primary' : 'default'} icon={<EyeOutlined />} onClick={() => setMode('preview')}>效果预览</Button>
        <Button size="small" type={mode === 'source' ? 'primary' : 'default'} icon={<CodeOutlined />} onClick={() => setMode('source')}>查看源码</Button>
      </div>
      {mode === 'preview' ? (
        blobUrl ? (
          <iframe src={blobUrl} sandbox="allow-scripts" style={{ width: '100%', height: '60vh', border: '1px solid #e8e8e8', borderRadius: 4 }} title="HTML Preview" />
        ) : (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        )
      ) : (
        <CodePreview content={source} language="html" />
      )}
    </div>
  );
}

export default function UniversalFilePreview({ previewData, fileId, hideDownload }: UniversalFilePreviewProps) {
  const { type } = previewData;

  if (type === 'image') return <ImagePreview url={previewData.url!} />;
  if (type === 'svg') return <SvgPreview source={previewData.source || ''} url={previewData.url!} />;
  if (type === 'pdf') return <PdfPreview url={previewData.url!} hideDownload={hideDownload} />;
  if (type === 'docx') return <DocxPreview url={previewData.url!} />;
  if (type === 'excel') return <ExcelPreview sheets={previewData.sheets || []} />;
  if (type === 'code') return <CodePreview content={previewData.content || ''} language={previewData.language} />;
  if (type === 'markdown') return <div className="prose" style={{ maxWidth: 'none', maxHeight: '70vh', overflow: 'auto' }}><Markdown remarkPlugins={[remarkGfm]}>{previewData.content || ''}</Markdown></div>;
  if (type === 'html') return <HtmlPreview source={previewData.source || ''} renderUrl={previewData.render_url} />;
  if (type === 'text') return <CodePreview content={previewData.content || ''} />;

  // Unsupported
  return (
    <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>
      <div style={{ fontSize: 48, marginBottom: 12 }}>📄</div>
      <div>该文件类型不支持预览</div>
      <div style={{ fontSize: 12, color: '#bfbfbf', marginTop: 4 }}>{previewData.content_type} · {previewData.size_bytes} bytes</div>
      {fileId && (
        <Button type="link" style={{ marginTop: 8 }} icon={<DownloadOutlined />}
          onClick={async () => {
            const headers = await getAuthHeaders();
            const res = await fetch(`${getAIConfig().aiBaseUrl}/api/files/${fileId}/download`, { headers });
            if (res.ok) {
              const blob = await res.blob();
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url; a.download = previewData.filename || 'download'; a.click();
              URL.revokeObjectURL(url);
            }
          }}
        >下载文件</Button>
      )}
    </div>
  );
}
