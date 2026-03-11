import { test, expect } from '@playwright/test';

test.describe('Cowork Layout — Static UI', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('test_three_column_layout', async ({ page }) => {
    const sidebar = page.locator('.cowork-sidebar');
    const chatBody = page.locator('.chat-dialog-body');
    const progressPanel = page.locator('.progress-panel');

    await expect(sidebar).toBeVisible();
    await expect(chatBody).toBeVisible();
    await expect(progressPanel).toBeVisible();
  });

  test('test_header_tabs', async ({ page }) => {
    const tabs = page.locator('.header-tabs .header-tab');
    await expect(tabs).toHaveCount(3);

    await expect(tabs.nth(0)).toHaveText('Chat');
    await expect(tabs.nth(1)).toHaveText('Cowork');
    await expect(tabs.nth(2)).toHaveText('Code');

    // Cowork is active by default
    const activeTab = page.locator('.header-tab--active');
    await expect(activeTab).toHaveText('Cowork');
  });

  test('test_sidebar_entries', async ({ page }) => {
    const entries = page.locator('.cowork-sidebar-entries .sidebar-entry');

    await expect(entries.filter({ hasText: 'New task' })).toBeVisible();
    await expect(entries.filter({ hasText: 'Search' })).toBeVisible();
    await expect(entries.filter({ hasText: 'Skills' })).toBeVisible();
  });

  test('test_progress_panel_sections', async ({ page }) => {
    const panel = page.locator('.progress-panel');

    await expect(panel.locator('.progress-section-title', { hasText: 'Progress' })).toBeVisible();
    await expect(panel.locator('.progress-section-title', { hasText: 'Files' })).toBeVisible();
    await expect(panel.locator('.progress-section-title', { hasText: 'Instructions' })).toBeVisible();
    await expect(panel.locator('.progress-section-title', { hasText: 'Context' })).toBeVisible();
  });

  test('test_chat_input', async ({ page }) => {
    const input = page.locator('.chat-input-area textarea');
    await expect(input).toBeVisible();
    await expect(input).toHaveAttribute('placeholder', 'Reply...');
  });

  test('test_chat_mode_hides_sidebars', async ({ page }) => {
    // Click "Chat" tab
    await page.locator('.header-tab', { hasText: 'Chat' }).click();

    // Sidebar and progress panel should not be rendered
    await expect(page.locator('.cowork-sidebar')).toBeHidden();
    await expect(page.locator('.progress-panel')).toBeHidden();

    // Chat body still visible
    await expect(page.locator('.chat-dialog-body')).toBeVisible();
  });

  test('test_cowork_mode_shows_all', async ({ page }) => {
    // Switch to Chat first, then back to Cowork
    await page.locator('.header-tab', { hasText: 'Chat' }).click();
    await expect(page.locator('.cowork-sidebar')).toBeHidden();

    await page.locator('.header-tab', { hasText: 'Cowork' }).click();

    await expect(page.locator('.cowork-sidebar')).toBeVisible();
    await expect(page.locator('.chat-dialog-body')).toBeVisible();
    await expect(page.locator('.progress-panel')).toBeVisible();
  });
});
