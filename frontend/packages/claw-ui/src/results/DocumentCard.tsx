/**
 * DocumentCard — 智能文档展示 (Phase 23 重写)。
 *
 * 根据文档类型自动选择展示模式:
 * - 合同类 + 有 originalContent → ContractDiffEditor
 * - 其他 → DocumentPresenter (Cowork 风格卡片)
 */

import type { GeneratedDocument } from '@claw/core';
import DocumentPresenter from './DocumentPresenter';
import ContractDiffEditor from './ContractDiffEditor';
import type { ContractAnnotation } from './ContractDiffEditor';

interface DocumentCardProps {
  document: GeneratedDocument;
  title?: string;
  annotations?: ContractAnnotation[];
  onDiffSubmit?: (accepted: unknown[], rejected: unknown[]) => void;
  onAdopt?: (doc: GeneratedDocument) => void;
}

/** Check if document is a contract type with original content for diff */
function isContractWithDiff(doc: GeneratedDocument): boolean {
  const contractTypes = ['合同', '协议', 'contract', 'agreement'];
  const isContract = contractTypes.some((t) =>
    doc.documentType.toLowerCase().includes(t) ||
    doc.title.toLowerCase().includes(t),
  );
  const hasOriginal = !!(doc.metadata?.originalContent);
  return isContract && hasOriginal;
}

export default function DocumentCard({
  document: doc,
  title,
  annotations,
  onDiffSubmit,
  onAdopt,
}: DocumentCardProps) {
  // Contract with original content → Diff Editor
  if (isContractWithDiff(doc)) {
    return (
      <div className="animate-fade-in">
        <ContractDiffEditor
          title={title || `${doc.title} — 修改对比`}
          originalContent={doc.metadata.originalContent as string}
          modifiedContent={doc.content}
          annotations={annotations}
          onSubmit={onDiffSubmit}
        />
      </div>
    );
  }

  // Default → DocumentPresenter
  return (
    <div className="animate-fade-in">
      <DocumentPresenter document={doc} onAdopt={onAdopt} />
    </div>
  );
}
