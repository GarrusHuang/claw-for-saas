/**
 * Skill 创建/编辑模态框 — 增强版。
 *
 * Phase 18: 验证 warnings/checks 展示
 * - 保存成功但有 warnings → 弹出建议列表
 * - 保存失败且有 checks → 展示验证检查详情
 */

import { useEffect, useState } from 'react';
import { Modal, Form, Input, Select, message, Tag } from 'antd';
import { aiApi } from '@claw/core';

const { TextArea } = Input;

interface SkillEditorModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  editData?: {
    metadata: {
      name: string;
      description?: string;
      type?: string;
      version?: string;
      applies_to?: string[];
      business_types?: string[];
      depends_on?: string[];
      tags?: string[];
      token_estimate?: number;
    };
    body?: string;
  } | null;
}

export default function SkillEditorModal({ open, onClose, onSuccess, editData }: SkillEditorModalProps) {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const isEdit = !!editData;

  useEffect(() => {
    if (open && editData) {
      form.setFieldsValue({
        name: editData.metadata.name,
        description: editData.metadata.description || '',
        type: editData.metadata.type || 'domain',
        version: editData.metadata.version || '1.0',
        applies_to: (editData.metadata.applies_to || []).join(', '),
        business_types: (editData.metadata.business_types || []).join(', '),
        depends_on: (editData.metadata.depends_on || []).join(', '),
        tags: (editData.metadata.tags || []).join(', '),
        token_estimate: editData.metadata.token_estimate || '',
        body: editData.body || '',
      });
    } else if (open) {
      form.resetFields();
    }
  }, [open, editData, form]);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);

      const splitTrim = (s?: string) =>
        s ? s.split(',').map((v: string) => v.trim()).filter(Boolean) : [];

      const payload = {
        name: values.name.trim(),
        description: values.description || '',
        type: values.type || 'domain',
        version: values.version || '1.0',
        applies_to: splitTrim(values.applies_to),
        business_types: splitTrim(values.business_types),
        depends_on: splitTrim(values.depends_on),
        tags: splitTrim(values.tags),
        token_estimate: values.token_estimate ? Number(values.token_estimate) : undefined,
        body: values.body || '',
      };

      const result = isEdit
        ? await aiApi.updateSkill(editData!.metadata.name, payload)
        : await aiApi.createSkill(payload);

      if (result.ok) {
        // Phase 18: 显示验证警告
        if (result.warnings && result.warnings.length > 0) {
          Modal.warning({
            title: 'Skill 已保存，但有以下建议',
            content: (
              <ul style={{ paddingLeft: 20 }}>
                {result.warnings.map((w: string, i: number) => (
                  <li key={i} style={{ marginBottom: 4, fontSize: 13 }}>{w}</li>
                ))}
              </ul>
            ),
          });
        } else {
          message.success(isEdit ? 'Skill 已更新' : 'Skill 已创建');
        }
        onSuccess();
        onClose();
      } else {
        // Phase 18: 显示验证检查详情
        if (result.checks) {
          Modal.error({
            title: '验证失败',
            content: (
              <div>
                <p style={{ marginBottom: 8 }}>{result.error}</p>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {Object.entries(result.checks).map(([k, v]) => (
                    <Tag key={k} color={v ? 'green' : 'red'}>
                      {v ? '✓' : '✗'} {k}
                    </Tag>
                  ))}
                </div>
              </div>
            ),
          });
        } else {
          message.error(result.error || '操作失败');
        }
      }
    } catch {
      // validation error
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={isEdit ? '编辑 Skill' : '创建 Skill'}
      open={open}
      onCancel={onClose}
      onOk={handleSubmit}
      okText={isEdit ? '保存' : '创建'}
      confirmLoading={saving}
      width={720}
      styles={{ body: { maxHeight: '70vh', overflow: 'auto' } }}
    >
      <Form form={form} layout="vertical" size="small" initialValues={{ type: 'domain', version: '1.0' }}>
        <div style={{ display: 'flex', gap: 12 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入 Skill 名称' }]} style={{ flex: 1 }}>
            <Input placeholder="my-skill-name" disabled={isEdit} />
          </Form.Item>
          <Form.Item name="type" label="类型" style={{ width: 140 }}>
            <Select options={[
              { value: 'domain', label: '领域知识' },
              { value: 'scenario', label: '场景策略' },
              { value: 'capability', label: '能力增强' },
            ]} />
          </Form.Item>
          <Form.Item name="version" label="版本" style={{ width: 80 }}>
            <Input placeholder="1.0" />
          </Form.Item>
        </div>

        <Form.Item name="description" label="描述">
          <Input placeholder="简要描述这个 Skill 的用途" />
        </Form.Item>

        <div style={{ display: 'flex', gap: 12 }}>
          <Form.Item name="applies_to" label="适用范围 (逗号分隔)" style={{ flex: 1 }}>
            <Input placeholder="universal, universal_form_agent" />
          </Form.Item>
          <Form.Item name="business_types" label="业务类型 (逗号分隔)" style={{ flex: 1 }}>
            <Input placeholder="reimbursement, contract" />
          </Form.Item>
        </div>

        <div style={{ display: 'flex', gap: 12 }}>
          <Form.Item name="depends_on" label="依赖 (逗号分隔)" style={{ flex: 1 }}>
            <Input placeholder="hospital-finance" />
          </Form.Item>
          <Form.Item name="tags" label="标签 (逗号分隔)" style={{ flex: 1 }}>
            <Input placeholder="财务, 审计" />
          </Form.Item>
          <Form.Item name="token_estimate" label="Token 估算" style={{ width: 100 }}>
            <Input placeholder="1500" />
          </Form.Item>
        </div>

        <Form.Item name="body" label="Skill 正文 (Markdown)" rules={[{ required: true, message: '请输入 Skill 内容' }]}>
          <TextArea
            rows={14}
            placeholder={"# Skill 标题\n\n## 核心原则\n\n描述这个 Skill 的核心知识和策略..."}
            style={{ fontFamily: 'monospace', fontSize: 12 }}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
