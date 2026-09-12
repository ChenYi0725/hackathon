const { test, expect } = require('@playwright/test');
const fs = require('node:fs/promises');

test('separate form downloads, list PDF and errors on desktop and mobile', async ({ page }) => {
  test.skip(!process.env.FORM_TEMPLATE_DIR, 'Supply local workbook templates for export acceptance');
  await page.goto('/');
  await page.getByRole('button', { name: '建立錯誤示範' }).click();
  await page.getByRole('button', { name: '匯出成果' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('link', { name: '審查報告 · 列印 / 另存 PDF' })).toBeVisible();
  for (const kind of ['report-pdf', 'table3-xlsx', 'table3-pdf', 'table4-xlsx', 'table4-pdf', 'table5-xlsx', 'table5-pdf']) {
    const pending = page.waitForEvent('download');
    await dialog.locator(`[data-id="${kind}"]`).click();
    const download = await pending;
    const bytes = await fs.readFile(await download.path());
    expect(bytes.subarray(0, kind.endsWith('xlsx') ? 2 : 5).toString()).toBe(kind.endsWith('xlsx') ? 'PK' : '%PDF-');
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
