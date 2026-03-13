import { useRef, useCallback, useState } from 'react';
import { Input, Button, Tag, message } from 'antd';
import type { InputRef } from 'antd';
import { SendOutlined, PaperClipOutlined, CloseOutlined, PlusOutlined, BorderOutlined } from '@ant-design/icons';
import { aiApi, type FileInfo } from '@claw/core';
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
        const result: FileInfo = await uploadFile(file, undefined, sessionId);
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

      {/* 文件 chips */}
      {attachedFiles.length > 0 && (
        <div className="chat-attached-files">
          {attachedFiles.map(f => (
            <Tag
              key={f.fileId}
              closable
              onClose={() => removeFile(f.fileId)}
              closeIcon={<CloseOutlined style={{ fontSize: 10 }} />}
              style={{ marginBottom: 4 }}
            >
              <PaperClipOutlined style={{ marginRight: 4 }} />
              {f.filename}
            </Tag>
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
    </div>
  );
}
