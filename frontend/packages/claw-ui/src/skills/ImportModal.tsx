import { useState } from 'react';
import { Modal, Input, Tabs, Typography, message } from 'antd';
import { aiApi } from '@claw/core';
const { importSkill } = aiApi;

const { Text } = Typography;
const { TextArea } = Input;

interface ImportModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export default function ImportModal({ open, onClose, onSuccess }: ImportModalProps) {
  const [mode, setMode] = useState<'url' | 'content'>('url');
  const [url, setUrl] = useState('');
  const [content, setContent] = useState('');
  const [importing, setImporting] = useState(false);

  const handleImport = async () => {
    setImporting(true);
    try {
      const payload = mode === 'url' ? { url } : { content };
      const result = await importSkill(payload);
      if (result.ok) {
        message.success(`Skill "${result.name}" 导入成功`);
        onSuccess();
        onClose();
        setUrl('');
        setContent('');
      } else {
        message.error(result.error || '导入失败');
      }
    } catch (err) {
      message.error('导入请求失败');
    } finally {
      setImporting(false);
    }
  };

  return (
    <Modal
      title="导入 Skill"
      open={open}
      onCancel={() => { setUrl(''); setContent(''); onClose(); }}
      onOk={handleImport}
      okText="导入"
      confirmLoading={importing}
      width={640}
    >
      <Tabs
        activeKey={mode}
        onChange={(k) => setMode(k as 'url' | 'content')}
        items={[
          { key: 'url', label: '从 URL 导入' },
          { key: 'content', label: '粘贴内容' },
        ]}
        size="small"
      />

      {mode === 'url' ? (
        <div>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
            支持 GitHub 文件 URL，例如: https://github.com/anthropics/skills/blob/main/skills/pdf/SKILL.md
          </Text>
          <Input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://github.com/..."
          />
        </div>
      ) : (
        <div>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
            粘贴完整的 SKILL.md 内容 (包括 --- frontmatter ---)
          </Text>
          <TextArea
            rows={14}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder={"---\nname: my-skill\ndescription: ...\n---\n\n# Skill Content\n\n..."}
            style={{ fontFamily: 'monospace', fontSize: 12 }}
          />
        </div>
      )}
    </Modal>
  );
}
