import { useState, useEffect } from 'react';
import { Form, Input, Button, message } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { aiApi, type ScheduledTask } from '@claw/core';
import CronPicker from './CronPicker.tsx';

interface ScheduleFormProps {
  editTask: ScheduledTask | null;   // null = create mode
  onBack: () => void;
  onSuccess: () => void;
}

export default function ScheduleForm({ editTask, onBack, onSuccess }: ScheduleFormProps) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const isEdit = !!editTask;

  useEffect(() => {
    if (editTask) {
      form.setFieldsValue({
        name: editTask.name,
        message: editTask.message,
        cron: editTask.cron,
        business_type: editTask.business_type,
      });
    } else {
      form.resetFields();
      form.setFieldsValue({ cron: '0 9 * * *', business_type: 'scheduled_task' });
    }
  }, [editTask, form]);

  const handleSubmit = async (values: { name: string; message: string; cron: string; business_type: string }) => {
    setSubmitting(true);
    try {
      if (isEdit) {
        await aiApi.updateSchedule(editTask.id, {
          name: values.name,
          message: values.message,
          cron: values.cron,
          business_type: values.business_type,
        });
        message.success('任务已更新');
      } else {
        await aiApi.createSchedule({
          name: values.name,
          message: values.message,
          cron: values.cron,
          business_type: values.business_type || undefined,
        });
        message.success('任务已创建');
      }
      onSuccess();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '操作失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="schedule-form-container">
      <div
        className="schedule-form-back"
        onClick={onBack}
      >
        <ArrowLeftOutlined style={{ fontSize: 12 }} />
        <span>返回任务列表</span>
      </div>

      <h2 style={{ fontSize: 18, fontWeight: 600, margin: '16px 0 24px', color: '#333' }}>
        {isEdit ? '更新任务' : '创建任务'}
      </h2>

      <Form
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
        initialValues={{ cron: '0 9 * * *', business_type: 'scheduled_task' }}
      >
        <Form.Item label="标题" name="name" rules={[{ required: true, message: '请输入任务标题' }]}>
          <Input placeholder="输入任务标题" />
        </Form.Item>

        <Form.Item label="提示词" name="message" rules={[{ required: true, message: '请输入提示词' }]}>
          <Input.TextArea rows={6} placeholder="输入要执行的提示词..." />
        </Form.Item>

        <Form.Item label="计划" name="cron" rules={[{ required: true, message: '请设置计划' }]}>
          <CronPicker
            value={form.getFieldValue('cron')}
            onChange={(cron) => form.setFieldsValue({ cron })}
          />
        </Form.Item>

        <Form.Item label="业务类型" name="business_type">
          <Input placeholder="scheduled_task" />
        </Form.Item>

        <Form.Item style={{ marginTop: 32 }}>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
            <Button onClick={onBack}>取消</Button>
            <Button type="primary" htmlType="submit" loading={submitting}>
              {isEdit ? '更新任务' : '创建任务'}
            </Button>
          </div>
        </Form.Item>
      </Form>
    </div>
  );
}
