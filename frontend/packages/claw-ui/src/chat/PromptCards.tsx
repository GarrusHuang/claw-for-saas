import { Typography, Tag } from 'antd';
import {
  FileTextOutlined,
  AuditOutlined,
  SolutionOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import { getAllScenarios, type ScenarioConfig } from '@claw/core';

const { Text } = Typography;

interface PromptCardsProps {
  onSelect: (scenario: ScenarioConfig) => void;
  onAsk?: (question: string) => void;
}

/** 场景 key → 图标映射 */
const ICONS: Record<string, React.ReactNode> = {
  reimbursement_create: <FileTextOutlined style={{ fontSize: 18, color: '#1a6fb5' }} />,
  reimbursement_review: <AuditOutlined style={{ fontSize: 18, color: '#52c41a' }} />,
  contract_draft: <SolutionOutlined style={{ fontSize: 18, color: '#722ed1' }} />,
  contract_review: <SafetyCertificateOutlined style={{ fontSize: 18, color: '#fa8c16' }} />,
};

/** 能力标签 — 参考图风格 */
const capabilityTabs = [
  { label: '智能填单', color: '#1a6fb5' },
  { label: '智能审核', color: '#52c41a' },
  { label: '智能起草', color: '#722ed1' },
  { label: '智能鉴审', color: '#fa8c16' },
];

/** 建议问题 */
const SUGGESTED_QUESTIONS = [
  'What can Claw do?',
  '采购申请多久能审批完成？',
  '如何使用合同管理？',
  '报销流程多久能审批完成？',
];

/**
 * 智能模式初始提示卡片 — 参考图风格。
 * 包含欢迎语、能力标签、建议问题、场景卡片。
 */
export default function PromptCards({ onSelect, onAsk }: PromptCardsProps) {
  const scenarios = getAllScenarios();

  return (
    <div style={{ padding: '24px 20px' }}>
      {/* ── 欢迎标题 ── */}
      <div style={{ textAlign: 'center', marginBottom: 20 }}>
        <div style={{ fontSize: 18, fontWeight: 600, color: '#333', marginBottom: 4 }}>
          Claw AI助手
        </div>
        <Text type="secondary" style={{ fontSize: 14 }}>
          Hi~ I'm Claw AI, happy to help!
        </Text>
      </div>

      {/* ── 能力标签 ── */}
      <div style={{ textAlign: 'center', marginBottom: 20 }}>
        {capabilityTabs.map((tab) => (
          <Tag
            key={tab.label}
            style={{
              margin: '0 4px 6px',
              borderRadius: 12,
              padding: '2px 12px',
              fontSize: 12,
              border: `1px solid ${tab.color}40`,
              color: tab.color,
              background: `${tab.color}08`,
              cursor: 'default',
            }}
          >
            {tab.label}
          </Tag>
        ))}
      </div>

      {/* ── 建议问题 ── */}
      <div style={{ marginBottom: 24 }}>
        {SUGGESTED_QUESTIONS.map((q) => (
          <div
            key={q}
            className="suggested-question"
            onClick={() => onAsk?.(q)}
            style={{ cursor: onAsk ? 'pointer' : 'default' }}
          >
            {q}
          </div>
        ))}
      </div>

      {/* ── 场景卡片 ── */}
      <div style={{ fontSize: 13, color: '#666', marginBottom: 10, fontWeight: 500 }}>
        或选择具体业务场景：
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        {scenarios.map((sc) => (
          <div key={sc.key} className="prompt-card" onClick={() => onSelect(sc)}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 8,
                  background: '#f5f7fa',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}
              >
                {ICONS[sc.key] || <FileTextOutlined style={{ fontSize: 18, color: '#1a6fb5' }} />}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 13, lineHeight: 1.3 }}>
                  {sc.promptDescription}
                </div>
                <Text type="secondary" style={{ fontSize: 11 }} ellipsis>
                  {sc.promptSubtext}
                </Text>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
