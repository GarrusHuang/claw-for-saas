import { useState, useEffect, useCallback } from 'react';
import { aiApi, type ScheduledTask } from '@claw/core';
import ScheduleList from './ScheduleList.tsx';
import ScheduleForm from './ScheduleForm.tsx';
import ScheduleDetail from './ScheduleDetail.tsx';

type SubView = 'list' | 'create' | 'edit' | 'detail';

export default function ScheduleView() {
  const [subView, setSubView] = useState<SubView>('list');
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [editTask, setEditTask] = useState<ScheduledTask | null>(null);
  const [detailTask, setDetailTask] = useState<ScheduledTask | null>(null);

  const fetchTasks = useCallback(async () => {
    setLoading(true);
    try {
      const data = await aiApi.listSchedules();
      setTasks(data.tasks);
    } catch (err) {
      console.warn('[ScheduleView] Failed to fetch schedules:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleCreate = useCallback(() => {
    setEditTask(null);
    setSubView('create');
  }, []);

  const handleEdit = useCallback((task: ScheduledTask) => {
    setEditTask(task);
    setSubView('edit');
  }, []);

  const handleDetail = useCallback(async (task: ScheduledTask) => {
    // 先用列表数据立即展示，同时从 API 拉取最新数据（含 run_history）
    setDetailTask(task);
    setSubView('detail');
    try {
      const fresh = await aiApi.getSchedule(task.id);
      setDetailTask(fresh);
    } catch {
      // 拉取失败就用列表数据
    }
  }, []);

  const handleBack = useCallback(() => {
    setSubView('list');
    setEditTask(null);
    setDetailTask(null);
  }, []);

  const handleFormSuccess = useCallback(async () => {
    await fetchTasks();
    const returnTaskId = editTask?.id;
    setEditTask(null);
    // 如果是从详情页进入编辑的，编辑完回详情页
    if (returnTaskId && detailTask?.id === returnTaskId) {
      try {
        const fresh = await aiApi.getSchedule(returnTaskId);
        setDetailTask(fresh);
        setSubView('detail');
      } catch {
        setSubView('list');
        setDetailTask(null);
      }
    } else {
      setSubView('list');
      setDetailTask(null);
    }
  }, [fetchTasks, editTask, detailTask]);

  const handleDetailRefresh = useCallback(async () => {
    await fetchTasks();
    // 刷新 detailTask
    if (detailTask) {
      try {
        const updated = await aiApi.getSchedule(detailTask.id);
        setDetailTask(updated);
      } catch {
        // 任务可能已删除
        setSubView('list');
        setDetailTask(null);
      }
    }
  }, [fetchTasks, detailTask]);

  if (subView === 'detail' && detailTask) {
    return (
      <ScheduleDetail
        task={detailTask}
        onBack={handleBack}
        onEdit={() => handleEdit(detailTask)}
        onRefresh={handleDetailRefresh}
      />
    );
  }

  if (subView === 'create' || subView === 'edit') {
    return (
      <ScheduleForm
        editTask={editTask}
        onBack={handleBack}
        onSuccess={handleFormSuccess}
      />
    );
  }

  return (
    <ScheduleList
      tasks={tasks}
      loading={loading}
      onRefresh={fetchTasks}
      onCreate={handleCreate}
      onEdit={handleEdit}
      onDetail={handleDetail}
    />
  );
}
