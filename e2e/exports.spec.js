const { test, expect } = require('@playwright/test');
const fs = require('node:fs/promises');

test('Excel downloads and errors on desktop and mobile', async ({ page }) => {
  await page.goto('/');
  await page.locator('.case-table tbody tr').first().getByRole('button').click();
  await page.getByRole('button', { name: '匯出成果' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('link', { name: '審查報告 · HTML' })).toBeVisible();
  await expect(dialog.locator('[data-action="download-export"][data-id$="-pdf"]')).toHaveCount(0);
  await expect(dialog.getByRole('link', { name: '下載 PDF 審查摘要 ↗', exact: true })).toBeVisible();
  for (const kind of ['table3-xlsx', 'table4-xlsx', 'table5-xlsx']) {
    const pending = page.waitForEvent('download');
    await dialog.locator(`[data-id="${kind}"]`).click();
    const download = await pending;
    const bytes = await fs.readFile(await download.path());
    expect(bytes.subarray(0, 2).toString()).toBe('PK');
    await expect(page.locator('#export-status')).toContainText('檔案已下載');
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: 'test-results/export-mobile.png', fullPage: true });
  await page.route('**/export/table3-xlsx?*', route => route.fulfill({
    status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '模板尚未設定' })
  }));
  await dialog.locator('[data-id="table3-xlsx"]').click();
  await expect(page.locator('#export-status')).toHaveText('模板尚未設定');
  await expect(dialog.locator('[data-id="table3-xlsx"]')).toBeEnabled();
});
