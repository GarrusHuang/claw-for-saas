import { useCallback } from 'react';
import { Table, Switch, Dropdown, Button, Popconfirm, message } from 'antd';
import { PlusOutlined, MoreOutlined } from '@ant-design/icons';
import { aiApi, type ScheduledTask } from '@claw/core';

interface ScheduleListProps {
  tasks: ScheduledTask[];
  loading: boolean;
  onRefresh: () => void;
  onCreate: () => void;
  onEdit: (task: ScheduledTask) => void;
}

/** Convert cron expression to readable Chinese text */
function describeCron(cron: string): string {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return cron;
  const [minS, hourS, domS, , dowS] = parts;
  const time = `${hourS.padStart(2, '0')}:${minS.padStart(2, '0')}`;

  if (dowS === '*' && domS === '*') return `每天 ${time}`;
  if (dowS === '1-5' && domS === '*') return `工作日 ${time}`;
  if (dowS !== '*' && domS === '*') {
    const dayMap: Record<string, string> = { '0': '日', '1': '一', '2': '二', '3': '三', '4': '四', '5': '五', '6': '六' };
    return `每周${dayMap[dowS] || dowS} ${time}`;
  }
  if (dowS === '*' && domS !== '*') return `每月 ${domS} 日 ${time}`;
  return cron;
}

/** Format timestamp to relative time */
function relativeTime(ts: number | null): string {
  if (!ts) return '-';
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return '刚刚';
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
  return `${Math.floor(diff / 86400)}天前`;
}

export default function ScheduleList({ tasks, loading, onRefresh, onCreate, onEdit }: ScheduleListProps) {

  const handleToggle = useCallback(async (task: ScheduledTask) => {
    try {
      if (task.enabled) {
        await aiApi.pauseSchedule(task.id);
      } else {
        await aiApi.resumeSchedule(task.id);
      }
      onRefresh();
    } catch {
      message.error('操作失败');
    }
  }, [onRefresh]);

  const handleDelete = useCallback(async (taskId: string) => {
    try {
      await aiApi.deleteSchedule(taskId);
      message.success('任务已删除');
      onRefresh();
    } catch {
      message.error('删除失败');
    }
  }, [onRefresh]);

  const columns = [
    {
      title: '标题',
      dataIndex: 'name',
      key: 'name',
      ellipsis: true,
    },
    {
      title: '计划于',
      dataIndex: 'cron',
      key: 'cron',
      width: 180,
      render: (cron: string) => describeCron(cron),
    },
    {
      title: '上次执行',
      key: 'last_run',
      width: 140,
      render: (_: unknown, record: ScheduledTask) => (
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span
            className={`schedule-status-dot schedule-status-dot--${
              !record.last_run_at ? 'none' : record.last_run_status === 'success' ? 'success' : 'failed'
            }`}
          />
          {relativeTime(record.last_run_at)}
        </span>
      ),
    },
    {
      title: '状态',
      key: 'enabled',
      width: 80,
      render: (_: unknown, record: ScheduledTask) => (
        <Switch
          size="small"
          checked={record.enabled}
          onChange={() => handleToggle(record)}
        />
      ),
    },
    {
      title: '更多',
      key: 'actions',
      width: 60,
      render: (_: unknown, record: ScheduledTask) => (
        <Dropdown
          menu={{
            items: [
              { key: 'edit', label: '编辑', onClick: () => onEdit(record) },
              {
                key: 'delete',
                label: (
                  <Popconfirm
                    title={`确定删除 "${record.name}"?`}
                    onConfirm={() => handleDelete(record.id)}
                    okText="删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true, size: 'small' }}
                    cancelButtonProps={{ size: 'small' }}
                  >
                    <span style={{ color: '#ff4d4f' }}>删除</span>
                  </Popconfirm>
                ),
              },
            ],
          }}
          trigger={['click']}
        >
          <Button type="text" size="small" icon={<MoreOutlined />} />
        </Dropdown>
      ),
    },
  ];

  return (
    <div>
      <div className="schedule-view-header">
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0, color: '#333' }}>定时任务</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={onCreate}>
          新建任务
        </Button>
      </div>

      <Table
        dataSource={tasks}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={false}
        size="middle"
        locale={{ emptyText: '暂无定时任务' }}
      />
    </div>
  );
}
