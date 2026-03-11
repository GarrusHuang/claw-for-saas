/**
 * InlineUploader — 内联文件上传控件 (Phase 24A)。
 *
 * Agent 通过 SSE `request_upload` 事件请求用户上传文件时,
 * 在聊天消息流中渲染拖拽上传区域。
 *
 * - 支持拖拽 + 点击选择
 * - 已上传文件展示为 Tag 列表
 * - 上传完成后点击"提交"将文件发送给 Agent
 * - 提交后变为只读态
 */

import { useState, useRef, useCallback } from 'react';
import { Button, Tag, Typography, message } from 'antd';
import {
  CloudUploadOutlined,
  PaperClipOutlined,
  CloseOutlined,
  CheckOutlined,
  InboxOutlined,
} from '@ant-design/icons';
import { aiApi, type FileInfo } from '@claw/core';
const { uploadFile } = aiApi;

const { Text } = Typography;

interface UploadedFile {
  fileId: string;
  filename: string;
}

interface InlineUploaderProps {
  prompt: string;
  accept: string;
  onSubmit: (files: UploadedFile[]) => void;
  resolved?: boolean;
}

export default function InlineUploader({
  prompt,
  accept,
  onSubmit,
  resolved = false,
}: InlineUploaderProps) {
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [submitted, setSubmitted] = useState(resolved);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const acceptTypes = accept === '*' ? undefined : accept;

  const handleUpload = useCallback(async (fileList: FileList) => {
    setUploading(true);
    try {
      for (const file of Array.from(fileList)) {
        if (file.size > 10 * 1024 * 1024) {
          message.error(`文件 ${file.name} 太大 (超过 10MB)`);
          continue;
        }
        const result: FileInfo = await uploadFile(file);
        setFiles((prev) => [...prev, { fileId: result.file_id, filename: result.filename }]);
      }
    } catch (err) {
      message.error(`上传失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setUploading(false);
    }
  }, []);

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files.length > 0) {
        handleUpload(e.target.files);
      }
      if (fileInputRef.current) fileInputRef.current.value = '';
    },
    [handleUpload],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (e.dataTransfer.files.length > 0) {
        handleUpload(e.dataTransfer.files);
      }
    },
    [handleUpload],
  );

  const removeFile = useCallback((fileId: string) => {
    setFiles((prev) => prev.filter((f) => f.fileId !== fileId));
  }, []);

  const handleSubmit = useCallback(() => {
    if (files.length === 0) return;
    setSubmitted(true);
    onSubmit(files);
  }, [files, onSubmit]);

  // ── 已提交: 只读文件列表 ──
  if (submitted) {
    return (
      <div className="inline-uploader inline-uploader--resolved">
        <div className="inline-uploader-header">
          <CheckOutlined style={{ color: '#52c41a', fontSize: 12 }} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            已上传 {files.length} 个文件
          </Text>
        </div>
        <div className="inline-uploader-files">
          {files.map((f) => (
            <Tag key={f.fileId} icon={<PaperClipOutlined />} style={{ fontSize: 11 }}>
              {f.filename}
            </Tag>
          ))}
        </div>
      </div>
    );
  }

  // ── 上传中: 拖拽区域 + 文件列表 ──
  return (
    <div className="inline-uploader animate-fade-in">
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={acceptTypes}
        style={{ display: 'none' }}
        onChange={handleFileSelect}
      />

      {/* 提示文字 */}
      <div className="inline-uploader-header">
        <CloudUploadOutlined style={{ color: '#1890ff', fontSize: 14 }} />
        <Text style={{ fontSize: 13 }}>{prompt}</Text>
      </div>

      {/* 拖拽区域 */}
      <div
        className={`inline-uploader-dropzone ${dragging ? 'inline-uploader-dropzone--active' : ''}`}
        onClick={() => fileInputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
      >
        <InboxOutlined style={{ fontSize: 28, color: dragging ? '#1890ff' : '#bbb' }} />
        <Text type="secondary" style={{ fontSize: 12 }}>
          {uploading ? '正在上传...' : '拖拽文件到此处，或点击选择'}
        </Text>
        {accept !== '*' && (
          <Text type="secondary" style={{ fontSize: 10 }}>
            支持格式: {accept}
          </Text>
        )}
      </div>

      {/* 已上传文件列表 */}
      {files.length > 0 && (
        <div className="inline-uploader-files">
          {files.map((f) => (
            <Tag
              key={f.fileId}
              closable
              onClose={() => removeFile(f.fileId)}
              closeIcon={<CloseOutlined style={{ fontSize: 10 }} />}
              icon={<PaperClipOutlined />}
              style={{ fontSize: 11 }}
            >
              {f.filename}
            </Tag>
          ))}
        </div>
      )}

      {/* 提交按钮 */}
      {files.length > 0 && (
        <div className="inline-uploader-actions">
          <Button
            type="primary"
            size="small"
            icon={<CheckOutlined />}
            onClick={handleSubmit}
            loading={uploading}
            style={{ fontSize: 12, borderRadius: 4 }}
          >
            提交 {files.length} 个文件
          </Button>
        </div>
      )}
    </div>
  );
}
