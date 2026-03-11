/**
 * 场景配置类型定义。
 *
 * 从 config/scenarios.ts 提取的接口，使 ai-core 不依赖具体场景数据。
 */

export interface FormSection {
  title: string;
  fields: string[];
}

export interface CandidateType {
  type_id: string;
  type_name: string;
  description: string;
  keywords: string[];
}

/** 表单字段类型 */
export type FieldType =
  | 'text'
  | 'number'
  | 'textarea'
  | 'select'
  | 'search_select'
  | 'date'
  | 'date_range'
  | 'currency';

export interface FormFieldDef {
  field_id: string;
  field_name: string;
  field_type: FieldType;
  required: boolean;
  description?: string;
  /** 静态选项 (select) */
  options?: string[];
  /** 动态查询端点 (search_select) */
  optionsEndpoint?: string;
  /** 单位后缀 (currency: '元' | '万元') */
  unit?: string;
}

export interface AuditRuleDef {
  rule_id: string;
  rule_name: string;
  description: string;
  severity: string;
  category?: string;
}

export interface KnownValue {
  field_id: string;
  value: unknown;
  source: string;
}

export interface ScenarioConfig {
  key: string;
  title: string;
  action: string;
  businessType: string;
  smartButtonLabel: string;
  routePath: string;
  sampleMaterial?: string;
  promptDescription: string;
  promptSubtext: string;
  candidateTypes: CandidateType[];
  formFields: FormFieldDef[];
  auditRules: AuditRuleDef[];
  knownValues: KnownValue[];
  formSections: FormSection[];
  initialValues?: Record<string, unknown>;
}
