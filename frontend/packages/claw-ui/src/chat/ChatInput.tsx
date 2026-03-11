import { useRef, useCallback, useState } from 'react';
import { Input, Button, Switch, Typography, Tag, message } from 'antd';
import { SendOutlined, PaperClipOutlined, CloseOutlined } from '@ant-design/icons';
import { aiApi, type FileInfo } from '@claw/core';
const { uploadFile } = aiApi;

const { TextArea } = Input;
const { Text } = Typography;

export interface AttachedFile {
  fileId: string;
  filename: string;
}

interface ChatInputProps {
  onSend: (message: string, files?: AttachedFile[]) => void;
  disabled?: boolean;
  placeholder?: string;
  showThinking?: boolean;
  onShowThinkingChange?: (v: boolean) => void;
}

/**
 * 聊天输入框 — 参考图风格。
 * 大输入区 + "展示思考" 开关 + 附件按钮 + 发送按钮。
 * Enter 发送 / Shift+Enter 换行 / Pipeline 运行中禁用。
 */
export default function ChatInput({
  onSend,
  disabled = false,
  placeholder = '请输入您的问题',
  showThinking = false,
  onShowThinkingChange,
}: ChatInputProps) {
  const [value, setValue] = useState('');
  const [attachedFiles, setAttachedFiles] = useState<AttachedFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed, attachedFiles.length > 0 ? attachedFiles : undefined);
    setValue('');
    setAttachedFiles([]);
    setTimeout(() => textareaRef.current?.focus(), 50);
  }, [value, disabled, onSend, attachedFiles]);

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
        // 前端也检查文件大小
        if (file.size > 10 * 1024 * 1024) {
          message.error(`文件 ${file.name} 太大 (超过 10MB)`);
          continue;
        }
        const result: FileInfo = await uploadFile(file);
        setAttachedFiles(prev => [...prev, {
          fileId: result.file_id,
          filename: result.filename,
        }]);
        message.success(`${result.filename} 上传成功`);
      }
    } catch (err) {
      message.error(`文件上传失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setUploading(false);
      // 重置 input 以允许重复选择同一文件
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
        accept=".txt,.csv,.json,.xml,.yaml,.yml,.md,.pdf,.doc,.docx,.xls,.xlsx,.png,.jpg,.jpeg,.gif,.bmp,.webp,.zip,.tar,.gz"
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

      <TextArea
        ref={textareaRef as React.Ref<never>}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={disabled}
        autoSize={{ minRows: 2, maxRows: 5 }}
        style={{
          border: 'none',
          boxShadow: 'none',
          resize: 'none',
          padding: '8px 0',
          fontSize: 14,
        }}
      />
      <div className="chat-input-toolbar">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Switch
            size="small"
            checked={showThinking}
            onChange={(v) => onShowThinkingChange?.(v)}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>展示思考</Text>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Button
            type="text"
            size="small"
            icon={<PaperClipOutlined />}
            disabled={disabled || uploading}
            loading={uploading}
            onClick={() => fileInputRef.current?.click()}
            style={{ color: '#999' }}
            title="上传附件"
          />
          <Button
            type="primary"
            shape="circle"
            icon={<SendOutlined />}
            onClick={handleSend}
            disabled={disabled || !value.trim()}
            size="small"
          />
        </div>
      </div>
      {disabled && (
        <div style={{ fontSize: 11, color: '#999', textAlign: 'center', paddingBottom: 4 }}>
          AI 正在处理中，请稍候...
        </div>
      )}
    </div>
  );
}
