import { useState, useEffect, useCallback } from 'react';
import { aiApi, type ScheduledTask } from '@claw/core';
import ScheduleList from './ScheduleList.tsx';
import ScheduleForm from './ScheduleForm.tsx';

type SubView = 'list' | 'create' | 'edit';

export default function ScheduleView() {
  const [subView, setSubView] = useState<SubView>('list');
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [editTask, setEditTask] = useState<ScheduledTask | null>(null);

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

  const handleBack = useCallback(() => {
    setSubView('list');
    setEditTask(null);
  }, []);

  const handleFormSuccess = useCallback(() => {
    setSubView('list');
    setEditTask(null);
    fetchTasks();
  }, [fetchTasks]);

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
    />
  );
}
