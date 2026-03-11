/**
 * DiffBlock — 单个 diff 区块 (Accept / Reject 控制)。
 *
 * Phase 23A: 合同条款级别的 diff 展示。
 * 每个区块对应合同的一个条款/段落。
 * - unchanged: 灰色折叠态
 * - modified: 左右对比高亮
 * - added: 绿色高亮
 * - removed: 红色高亮
 */

import { useState } from 'react';
import { Typography, Button, Tooltip } from 'antd';
import {
  CheckOutlined,
  CloseOutlined,
  DownOutlined,
  RightOutlined,
  SwapOutlined,
} from '@ant-design/icons';

const { Text } = Typography;

export type DiffType = 'unchanged' | 'modified' | 'added' | 'removed';
export type DiffDecision = 'pending' | 'accepted' | 'rejected';

export interface DiffSection {
  id: string;
  title: string;
  original: string;
  modified: string;
  type: DiffType;
  annotation?: string;
}

interface DiffBlockProps {
  section: DiffSection;
  decision: DiffDecision;
  onAccept: (id: string) => void;
  onReject: (id: string) => void;
}

export default function DiffBlock({ section, decision, onAccept, onReject }: DiffBlockProps) {
  const [expanded, setExpanded] = useState(section.type !== 'unchanged');

  const isUnchanged = section.type === 'unchanged';
  const isModified = section.type === 'modified';
  const isAdded = section.type === 'added';
  const isRemoved = section.type === 'removed';

  const borderColor =
    decision === 'accepted' ? '#52c41a'
    : decision === 'rejected' ? '#ff4d4f'
    : isModified ? '#faad14'
    : isAdded ? '#52c41a'
    : isRemoved ? '#ff4d4f'
    : '#e8e8e8';

  const bgColor =
    decision === 'accepted' ? '#f6ffed'
    : decision === 'rejected' ? '#fff2f0'
    : 'transparent';

  return (
    <div
      className="diff-block"
      style={{
        borderLeft: `3px solid ${borderColor}`,
        background: bgColor,
        borderRadius: 4,
        marginBottom: 8,
        transition: 'all 0.2s ease',
      }}
    >
      {/* Header */}
      <div
        className="diff-block-header"
        onClick={() => setExpanded((v) => !v)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 12px',
          cursor: 'pointer',
          userSelect: 'none',
        }}
      >
        <span style={{ fontSize: 10, color: '#999' }}>
          {expanded ? <DownOutlined /> : <RightOutlined />}
        </span>
        <Text strong style={{ fontSize: 12, flex: 1 }}>
          {section.title}
        </Text>
        {!isUnchanged && (
          <span
            className="diff-block-type-tag"
            style={{
              fontSize: 10,
              padding: '1px 6px',
              borderRadius: 3,
              background: isModified ? '#fff7e6' : isAdded ? '#f6ffed' : '#fff2f0',
              color: isModified ? '#d48806' : isAdded ? '#389e0d' : '#cf1322',
            }}
          >
            {isModified ? '已修改' : isAdded ? '新增' : '已删除'}
          </span>
        )}
        {decision !== 'pending' && (
          <span
            style={{
              fontSize: 10,
              padding: '1px 6px',
              borderRadius: 3,
              background: decision === 'accepted' ? '#f6ffed' : '#fff2f0',
              color: decision === 'accepted' ? '#389e0d' : '#cf1322',
              fontWeight: 600,
            }}
          >
            {decision === 'accepted' ? '已采纳' : '已拒绝'}
          </span>
        )}
      </div>

      {/* Body */}
      {expanded && (
        <div style={{ padding: '0 12px 10px' }}>
          {/* Annotation (from audit results) */}
          {section.annotation && (
            <div
              style={{
                background: '#fffbe6',
                border: '1px solid #ffe58f',
                borderRadius: 4,
                padding: '6px 10px',
                marginBottom: 8,
                fontSize: 11,
                color: '#ad6800',
                lineHeight: 1.6,
              }}
            >
              {section.annotation}
            </div>
          )}

          {/* Diff Content */}
          {isUnchanged ? (
            <pre className="diff-block-content diff-block-content--unchanged">
              {section.original}
            </pre>
          ) : isModified ? (
            <div className="diff-block-compare">
              <div className="diff-block-side diff-block-side--original">
                <div className="diff-block-side-label">原文</div>
                <pre className="diff-block-content diff-block-content--removed">
                  {section.original}
                </pre>
              </div>
              <div className="diff-block-side-divider">
                <SwapOutlined style={{ fontSize: 10, color: '#bbb' }} />
              </div>
              <div className="diff-block-side diff-block-side--modified">
                <div className="diff-block-side-label">修改</div>
                <pre className="diff-block-content diff-block-content--added">
                  {section.modified}
                </pre>
              </div>
            </div>
          ) : isAdded ? (
            <pre className="diff-block-content diff-block-content--added">
              {section.modified}
            </pre>
          ) : (
            <pre className="diff-block-content diff-block-content--removed">
              {section.original}
            </pre>
          )}

          {/* Accept / Reject Buttons */}
          {!isUnchanged && (
            <div style={{ display: 'flex', gap: 8, marginTop: 8, justifyContent: 'flex-end' }}>
              <Tooltip title="采纳此修改">
                <Button
                  size="small"
                  type={decision === 'accepted' ? 'primary' : 'default'}
                  icon={<CheckOutlined />}
                  onClick={(e) => { e.stopPropagation(); onAccept(section.id); }}
                  style={{
                    fontSize: 11,
                    borderRadius: 4,
                    ...(decision === 'accepted' ? { background: '#52c41a', borderColor: '#52c41a' } : {}),
                  }}
                >
                  采纳
                </Button>
              </Tooltip>
              <Tooltip title="拒绝此修改">
                <Button
                  size="small"
                  danger={decision === 'rejected'}
                  type={decision === 'rejected' ? 'primary' : 'default'}
                  icon={<CloseOutlined />}
                  onClick={(e) => { e.stopPropagation(); onReject(section.id); }}
                  style={{ fontSize: 11, borderRadius: 4 }}
                >
                  拒绝
                </Button>
              </Tooltip>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
