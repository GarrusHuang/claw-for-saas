/**
 * 知识库管理视图 — 共享知识 + 我的知识。
 */
import { useState, useEffect, useCallback } from 'react';
import { Button, Spin, Empty, Popconfirm, Tag, message, Upload } from 'antd';
import {
  UploadOutlined, DeleteOutlined, GlobalOutlined,
  UserOutlined, FileOutlined, FilePdfOutlined,
  FileWordOutlined, FileExcelOutlined, FileImageOutlined,
} from '@ant-design/icons';
import { aiApi } from '@claw/core';
import type { KBFileInfo } from '@claw/core';

const { listKnowledgeFiles, uploadKnowledgeFile, deleteKnowledgeFile } = aiApi;

function getKBFileIcon(filename: string) {
  const ext = filename.split('.').pop()?.toLowerCase() || '';
  if (['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'svg'].includes(ext)) return <FileImageOutlined style={{ color: '#1890ff' }} />;
  if (ext === 'pdf') return <FilePdfOutlined style={{ color: '#ff4d4f' }} />;
  if (['doc', 'docx'].includes(ext)) return <FileWordOutlined style={{ color: '#2f54eb' }} />;
  if (['xls', 'xlsx', 'csv'].includes(ext)) return <FileExcelOutlined style={{ color: '#52c41a' }} />;
  return <FileOutlined style={{ color: '#8c8c8c' }} />;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function KnowledgeView() {
  const [files, setFiles] = useState<KBFileInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [previewFileId, setPreviewFileId] = useState<string | null>(null);
  const [previewFilename, setPreviewFilename] = useState<string>('');

  const fetchFiles = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listKnowledgeFiles();
      setFiles(data.files);
    } catch (err) {
      console.error('Failed to load KB files:', err);
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchFiles(); }, []); // eslint-disable-line

  const handleUpload = useCallback(async (file: File) => {
    setUploading(true);
    try {
      await uploadKnowledgeFile(file, 'user', '');
      message.success(`${file.name} 上传成功`);
      fetchFiles();
    } catch (err) {
      message.error(`上传失败: ${err instanceof Error ? err.message : '未知错误'}`);
    }
    setUploading(false);
    return false; // Prevent default upload
  }, [fetchFiles]);

  const handleDelete = useCallback(async (fileId: string) => {
    try {
      await deleteKnowledgeFile(fileId);
      message.success('已删除');
      fetchFiles();
    } catch (err) {
      message.error(`删除失败: ${err instanceof Error ? err.message : '未知错误'}`);
    }
  }, [fetchFiles]);

  const globalFiles = files.filter(f => f.scope === 'global');
  const userFiles = files.filter(f => f.scope === 'user');

  // Dynamically import FilePreviewModal to avoid circular deps
  const [FilePreviewModal, setFilePreviewModal] = useState<any>(null);
  useEffect(() => {
    import('../preview/FilePreviewModal').then(m => setFilePreviewModal(() => m.default)).catch(() => {});
  }, []);

  return (
    <div style={{ padding: '20px 24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>知识库</h2>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: '#8c8c8c' }}>
            上传参考文档，AI 会在对话中自动引用
          </p>
        </div>
        <Upload
          showUploadList={false}
          beforeUpload={handleUpload}
          multiple
        >
          <Button type="primary" icon={<UploadOutlined />} loading={uploading}>
            上传文件
          </Button>
        </Upload>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>
      ) : files.length === 0 ? (
        <Empty description="暂无知识文件" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ marginTop: 60 }} />
      ) : (
        <>
          {/* 共享知识 */}
          {globalFiles.length > 0 && (
            <div style={{ marginBottom: 24 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12, fontSize: 14, fontWeight: 500, color: '#595959' }}>
                <GlobalOutlined /> 共享知识
                <Tag color="blue" style={{ fontSize: 11 }}>{globalFiles.length}</Tag>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 10 }}>
                {globalFiles.map(f => (
                  <div
                    key={f.file_id}
                    style={{
                      padding: '10px 14px', border: '1px solid #e8e8e8',
                      borderRadius: 8, cursor: 'pointer', transition: 'all 0.15s',
                      background: '#fafafa',
                    }}
                    onClick={() => { setPreviewFileId(f.file_id); setPreviewFilename(f.filename); }}
                    onMouseEnter={e => { e.currentTarget.style.borderColor = '#91d5ff'; e.currentTarget.style.background = '#f0f7ff'; }}
                    onMouseLeave={e => { e.currentTarget.style.borderColor = '#e8e8e8'; e.currentTarget.style.background = '#fafafa'; }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 20 }}>{getKBFileIcon(f.filename)}</span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 500, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.filename}</div>
                        <div style={{ fontSize: 11, color: '#bfbfbf' }}>{formatSize(f.size_bytes)}</div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 我的知识 */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12, fontSize: 14, fontWeight: 500, color: '#595959' }}>
              <UserOutlined /> 我的知识
              <Tag color="green" style={{ fontSize: 11 }}>{userFiles.length}</Tag>
            </div>
            {userFiles.length === 0 ? (
              <Empty description="暂无个人知识文件" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 10 }}>
                {userFiles.map(f => (
                  <div
                    key={f.file_id}
                    style={{
                      padding: '10px 14px', border: '1px solid #e8e8e8',
                      borderRadius: 8, cursor: 'pointer', transition: 'all 0.15s',
                    }}
                    onClick={() => { setPreviewFileId(f.file_id); setPreviewFilename(f.filename); }}
                    onMouseEnter={e => { e.currentTarget.style.borderColor = '#91d5ff'; e.currentTarget.style.background = '#f0f7ff'; }}
                    onMouseLeave={e => { e.currentTarget.style.borderColor = '#e8e8e8'; e.currentTarget.style.background = '#fff'; }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 20 }}>{getKBFileIcon(f.filename)}</span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 500, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.filename}</div>
                        <div style={{ fontSize: 11, color: '#bfbfbf' }}>{formatSize(f.size_bytes)}</div>
                      </div>
                      <Popconfirm title="确定删除?" onConfirm={e => { e?.stopPropagation(); handleDelete(f.file_id); }} onCancel={e => e?.stopPropagation()} okText="删除" cancelText="取消" okButtonProps={{ danger: true, size: 'small' }}>
                        <DeleteOutlined style={{ color: '#ff4d4f', fontSize: 14 }} onClick={e => e.stopPropagation()} />
                      </Popconfirm>
                    </div>
                    {f.description && <div style={{ fontSize: 11, color: '#8c8c8c', marginTop: 4 }}>{f.description}</div>}
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {/* Preview Modal */}
      {FilePreviewModal && previewFileId && (
        <FilePreviewModal
          open={!!previewFileId}
          fileId={previewFileId}
          filename={previewFilename}
          onClose={() => setPreviewFileId(null)}
          apiBase="/api/knowledge"
        />
      )}
    </div>
  );
}
