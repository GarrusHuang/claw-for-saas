import { useState } from 'react';
import { Card, Tag, Typography } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
  DownOutlined,
  RightOutlined,
} from '@ant-design/icons';
import type { AuditItem, AuditSummary } from '@claw/core';

const { Text } = Typography;

interface AuditResultCardProps {
  auditSummary: AuditSummary;
  title?: string;
}

const STATUS_CONFIG: Record<
  AuditItem['status'],
  { color: string; bgColor: string; borderColor: string; icon: typeof CheckCircleOutlined; label: string }
> = {
  pass: { color: '#52c41a', bgColor: '#f6ffed', borderColor: '#b7eb8f', icon: CheckCircleOutlined, label: '通过' },
  fail: { color: '#ff4d4f', bgColor: '#fff2f0', borderColor: '#ffccc7', icon: CloseCircleOutlined, label: '不通过' },
  warning: { color: '#faad14', bgColor: '#fffbe6', borderColor: '#ffe58f', icon: WarningOutlined, label: '警告' },
};

function AuditRuleItem({ item }: { item: AuditItem }) {
  const cfg = STATUS_CONFIG[item.status];
  const Icon = cfg.icon;
  const [expanded, setExpanded] = useState(item.status !== 'pass');

  return (
    <div
      style={{
        border: `1px solid ${cfg.borderColor}`,
        borderRadius: 6,
        marginBottom: 8,
        background: cfg.bgColor,
        overflow: 'hidden',
      }}
    >
      <div
        role="button"
        tabIndex={0}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 12px',
          cursor: 'pointer',
        }}
        onClick={() => setExpanded(!expanded)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded(!expanded); } }}
      >
        <Icon style={{ color: cfg.color, fontSize: 14 }} />
        <Text strong style={{ fontSize: 12, flex: 1 }}>{item.ruleId}</Text>
        <Tag
          color={item.status === 'pass' ? 'green' : item.status === 'fail' ? 'red' : 'orange'}
          style={{ fontSize: 10, lineHeight: '18px' }}
        >
          {cfg.label}
        </Tag>
        {expanded
          ? <DownOutlined style={{ fontSize: 10, color: '#999' }} />
          : <RightOutlined style={{ fontSize: 10, color: '#999' }} />}
      </div>
      {expanded && (
        <div style={{ padding: '0 12px 10px 34px', fontSize: 12, color: '#333', lineHeight: 1.6 }}>
          {item.message}
        </div>
      )}
    </div>
  );
}

const STATUS_ORDER: Record<AuditItem['status'], number> = { fail: 0, warning: 1, pass: 2 };

export default function AuditResultCard({
  auditSummary,
  title = '审计结果',
}: AuditResultCardProps) {
  const total = auditSummary.results.length;
  const sorted = [...auditSummary.results].sort(
    (a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status],
  );

  return (
    <div className="animate-fade-in">
      <Card
        title={<span style={{ fontSize: 13 }}>🔍 {title}</span>}
        size="small"
        className="mb-4"
      >
        {sorted.map((item, i) => (
          <AuditRuleItem key={`${item.ruleId}-${i}`} item={item} />
        ))}

        {/* ── Summary bar ── */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginTop: 4,
            padding: '8px 12px',
            background: '#fafafa',
            borderRadius: 6,
            fontSize: 12,
          }}
        >
          <Text type="secondary">{total} 项检查</Text>
          <div style={{ display: 'flex', gap: 12 }}>
            {auditSummary.passCount > 0 && (
              <span style={{ color: '#52c41a' }}>
                <CheckCircleOutlined style={{ marginRight: 3 }} />
                {auditSummary.passCount} 通过
              </span>
            )}
            {auditSummary.warningCount > 0 && (
              <span style={{ color: '#faad14' }}>
                <WarningOutlined style={{ marginRight: 3 }} />
                {auditSummary.warningCount} 警告
              </span>
            )}
            {auditSummary.failCount > 0 && (
              <span style={{ color: '#ff4d4f' }}>
                <CloseCircleOutlined style={{ marginRight: 3 }} />
                {auditSummary.failCount} 不通过
              </span>
            )}
          </div>
        </div>

        {auditSummary.conclusion && (
          <div style={{ marginTop: 8, fontSize: 12 }}>
            <Text strong>结论: </Text>
            <Text>{auditSummary.conclusion}</Text>
          </div>
        )}
      </Card>
    </div>
  );
}
