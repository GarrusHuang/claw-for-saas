import { test, expect } from '@playwright/test';

/**
 * E2E 视觉测试 — 真实浏览器验证 UI 渲染。
 *
 * 覆盖:
 * - F3: LoginPage 渲染 + 表单交互 + 错误提示
 * - F2: Cowork 三栏布局（无 tab 切换）
 * - F1: 文档流风格（无气泡、无头像）
 * - 截图: 每个关键页面自动截图到 e2e/screenshots/
 */

// ── F3: LoginPage ──

test.describe('F3: LoginPage', () => {
  test('renders login form correctly', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // 页面标题
    await expect(page.locator('.login-logo')).toHaveText('Claw');
    await expect(page.locator('.login-subtitle')).toHaveText('AI Agent 运行时');

    // 表单元素
    await expect(page.locator('#username')).toBeVisible();
    await expect(page.locator('#password')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toHaveText('登录');

    await page.screenshot({ path: 'e2e/screenshots/login-page.png' });
  });

  test('sign in button disabled when username empty', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const btn = page.locator('button[type="submit"]');
    await expect(btn).toBeDisabled();
  });

  test('sign in button enabled when username filled', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    await page.fill('#username', 'admin');
    await page.fill('#password', 'test123');

    const btn = page.locator('button[type="submit"]');
    await expect(btn).toBeEnabled();

    await page.screenshot({ path: 'e2e/screenshots/login-filled.png' });
  });

  test('shows error on failed login', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    await page.fill('#username', 'admin');
    await page.fill('#password', 'wrong');
    await page.click('button[type="submit"]');

    // 等待错误显示
    await page.waitForTimeout(2000);
    const error = page.locator('.login-error');
    await expect(error).toBeVisible();

    await page.screenshot({ path: 'e2e/screenshots/login-error.png' });
  });
});

// ── F2: Cowork 三栏布局 ──

test.describe('F2: Cowork Layout', () => {
  test.beforeEach(async ({ page }) => {
    // 注入 token 绕过认证进入主界面
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.evaluate(() => {
      localStorage.setItem('claw_auth_token', 'e2e-test-token');
      localStorage.setItem('claw_auth_user', JSON.stringify({
        userId: 'admin',
        tenantId: 'default',
        expiresAt: Date.now() + 86400000,
      }));
    });
    await page.reload();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
  });

  test('three-column layout renders', async ({ page }) => {
    await expect(page.locator('.cowork-sidebar')).toBeVisible();
    await expect(page.locator('.chat-dialog-body')).toBeVisible();
    await expect(page.locator('.progress-panel')).toBeVisible();

    await page.screenshot({ path: 'e2e/screenshots/cowork-layout.png', fullPage: true });
  });

  test('no tab buttons exist', async ({ page }) => {
    // 确认没有 Chat/Code tab
    await expect(page.locator('button:has-text("Chat")')).toHaveCount(0);
    await expect(page.locator('button:has-text("Code")')).toHaveCount(0);
  });

  test('header shows Claw title', async ({ page }) => {
    await expect(page.locator('.chat-dialog-header')).toContainText('Claw');
  });

  test('sidebar has navigation entries', async ({ page }) => {
    const sidebar = page.locator('.cowork-sidebar');

    await expect(sidebar.locator('text=新任务')).toBeVisible();
    await expect(sidebar.locator('text=搜索')).toBeVisible();
    await expect(sidebar.locator('text=定时任务')).toBeVisible();
    await expect(sidebar.locator('text=技能')).toBeVisible();
    await expect(sidebar.locator('text=自定义')).toBeVisible();
    await expect(sidebar.locator('text=最近')).toBeVisible();
  });

  test('progress panel has all sections', async ({ page }) => {
    const panel = page.locator('.progress-panel');

    await expect(panel.locator('.progress-section-title', { hasText: '进度' })).toBeVisible();
    await expect(panel.locator('.progress-section-title', { hasText: '文件' })).toBeVisible();
    await expect(panel.locator('.progress-section-title', { hasText: '说明' })).toBeVisible();
    await expect(panel.locator('.progress-section-title', { hasText: '上下文' })).toBeVisible();
  });

  test('chat input area renders with placeholder', async ({ page }) => {
    const textarea = page.locator('.chat-input-area textarea');
    await expect(textarea).toBeVisible();
    await expect(textarea).toHaveAttribute('placeholder', '回复...');

    await page.screenshot({ path: 'e2e/screenshots/chat-input.png' });
  });
});

// ── F1: 文档流风格 ──

test.describe('F1: Document Flow Style', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.evaluate(() => {
      localStorage.setItem('claw_auth_token', 'e2e-test-token');
      localStorage.setItem('claw_auth_user', JSON.stringify({
        userId: 'admin',
        tenantId: 'default',
        expiresAt: Date.now() + 86400000,
      }));
    });
    await page.reload();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
  });

  test('no chat bubbles in layout', async ({ page }) => {
    // 确认无气泡样式
    const bubbles = page.locator('.chat-bubble-ai, .chat-bubble-user');
    await expect(bubbles).toHaveCount(0);
  });

  test('no avatar elements in layout', async ({ page }) => {
    // 确认无头像元素
    const avatars = page.locator('.claw-avatar, .user-avatar');
    await expect(avatars).toHaveCount(0);
  });

  test('no thinking toggle button', async ({ page }) => {
    // 确认无思考开关
    const thinkingToggle = page.locator('.thinking-toggle, button:has-text("思考")');
    await expect(thinkingToggle).toHaveCount(0);
  });
});

// ── F5: Schedule 视图切换 ──

test.describe('F5: Schedule View', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.evaluate(() => {
      localStorage.setItem('claw_auth_token', 'e2e-test-token');
      localStorage.setItem('claw_auth_user', JSON.stringify({
        userId: 'admin',
        tenantId: 'default',
        expiresAt: Date.now() + 86400000,
      }));
    });
    await page.reload();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
  });

  test('clicking "定时任务" switches to schedule view', async ({ page }) => {
    // 点击侧边栏 "定时任务"
    await page.click('.cowork-sidebar >> text=定时任务');
    await page.waitForTimeout(500);

    // Schedule 视图应显示标题和新建按钮
    await expect(page.locator('h2', { hasText: '定时任务' })).toBeVisible();
    await expect(page.locator('button', { hasText: '新建任务' })).toBeVisible();

    // Chat 组件应隐藏
    await expect(page.locator('.chat-input-area')).toHaveCount(0);
    await expect(page.locator('.progress-panel')).toHaveCount(0);

    await page.screenshot({ path: 'e2e/screenshots/schedule-view.png', fullPage: true });
  });

  test('clicking "新任务" switches back to chat view', async ({ page }) => {
    // 先切到 schedule
    await page.click('.cowork-sidebar >> text=定时任务');
    await page.waitForTimeout(500);

    // 再切回 chat
    await page.click('.cowork-sidebar >> text=新任务');
    await page.waitForTimeout(500);

    // Chat 组件应恢复
    await expect(page.locator('.chat-input-area')).toBeVisible();

    await page.screenshot({ path: 'e2e/screenshots/schedule-back-to-chat.png' });
  });

  test('sidebar "定时任务" gets active state', async ({ page }) => {
    await page.click('.cowork-sidebar >> text=定时任务');
    await page.waitForTimeout(500);

    // 应有 active class
    const entry = page.locator('.sidebar-entry--active');
    await expect(entry).toBeVisible();
  });
});

// ── F5: Schedule CRUD 全流程 (API mock) ──

test.describe('F5: Schedule CRUD', () => {
  const mockTasks = [
    {
      id: 'task-e2e-1',
      name: '每日审计',
      cron: '0 9 * * *',
      message: '执行每日审计',
      user_id: 'admin',
      tenant_id: 'default',
      business_type: 'scheduled_task',
      enabled: true,
      created_at: Date.now() / 1000 - 86400,
      last_run_at: Date.now() / 1000 - 3600,
      last_run_status: 'success',
      next_run_at: Date.now() / 1000 + 3600,
    },
    {
      id: 'task-e2e-2',
      name: '周报生成',
      cron: '0 9 * * 1',
      message: '生成周报',
      user_id: 'admin',
      tenant_id: 'default',
      business_type: 'scheduled_task',
      enabled: false,
      created_at: Date.now() / 1000 - 172800,
      last_run_at: null,
      last_run_status: '',
      next_run_at: null,
    },
  ];

  test.beforeEach(async ({ page }) => {
    // 注入 token
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.evaluate(() => {
      localStorage.setItem('claw_auth_token', 'e2e-test-token');
      localStorage.setItem('claw_auth_user', JSON.stringify({
        userId: 'admin',
        tenantId: 'default',
        expiresAt: Date.now() + 86400000,
      }));
    });

    // Mock schedule API
    await page.route('**/api/schedules', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ json: { tasks: mockTasks, total: mockTasks.length } });
      } else if (route.request().method() === 'POST') {
        route.fulfill({ json: { id: 'task-new', name: 'new', cron: '0 9 * * *' } });
      } else {
        route.continue();
      }
    });

    await page.route('**/api/schedules/*/pause', (route) => {
      route.fulfill({ json: { status: 'paused', task_id: 'task-e2e-1' } });
    });

    await page.route('**/api/schedules/*/resume', (route) => {
      route.fulfill({ json: { status: 'resumed', task_id: 'task-e2e-2' } });
    });

    await page.route('**/api/schedules/*', (route) => {
      if (route.request().method() === 'DELETE') {
        route.fulfill({ json: { status: 'deleted', task_id: 'task-e2e-1' } });
      } else if (route.request().method() === 'PUT') {
        route.fulfill({ json: { id: 'task-e2e-1', name: 'updated' } });
      } else {
        route.continue();
      }
    });

    await page.reload();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
  });

  test('schedule list shows tasks from API', async ({ page }) => {
    await page.click('.cowork-sidebar >> text=定时任务');
    await page.waitForTimeout(500);

    // 验证任务列表渲染
    await expect(page.locator('text=每日审计')).toBeVisible();
    await expect(page.locator('text=周报生成')).toBeVisible();
    await expect(page.locator('text=每天 09:00')).toBeVisible();
    await expect(page.locator('text=每周一 09:00')).toBeVisible();

    await page.screenshot({ path: 'e2e/screenshots/schedule-list-data.png', fullPage: true });
  });

  test('create form renders with all fields', async ({ page }) => {
    await page.click('.cowork-sidebar >> text=定时任务');
    await page.waitForTimeout(500);

    // 点击新建
    await page.click('button:has-text("新建任务")');
    await page.waitForTimeout(500);

    // 验证表单
    await expect(page.locator('h2', { hasText: '创建任务' })).toBeVisible();
    await expect(page.locator('text=标题')).toBeVisible();
    await expect(page.locator('text=提示词')).toBeVisible();
    await expect(page.locator('text=计划')).toBeVisible();
    await expect(page.locator('text=业务类型')).toBeVisible();
    await expect(page.locator('text=返回任务列表')).toBeVisible();

    // CronPicker 默认显示 "每天"
    await expect(page.locator('text=每天')).toBeVisible();

    await page.screenshot({ path: 'e2e/screenshots/schedule-create-form.png', fullPage: true });
  });

  test('back button returns to list from create form', async ({ page }) => {
    await page.click('.cowork-sidebar >> text=定时任务');
    await page.waitForTimeout(500);

    await page.click('button:has-text("新建任务")');
    await page.waitForTimeout(500);
    await expect(page.locator('h2', { hasText: '创建任务' })).toBeVisible();

    // 点击返回
    await page.click('text=返回任务列表');
    await page.waitForTimeout(500);

    // 回到列表
    await expect(page.locator('text=每日审计')).toBeVisible();
  });

  test('schedule list shows status indicators', async ({ page }) => {
    await page.click('.cowork-sidebar >> text=定时任务');
    await page.waitForTimeout(500);

    // 成功状态点
    await expect(page.locator('.schedule-status-dot--success')).toBeVisible();
    // 无执行记录状态点
    await expect(page.locator('.schedule-status-dot--none')).toBeVisible();
    // Switch 开关
    const switches = page.locator('.ant-switch');
    await expect(switches).toHaveCount(2);
  });

  test('empty table shows placeholder', async ({ page }) => {
    // 覆盖为空列表
    await page.route('**/api/schedules', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ json: { tasks: [], total: 0 } });
      } else {
        route.continue();
      }
    });

    await page.click('.cowork-sidebar >> text=定时任务');
    await page.waitForTimeout(500);

    await expect(page.locator('text=暂无定时任务')).toBeVisible();
  });
});
