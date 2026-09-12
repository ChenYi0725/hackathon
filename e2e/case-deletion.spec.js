const { test, expect } = require('@playwright/test');

for (const width of [1440, 390]) {
  test(`delete recent case with cancellation and reload (${width}px)`, async ({ page, request }) => {
    await page.setViewportSize({ width, height: 1040 });
    const title = `刪除測試 ${width} <案件>`;
    const created = await request.post('/api/cases', { data: { title } });
    const { case: item } = await created.json();
    await page.goto('/');
    const count = (await (await request.get('/api/cases')).json()).length;
    const deleteButton = page.getByRole('button', { name: `刪除 ${title}`, exact: true });
    await deleteButton.click();
    await expect(page.getByRole('dialog')).toContainText(title);
    await page.getByRole('button', { name: '取消', exact: true }).click();
    await expect(deleteButton).toBeVisible();
    await page.getByRole('textbox', { name: '搜尋案件' }).fill(title);
    await deleteButton.click();
    await page.getByRole('button', { name: '確認刪除', exact: true }).click();
    await expect(page.getByRole('dialog')).not.toBeVisible();
    await expect(deleteButton).toHaveCount(0);
    await expect(page.locator('#case-list')).toContainText('沒有符合的案件');
    await expect(page.locator('.metric').first().locator('strong')).toHaveText(String(count - 1));
    expect((await request.get(`/api/cases/${item.id}`)).status()).toBe(404);
    await page.reload();
    await expect(page.getByRole('heading', { name: '案件工作台', exact: true })).toBeVisible();
    await expect(deleteButton).toHaveCount(0);
  });
}

test('stale deletion shows an error and preserves the case', async ({ page, request }) => {
  const created = await request.post('/api/cases', { data: { title: '版本衝突刪除測試' } });
  const { case: item } = await created.json();
  await page.goto('/');
  await page.getByRole('button', { name: `刪除 ${item.title}`, exact: true }).click();
  await request.put(`/api/cases/${item.id}`, { data: { ...item, title: '其他操作已修改' } });
  await page.getByRole('button', { name: '確認刪除', exact: true }).click();
  await expect(page.locator('#delete-status')).toContainText('重新載入後再刪除');
  expect((await request.get(`/api/cases/${item.id}`)).status()).toBe(200);
  await page.getByRole('button', { name: '取消', exact: true }).click();
  await page.reload();
  await page.getByRole('button', { name: '刪除 其他操作已修改', exact: true }).click();
  await page.getByRole('button', { name: '確認刪除', exact: true }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
});
