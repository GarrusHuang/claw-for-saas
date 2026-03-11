/**
 * ContractDiffEditor — 合同 Diff 对比编辑器。
 *
 * Phase 23A: 展示原始合同与 AI 修改建议的对比。
 *
 * 功能:
 * - 按条款拆分对比 (section-based diff)
 * - 每个 diff 区块可 Accept / Reject
 * - 汇总统计: N 处修改, M 已采纳, K 已拒绝
 * - 支持注释 (来自审计结果)
 * - 全部确认后可提交
 */

import { useState, useMemo, useCallback } from 'react';
import { Typography, Button, Tag } from 'antd';
import {
  FileTextOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  EditOutlined,
} from '@ant-design/icons';
import DiffBlock from './DiffBlock';
import type { DiffSection, DiffDecision, DiffType } from './DiffBlock';

const { Text } = Typography;

export interface ContractAnnotation {
  sectionTitle: string;
  message: string;
}

interface ContractDiffEditorProps {
  title?: string;
  originalContent: string;
  modifiedContent: string;
  annotations?: ContractAnnotation[];
  onSubmit?: (accepted: DiffSection[], rejected: DiffSection[]) => void;
}

/** Split contract text into sections by numbered headings (第X条, X., ## etc.) */
function splitSections(text: string): Array<{ title: string; content: string }> {
  const lines = text.split('\n');
  const sections: Array<{ title: string; content: string }> = [];
  let currentTitle = '';
  let currentContent: string[] = [];

  const HEADING_RE = /^(?:#{1,3}\s+|第[一二三四五六七八九十百千\d]+[条章节]\s*|(?:\d+\.)\s+)/;

  for (const line of lines) {
    if (HEADING_RE.test(line.trim())) {
      // Save previous section
      if (currentTitle || currentContent.length > 0) {
        sections.push({
          title: currentTitle || '前言',
          content: currentContent.join('\n').trim(),
        });
      }
      currentTitle = line.trim();
      currentContent = [];
    } else {
      currentContent.push(line);
    }
  }

  // Save last section
  if (currentTitle || currentContent.length > 0) {
    sections.push({
      title: currentTitle || '正文',
      content: currentContent.join('\n').trim(),
    });
  }

  return sections;
}

/** Simple content similarity check (Jaccard on words) */
function contentSimilarity(a: string, b: string): number {
  const wordsA = new Set(a.replace(/\s+/g, ' ').trim().split(/\s/));
  const wordsB = new Set(b.replace(/\s+/g, ' ').trim().split(/\s/));
  if (wordsA.size === 0 && wordsB.size === 0) return 1;
  let intersection = 0;
  for (const w of wordsA) {
    if (wordsB.has(w)) intersection++;
  }
  const union = wordsA.size + wordsB.size - intersection;
  return union === 0 ? 1 : intersection / union;
}

/** Build diff sections by matching original and modified sections */
function buildDiffSections(
  original: string,
  modified: string,
  annotations?: ContractAnnotation[],
): DiffSection[] {
  const origSections = splitSections(original);
  const modSections = splitSections(modified);

  const annotationMap = new Map<string, string>();
  if (annotations) {
    for (const a of annotations) {
      annotationMap.set(a.sectionTitle, a.message);
    }
  }

  const result: DiffSection[] = [];
  const usedMod = new Set<number>();

  // Match original sections to modified sections by title similarity
  for (let i = 0; i < origSections.length; i++) {
    const orig = origSections[i];
    let bestMatch = -1;
    let bestScore = 0;

    for (let j = 0; j < modSections.length; j++) {
      if (usedMod.has(j)) continue;
      // Title matching: exact or similar
      const titleScore = orig.title === modSections[j].title ? 1 : contentSimilarity(orig.title, modSections[j].title);
      if (titleScore > bestScore && titleScore > 0.3) {
        bestScore = titleScore;
        bestMatch = j;
      }
    }

    if (bestMatch >= 0) {
      usedMod.add(bestMatch);
      const mod = modSections[bestMatch];
      const sim = contentSimilarity(orig.content, mod.content);
      const type: DiffType = sim > 0.95 ? 'unchanged' : 'modified';

      // Try to find annotation
      const annotation = annotationMap.get(orig.title) || annotationMap.get(mod.title);

      result.push({
        id: `diff-${i}`,
        title: orig.title,
        original: orig.content,
        modified: mod.content,
        type,
        annotation,
      });
    } else {
      // Original section removed
      result.push({
        id: `diff-${i}`,
        title: orig.title,
        original: orig.content,
        modified: '',
        type: 'removed',
        annotation: annotationMap.get(orig.title),
      });
    }
  }

  // Remaining modified sections are additions
  for (let j = 0; j < modSections.length; j++) {
    if (usedMod.has(j)) continue;
    const mod = modSections[j];
    result.push({
      id: `diff-add-${j}`,
      title: mod.title,
      original: '',
      modified: mod.content,
      type: 'added',
      annotation: annotationMap.get(mod.title),
    });
  }

  return result;
}

export default function ContractDiffEditor({
  title = '合同修改对比',
  originalContent,
  modifiedContent,
  annotations,
  onSubmit,
}: ContractDiffEditorProps) {
  const sections = useMemo(
    () => buildDiffSections(originalContent, modifiedContent, annotations),
    [originalContent, modifiedContent, annotations],
  );

  const [decisions, setDecisions] = useState<Record<string, DiffDecision>>({});

  const handleAccept = useCallback((id: string) => {
    setDecisions((prev) => ({
      ...prev,
      [id]: prev[id] === 'accepted' ? 'pending' : 'accepted',
    }));
  }, []);

  const handleReject = useCallback((id: string) => {
    setDecisions((prev) => ({
      ...prev,
      [id]: prev[id] === 'rejected' ? 'pending' : 'rejected',
    }));
  }, []);

  // Statistics
  const changedSections = sections.filter((s) => s.type !== 'unchanged');
  const acceptedCount = changedSections.filter((s) => decisions[s.id] === 'accepted').length;
  const rejectedCount = changedSections.filter((s) => decisions[s.id] === 'rejected').length;
  const pendingCount = changedSections.length - acceptedCount - rejectedCount;
  const allDecided = pendingCount === 0 && changedSections.length > 0;

  const handleSubmit = useCallback(() => {
    if (!onSubmit) return;
    const accepted = sections.filter((s) => decisions[s.id] === 'accepted');
    const rejected = sections.filter((s) => decisions[s.id] === 'rejected');
    onSubmit(accepted, rejected);
  }, [sections, decisions, onSubmit]);

  const handleAcceptAll = useCallback(() => {
    const newDecisions: Record<string, DiffDecision> = {};
    for (const s of changedSections) {
      newDecisions[s.id] = 'accepted';
    }
    setDecisions(newDecisions);
  }, [changedSections]);

  return (
    <div className="contract-diff-editor">
      {/* Header */}
      <div className="contract-diff-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <EditOutlined style={{ color: '#1890ff', fontSize: 16 }} />
          <Text strong style={{ fontSize: 14 }}>{title}</Text>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
          <Tag icon={<FileTextOutlined />} color="blue">
            {sections.length} 个条款
          </Tag>
          {changedSections.length > 0 && (
            <>
              <Tag color="orange">{changedSections.length} 处修改</Tag>
              {acceptedCount > 0 && (
                <Tag icon={<CheckCircleOutlined />} color="green">{acceptedCount} 已采纳</Tag>
              )}
              {rejectedCount > 0 && (
                <Tag icon={<CloseCircleOutlined />} color="red">{rejectedCount} 已拒绝</Tag>
              )}
              {pendingCount > 0 && (
                <Tag color="default">{pendingCount} 待决定</Tag>
              )}
            </>
          )}
        </div>
      </div>

      {/* Diff Sections */}
      <div className="contract-diff-body">
        {sections.map((section) => (
          <DiffBlock
            key={section.id}
            section={section}
            decision={decisions[section.id] || 'pending'}
            onAccept={handleAccept}
            onReject={handleReject}
          />
        ))}
      </div>

      {/* Footer Actions */}
      {changedSections.length > 0 && (
        <div className="contract-diff-footer">
          <Button size="small" onClick={handleAcceptAll} style={{ fontSize: 12 }}>
            全部采纳
          </Button>
          {onSubmit && (
            <Button
              type="primary"
              size="small"
              onClick={handleSubmit}
              disabled={!allDecided}
              style={{ fontSize: 12, borderRadius: 4 }}
            >
              {allDecided ? '提交修改' : `还有 ${pendingCount} 处待决定`}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
