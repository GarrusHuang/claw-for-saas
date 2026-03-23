/**
 * 用量统计面板 — 汇总卡片 + 日明细 + 用户排名 + 工具排名 + 存储。
 */
import { useState, useEffect, useCallback } from 'react';
import { Statistic, Table, DatePicker, Button, message } from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import {
  getUsageSummary, getDailyUsage, getUserRanking, getToolUsage, getStorageUsage,
  type UsageSummary, type DailyUsage, type UserRanking, type ToolUsage, type StorageUsage,
} from './admin-api';

interface Props {
  tenantId: string;
}

const { RangePicker } = DatePicker;

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function UsageDashboard({ tenantId }: Props) {
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs]>([
    dayjs().subtract(7, 'day'),
    dayjs(),
  ]);
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [daily, setDaily] = useState<DailyUsage[]>([]);
  const [userRank, setUserRank] = useState<UserRanking[]>([]);
  const [toolRank, setToolRank] = useState<ToolUsage[]>([]);
  const [storage, setStorage] = useState<StorageUsage | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    const start = dateRange[0].format('YYYY-MM-DD');
    const end = dateRange[1].format('YYYY-MM-DD');
    setLoading(true);
    try {
      const [s, d, u, t, st] = await Promise.all([
        getUsageSummary(tenantId, start, end),
        getDailyUsage(tenantId, start, end),
        getUserRanking(tenantId, start, end),
        getToolUsage(tenantId, start, end),
        getStorageUsage(tenantId),
      ]);
      setSummary(s);
      setDaily(Array.isArray(d) ? d : []);
      setUserRank(Array.isArray(u) ? u : []);
      setToolRank(Array.isArray(t) ? t : []);
      setStorage(st);
    } catch (e) {
      message.error(`加载用量数据失败: ${e instanceof Error ? e.message : e}`);
    } finally {
      setLoading(false);
    }
  }, [tenantId, dateRange]);

  useEffect(() => { load(); }, [load]);

  const successRate = summary && summary.total_requests > 0
    ? ((summary.success_count / summary.total_requests) * 100).toFixed(1)
    : '0';

  const dailyCols = [
    { title: '日期', dataIndex: 'date', key: 'date' },
    { title: '请求数', dataIndex: 'total_requests', key: 'total_requests' },
    { title: 'Token', dataIndex: 'total_tokens', key: 'total_tokens', render: (v: number) => v?.toLocaleString() ?? '-' },
    { title: '工具调用', dataIndex: 'total_tool_calls', key: 'total_tool_calls' },
    { title: '成功', dataIndex: 'success_count', key: 'success_count' },
    { title: '失败', dataIndex: 'failed_count', key: 'failed_count' },
  ];

  const userCols = [
    { title: '用户', dataIndex: 'user_id', key: 'user_id' },
    { title: '请求', dataIndex: 'total_requests', key: 'total_requests' },
    { title: 'Token', dataIndex: 'total_tokens', key: 'total_tokens', render: (v: number) => v?.toLocaleString() ?? '-' },
    { title: '工具调用', dataIndex: 'total_tool_calls', key: 'total_tool_calls' },
  ];

  const toolCols = [
    { title: '工具名', dataIndex: 'tool_name', key: 'tool_name' },
    { title: '调用次数', dataIndex: 'call_count', key: 'call_count' },
  ];

  return (
    <div>
      {/* 日期筛选 */}
      <div style={{ marginBottom: 20, display: 'flex', alignItems: 'center', gap: 12 }}>
        <RangePicker
          value={dateRange}
          onChange={(v) => { if (v && v[0] && v[1]) setDateRange([v[0], v[1]]); }}
        />
        <Button type="primary" onClick={load} loading={loading}>查询</Button>
        <span style={{ fontSize: 13, color: '#8c8c8c', marginLeft: 'auto' }}>租户: {tenantId}</span>
      </div>

      {/* 汇总卡片 */}
      <div className="admin-stat-cards">
        <div className="admin-stat-card">
          <Statistic title="总请求" value={summary?.total_requests ?? 0} />
        </div>
        <div className="admin-stat-card">
          <Statistic title="总 Token" value={summary?.total_tokens ?? 0} formatter={(v) => Number(v).toLocaleString()} />
        </div>
        <div className="admin-stat-card">
          <Statistic title="成功率" value={successRate} suffix="%" />
        </div>
        <div className="admin-stat-card">
          <Statistic title="平均 Token/请求" value={summary?.avg_tokens_per_request ?? 0} precision={0} />
        </div>
        <div className="admin-stat-card">
          <Statistic title="平均耗时" value={summary?.avg_duration_ms ?? 0} suffix="ms" precision={0} />
        </div>
      </div>

      {/* 日明细 */}
      <Table
        dataSource={daily}
        columns={dailyCols}
        rowKey="date"
        loading={loading}
        pagination={false}
        size="small"
        style={{ marginBottom: 20 }}
      />

      {/* 用户排名 + 工具排名 */}
      <div className="admin-tables-row">
        <div className="admin-table-section">
          <div className="admin-table-section-title">用户排名</div>
          <Table dataSource={userRank} columns={userCols} rowKey="user_id" pagination={false} size="small" />
        </div>
        <div className="admin-table-section">
          <div className="admin-table-section-title">工具排名</div>
          <Table dataSource={toolRank} columns={toolCols} rowKey="tool_name" pagination={false} size="small" />
        </div>
      </div>

      {/* 存储用量 */}
      {storage && (
        <div style={{ marginTop: 20 }}>
          <div className="admin-stat-cards" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
            <div className="admin-stat-card">
              <Statistic title="会话存储" value={formatBytes(storage.sessions_bytes ?? 0)} />
            </div>
            <div className="admin-stat-card">
              <Statistic title="文件存储" value={formatBytes(storage.files_bytes ?? 0)} />
            </div>
            <div className="admin-stat-card">
              <Statistic title="总存储" value={formatBytes(storage.total_bytes ?? 0)} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
