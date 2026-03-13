import { useState, useCallback, useRef, useEffect } from 'react';
import { Modal, Input, Typography, Empty } from 'antd';
import { SearchOutlined, LoadingOutlined } from '@ant-design/icons';
import { aiApi, type SearchResult } from '@claw/core';
import { SESSION_LABEL_MAP } from './constants';

const { Text } = Typography;

interface SearchModalProps {
  open: boolean;
  onClose: () => void;
  onSelectSession: (sessionId: string) => void;
}

function formatResultLabel(result: SearchResult): string {
  if (result.title) return result.title as string;
  const bt = result.business_type || '';
  return SESSION_LABEL_MAP[bt] || bt || '对话';
}

function formatResultDate(result: SearchResult): string {
  if (!result.created_at) return '';
  try {
    const ts = typeof result.created_at === 'number'
      ? (result.created_at < 1e12 ? result.created_at * 1000 : result.created_at)
      : Number(result.created_at);
    const d = new Date(ts);
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const hour = String(d.getHours()).padStart(2, '0');
    const min = String(d.getMinutes()).padStart(2, '0');
    return `${month}-${day} ${hour}:${min}`;
  } catch {
    return '';
  }
}

export default function SearchModal({ open, onClose, onSelectSession }: SearchModalProps) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef = useRef<{ focus: () => void } | null>(null);

  // 自动聚焦 + 关闭时清理
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 100);
    } else {
      setQuery('');
      setResults([]);
      setSearched(false);
    }
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [open]);

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([]);
      setSearched(false);
      return;
    }
    setLoading(true);
    try {
      const data = await aiApi.searchSessions(q.trim());
      setResults(data);
      setSearched(true);
    } catch (err) {
      console.warn('[SearchModal] search failed:', err);
      setResults([]);
      setSearched(true);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleChange = useCallback((value: string) => {
    setQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(value), 300);
  }, [doSearch]);

  const handleSelect = useCallback((sessionId: string) => {
    onSelectSession(sessionId);
    onClose();
  }, [onSelectSession, onClose]);

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      title={null}
      closable={false}
      width={520}
      className="search-modal"
      styles={{ body: { padding: 0 } }}
    >
      <div className="search-modal-input-wrapper">
        <Input
          ref={inputRef as React.Ref<never>}
          prefix={loading ? <LoadingOutlined style={{ color: '#999' }} /> : <SearchOutlined style={{ color: '#999' }} />}
          placeholder="搜索会话标题或内容..."
          value={query}
          onChange={(e) => handleChange(e.target.value)}
          variant="borderless"
          size="large"
          allowClear
        />
      </div>

      <div className="search-modal-results">
        {!searched && !loading && (
          <div className="search-modal-hint">
            <Text type="secondary">输入关键词搜索历史会话</Text>
          </div>
        )}

        {searched && results.length === 0 && (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="未找到匹配的会话"
            style={{ padding: '32px 0' }}
          />
        )}

        {results.map((result) => (
          <div
            key={result.session_id}
            className="search-result-item"
            role="button"
            tabIndex={0}
            onClick={() => handleSelect(result.session_id)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleSelect(result.session_id); } }}
          >
            <div className="search-result-header">
              <Text
                style={{
                  fontSize: 14,
                  fontWeight: 500,
                  color: '#333',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  flex: 1,
                }}
              >
                {formatResultLabel(result)}
              </Text>
              <Text type="secondary" style={{ fontSize: 12, flexShrink: 0, marginLeft: 8 }}>
                {formatResultDate(result)}
              </Text>
            </div>
            {result.match_snippet && (
              <Text
                type="secondary"
                style={{
                  fontSize: 12,
                  display: 'block',
                  marginTop: 4,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {result.match_snippet}
              </Text>
            )}
          </div>
        ))}
      </div>
    </Modal>
  );
}
