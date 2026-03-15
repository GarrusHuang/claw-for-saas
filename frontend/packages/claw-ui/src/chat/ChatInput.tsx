import { useRef, useCallback, useState } from 'react';
import { Input, Button, message } from 'antd';
import type { InputRef } from 'antd';
import { SendOutlined, PlusOutlined, BorderOutlined } from '@ant-design/icons';
import { aiApi, usePipelineStore, type FileInfo } from '@claw/core';
import FilePreviewModal from '../preview/FilePreviewModal';
import FileCard from './FileCard';
import type { FileCardFile } from './FileCard';
const { uploadFile } = aiApi;

const { TextArea } = Input;

export interface AttachedFile {
  fileId: string;
  filename: string;
  contentType?: string;
  sizeBytes?: number;
}

interface ChatInputProps {
  onSend: (message: string, files?: AttachedFile[]) => void;
  onStop?: () => void;
  disabled?: boolean;
  placeholder?: string;
  sessionId?: string;
}

/**
 * 聊天输入框 — 文档流风格。
 * [+] [TextArea] [Send] 水平排列。
 * Enter 发送 / Shift+Enter 换行 / Pipeline 运行中禁用。
 */
export default function ChatInput({
  onSend,
  onStop,
  disabled = false,
  placeholder = '回复...',
  sessionId,
}: ChatInputProps) {
  const [value, setValue] = useState('');
  const [attachedFiles, setAttachedFiles] = useState<AttachedFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [previewFile, setPreviewFile] = useState<AttachedFile | null>(null);
  const textareaRef = useRef<InputRef>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed) return;
    onSend(trimmed, attachedFiles.length > 0 ? attachedFiles : undefined);
    setValue('');
    setAttachedFiles([]);
    setTimeout(() => textareaRef.current?.focus(), 50);
  }, [value, onSend, attachedFiles]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const handleFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        // 实时读取 store 中的 sessionId，避免闭包过期
        const currentSessionId = usePipelineStore.getState().sessionId;
        const result: FileInfo = await uploadFile(file, undefined, currentSessionId || undefined);
        setAttachedFiles(prev => [...prev, {
          fileId: result.file_id,
          filename: result.filename,
          contentType: result.content_type,
          sizeBytes: result.size_bytes,
        }]);
        message.success(`${result.filename} 上传成功`);
      }
    } catch (err) {
      message.error(`文件上传失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  }, []);

  const removeFile = useCallback((fileId: string) => {
    setAttachedFiles(prev => prev.filter(f => f.fileId !== fileId));
  }, []);

  return (
    <div className="chat-input-area">
      {/* 隐藏的文件输入 */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        style={{ display: 'none' }}
        onChange={handleFileSelect}
        accept=".txt,.csv,.json,.xml,.yaml,.yml,.md,.pdf,.doc,.docx,.xls,.xlsx,.png,.jpg,.jpeg,.gif,.bmp,.webp,.zip,.tar,.gz,.svg,.html,.jsx,.tsx,.py,.js,.ts,.css,.scss"
      />

      {/* 文件卡片 */}
      {attachedFiles.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, padding: '8px 12px 0' }}>
          {attachedFiles.map(f => (
            <FileCard
              key={f.fileId}
              file={f}
              compact
              onPreview={(file) => setPreviewFile(file as AttachedFile)}
              onRemove={removeFile}
            />
          ))}
        </div>
      )}

      {/* [+] [TextArea] [Send] 水平排列 */}
      <div className="chat-input-row">
        <Button
          type="text"
          shape="circle"
          size="small"
          icon={<PlusOutlined />}
          disabled={disabled || uploading}
          loading={uploading}
          onClick={() => fileInputRef.current?.click()}
          title="上传附件"
          style={{ color: '#999', flexShrink: 0 }}
        />
        <TextArea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          autoSize={{ minRows: 1, maxRows: 4 }}
          style={{
            border: 'none',
            boxShadow: 'none',
            resize: 'none',
            padding: '6px 0',
            fontSize: 14,
            flex: 1,
          }}
        />
        {disabled && onStop && !value.trim() ? (
          <Button
            type="primary"
            shape="circle"
            icon={<BorderOutlined />}
            onClick={onStop}
            size="small"
            danger
            style={{ flexShrink: 0 }}
          />
        ) : (
          <Button
            type="primary"
            shape="circle"
            icon={<SendOutlined />}
            onClick={handleSend}
            disabled={!value.trim()}
            size="small"
            style={{ flexShrink: 0 }}
          />
        )}
      </div>

      {/* 文件预览 Modal */}
      {previewFile && (
        <FilePreviewModal
          open={!!previewFile}
          fileId={previewFile.fileId}
          filename={previewFile.filename}
          onClose={() => setPreviewFile(null)}
        />
      )}
    </div>
  );
}
