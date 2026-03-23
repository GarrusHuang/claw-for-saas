/**
 * 用户管理 — 列表 + 新建/编辑/删除。
 */
import { useState, useEffect, useCallback } from 'react';
import { Table, Button, Modal, Form, Input, Select, Tag, Popconfirm, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { listUsers, createUser, updateUser, deleteUser, type User } from './admin-api';

interface Props {
  tenantId: string;
}

const ROLE_OPTIONS = [
  { value: 'admin', label: 'admin' },
  { value: 'user', label: 'user' },
];

export default function UserManager({ tenantId }: Props) {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setUsers(await listUsers(tenantId));
    } catch (e) {
      message.error(`加载失败: ${e instanceof Error ? e.message : e}`);
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => { load(); }, [load]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (u: User) => {
    setEditing(u);
    form.setFieldsValue({ user_id: u.user_id, username: u.username, roles: u.roles, status: u.status });
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      if (editing) {
        const data: { password?: string; roles?: string[]; status?: string } = {};
        if (values.password) data.password = values.password;
        if (values.roles) data.roles = values.roles;
        if (values.status) data.status = values.status;
        await updateUser(tenantId, editing.user_id, data);
        message.success('用户已更新');
      } else {
        await createUser(tenantId, {
          user_id: values.user_id,
          username: values.username,
          password: values.password,
          roles: values.roles || [],
        });
        message.success('用户已创建');
      }
      setModalOpen(false);
      load();
    } catch (e) {
      message.error(`保存失败: ${e instanceof Error ? e.message : e}`);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (userId: string) => {
    try {
      await deleteUser(tenantId, userId);
      message.success('用户已删除');
      load();
    } catch (e) {
      message.error(`删除失败: ${e instanceof Error ? e.message : e}`);
    }
  };

  const columns = [
    { title: '用户 ID', dataIndex: 'user_id', key: 'user_id' },
    { title: '用户名', dataIndex: 'username', key: 'username' },
    {
      title: '角色', dataIndex: 'roles', key: 'roles',
      render: (roles: string[]) => roles.map(r => (
        <Tag key={r} color={r === 'admin' ? 'blue' : 'default'}>{r}</Tag>
      )),
    },
    {
      title: '状态', dataIndex: 'status', key: 'status',
      render: (s: string) => <Tag color={s === 'active' ? 'green' : 'default'}>{s}</Tag>,
    },
    {
      title: '操作', key: 'actions',
      render: (_: unknown, record: User) => (
        <span style={{ display: 'flex', gap: 8 }}>
          <a onClick={() => openEdit(record)}>编辑</a>
          <Popconfirm title="确认删除该用户？" onConfirm={() => handleDelete(record.user_id)}>
            <a style={{ color: '#ff4d4f' }}>删除</a>
          </Popconfirm>
        </span>
      ),
    },
  ];

  return (
    <>
      <div className="admin-toolbar">
        <span style={{ fontSize: 13, color: '#8c8c8c' }}>租户: {tenantId}</span>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建用户</Button>
      </div>
      <Table
        dataSource={users}
        columns={columns}
        rowKey="user_id"
        loading={loading}
        pagination={false}
        size="middle"
      />
      <Modal
        title={editing ? '编辑用户' : '新建用户'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSave}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          {!editing && (
            <>
              <Form.Item name="user_id" label="用户 ID" rules={[{ required: true }]}>
                <Input placeholder="如: U001" />
              </Form.Item>
              <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
                <Input placeholder="登录用户名" />
              </Form.Item>
            </>
          )}
          <Form.Item
            name="password"
            label={editing ? '新密码 (留空不修改)' : '密码'}
            rules={editing ? [] : [{ required: true, min: 6 }]}
          >
            <Input.Password placeholder={editing ? '留空保持原密码' : '至少 6 位'} />
          </Form.Item>
          <Form.Item name="roles" label="角色">
            <Select mode="multiple" options={ROLE_OPTIONS} placeholder="选择角色" />
          </Form.Item>
          {editing && (
            <Form.Item name="status" label="状态">
              <Select options={[
                { value: 'active', label: 'active' },
                { value: 'disabled', label: 'disabled' },
              ]} />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </>
  );
}
