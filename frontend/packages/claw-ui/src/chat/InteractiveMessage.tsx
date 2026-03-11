/**
 * InteractiveMessage — Agent 发起的交互式消息 (Phase 24B)。
 *
 * 根据交互类型渲染不同控件:
 * - confirmation: 按钮组 (用户选择一个选项)
 * - input: 内联输入框 + 提交按钮
 *
 * 用户操作后触发 onRespond 回调，将响应作为下一轮消息发送。
 */

import { useState, useCallback } from 'react';
import { Button, Input, Typography } from 'antd';
import {
  QuestionCircleOutlined,
  CheckOutlined,
  EditOutlined,
  SendOutlined,
} from '@ant-design/icons';
import type { InteractionOption } from '@claw/core';

const { Text } = Typography;

// ── Confirmation 交互 ──

interface ConfirmationProps {
  message: string;
  options: InteractionOption[];
  onRespond: (value: string) => void;
  resolved?: boolean;
  resolvedValue?: string;
}

function ConfirmationInteraction({
  message: msg,
  options,
  onRespond,
  resolved = false,
  resolvedValue,
}: ConfirmationProps) {
  const [selected, setSelected] = useState<string | null>(resolvedValue || null);

  const handleSelect = useCallback(
    (value: string) => {
      if (resolved) return;
      setSelected(value);
      onRespond(value);
    },
    [resolved, onRespond],
  );

  return (
    <div className="interactive-message interactive-message--confirmation animate-fade-in">
      <div className="interactive-message-header">
        <QuestionCircleOutlined style={{ color: '#faad14', fontSize: 14 }} />
        <Text style={{ fontSize: 13 }}>{msg}</Text>
      </div>
      <div className="interactive-message-options">
        {options.map((opt) => {
          const isSelected = selected === opt.value;
          return (
            <Button
              key={opt.value}
              type={isSelected ? 'primary' : 'default'}
              size="small"
              disabled={resolved && !isSelected}
              onClick={() => handleSelect(opt.value)}
              icon={isSelected ? <CheckOutlined /> : undefined}
              style={{
                fontSize: 12,
                borderRadius: 6,
                ...(isSelected && resolved
                  ? { background: '#52c41a', borderColor: '#52c41a' }
                  : {}),
              }}
            >
              {opt.label}
            </Button>
          );
        })}
      </div>
    </div>
  );
}

// ── Input 交互 ──

interface InputInteractionProps {
  prompt: string;
  fieldType: string;
  onRespond: (value: string) => void;
  resolved?: boolean;
  resolvedValue?: string;
}

function InputInteraction({
  prompt,
  onRespond,
  resolved = false,
  resolvedValue,
}: InputInteractionProps) {
  const [value, setValue] = useState(resolvedValue || '');
  const [submitted, setSubmitted] = useState(resolved);

  const handleSubmit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || submitted) return;
    setSubmitted(true);
    onRespond(trimmed);
  }, [value, submitted, onRespond]);

  if (submitted) {
    return (
      <div className="interactive-message interactive-message--input interactive-message--resolved animate-fade-in">
        <div className="interactive-message-header">
          <CheckOutlined style={{ color: '#52c41a', fontSize: 12 }} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            已回复: {value}
          </Text>
        </div>
      </div>
    );
  }

  return (
    <div className="interactive-message interactive-message--input animate-fade-in">
      <div className="interactive-message-header">
        <EditOutlined style={{ color: '#1890ff', fontSize: 14 }} />
        <Text style={{ fontSize: 13 }}>{prompt}</Text>
      </div>
      <div className="interactive-message-input-row">
        <Input
          size="small"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onPressEnter={handleSubmit}
          placeholder="请输入..."
          style={{ flex: 1, fontSize: 12 }}
        />
        <Button
          type="primary"
          size="small"
          icon={<SendOutlined />}
          onClick={handleSubmit}
          disabled={!value.trim()}
          style={{ fontSize: 12, borderRadius: 4 }}
        />
      </div>
    </div>
  );
}

// ── 主组件: 根据 type 分发 ──

interface InteractiveMessageProps {
  type: 'confirmation' | 'input';
  // Confirmation
  message?: string;
  options?: InteractionOption[];
  // Input
  prompt?: string;
  fieldType?: string;
  // Common
  onRespond: (value: string) => void;
  resolved?: boolean;
  resolvedValue?: string;
}

export default function InteractiveMessage({
  type,
  message: msg,
  options,
  prompt,
  fieldType,
  onRespond,
  resolved,
  resolvedValue,
}: InteractiveMessageProps) {
  if (type === 'confirmation') {
    return (
      <ConfirmationInteraction
        message={msg || '请确认'}
        options={options || []}
        onRespond={onRespond}
        resolved={resolved}
        resolvedValue={resolvedValue}
      />
    );
  }

  return (
    <InputInteraction
      prompt={prompt || '请输入'}
      fieldType={fieldType || 'text'}
      onRespond={onRespond}
      resolved={resolved}
      resolvedValue={resolvedValue}
    />
  );
}
