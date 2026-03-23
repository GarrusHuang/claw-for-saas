/**
 * 邀请码管理 — 列表 + 创建(显示码) + 撤销。
 */
import { useState, useEffect, useCallback } from 'react';
import { Table, Button, Modal, Form, Select, InputNumber, Tag, Popconfirm, Typography, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { listInviteCodes, createInviteCode, revokeInviteCode, type InviteCode } from './admin-api';

interface Props {
  tenantId: string;
}

function formatTime(ts: number | null): string {
  if (!ts) return '-';
  return new Date(ts * 1000).toLocaleString('zh-CN');
}

export default function InviteCodeManager({ tenantId }: Props) {
  const [codes, setCodes] = useState<InviteCode[]>([]);
  const [loading, setLoading] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [createdCode, setCreatedCode] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setCodes(await listInviteCodes(tenantId));
    } catch (e) {
      message.error(`加载失败: ${e instanceof Error ? e.message : e}`);
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const result = await createInviteCode(tenantId, {
        roles: values.roles || [],
        max_uses: values.max_uses || 1,
        expires_in_days: values.expires_in_days || null,
      });
      setCreatedCode(result.code);
      setCreateModalOpen(false);
      form.resetFields();
      load();
    } catch (e) {
      message.error(`创建失败: ${e instanceof Error ? e.message : e}`);
    } finally {
      setSaving(false);
    }
  };

  const handleRevoke = async (code: string) => {
    try {
      await revokeInviteCode(tenantId, code);
      message.success('已撤销');
      load();
    } catch (e) {
      message.error(`撤销失败: ${e instanceof Error ? e.message : e}`);
    }
  };

  const statusColor = (s: string) => {
    if (s === 'active') return 'green';
    if (s === 'revoked') return 'red';
    if (s === 'exhausted') return 'orange';
    return 'default';
  };

  const columns = [
    {
      title: '邀请码', dataIndex: 'code', key: 'code',
      render: (code: string) => (
        <Typography.Text copyable style={{ fontSize: 13 }}>{code}</Typography.Text>
      ),
    },
    {
      title: '角色', dataIndex: 'roles', key: 'roles',
      render: (roles: string[]) => roles.map(r => <Tag key={r}>{r}</Tag>),
    },
    {
      title: '使用次数', key: 'uses',
      render: (_: unknown, r: InviteCode) => `${r.used_count} / ${r.max_uses}`,
    },
    { title: '过期时间', dataIndex: 'expires_at', key: 'expires_at', render: formatTime },
    { title: '创建者', dataIndex: 'created_by', key: 'created_by' },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', render: formatTime },
    {
      title: '状态', dataIndex: 'status', key: 'status',
      render: (s: string) => <Tag color={statusColor(s)}>{s}</Tag>,
    },
    {
      title: '操作', key: 'actions',
      render: (_: unknown, record: InviteCode) => (
        record.status === 'active' ? (
          <Popconfirm title="确认撤销？" onConfirm={() => handleRevoke(record.code)}>
            <a>撤销</a>
          </Popconfirm>
        ) : <span style={{ color: '#bfbfbf' }}>-</span>
      ),
    },
  ];

  return (
    <>
      <div className="admin-toolbar">
        <span style={{ fontSize: 13, color: '#8c8c8c' }}>租户: {tenantId}</span>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setCreateModalOpen(true); }}>
          生成邀请码
        </Button>
      </div>
      <Table
        dataSource={codes}
        columns={columns}
        rowKey="code"
        loading={loading}
        pagination={false}
        size="middle"
      />

      {/* 创建表单 */}
      <Modal
        title="生成邀请码"
        open={createModalOpen}
        onCancel={() => setCreateModalOpen(false)}
        onOk={handleCreate}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="roles" label="注册角色">
            <Select
              mode="multiple"
              options={[
                { value: 'admin', label: 'admin' },
                { value: 'user', label: 'user' },
              ]}
              placeholder="选择注册后角色"
            />
          </Form.Item>
          <Form.Item name="max_uses" label="最大使用次数" initialValue={1}>
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="expires_in_days" label="过期天数 (留空=永不过期)">
            <InputNumber min={1} style={{ width: '100%' }} placeholder="如: 7" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 创建成功弹窗 */}
      <Modal
        title="邀请码已生成"
        open={!!createdCode}
        onCancel={() => setCreatedCode(null)}
        onOk={() => setCreatedCode(null)}
      >
        <div style={{ marginBottom: 12, fontSize: 13, color: '#8c8c8c' }}>
          请将邀请码发送给目标用户:
        </div>
        <Typography.Text code copyable style={{ fontSize: 16 }}>
          {createdCode}
        </Typography.Text>
      </Modal>
    </>
  );
}
