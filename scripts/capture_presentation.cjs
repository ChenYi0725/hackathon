const { chromium } = require('@playwright/test');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

const root = path.resolve(__dirname, '..');
const out = path.join(root, 'deliverables', 'presentation');
const assets = path.join(out, 'assets');
fs.mkdirSync(assets, { recursive: true });
const python = process.env.TEST_PYTHON || path.join(os.homedir(), 'anaconda3', 'python.exe');
const server = spawn(python, ['run.py'], {
  cwd: root, windowsHide: true,
  env: { ...process.env, PORT: '8012', APP_DATA_DIR: path.join(out, '.capture-data-' + Date.now()), OLLAMA_MODEL: '' },
  stdio: ['ignore', 'ignore', 'pipe']
});
let browser;
server.stderr.on('data', () => {});
async function main() {
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch('http://127.0.0.1:8012/api/health')).ok) break; } catch {}
    if (i === 59) throw new Error('Capture service did not start');
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1050 }, deviceScaleFactor: 1.5 });
  await page.goto('http://127.0.0.1:8012/');
  await page.locator('.case-table tbody tr').first().waitFor();
  await page.screenshot({ path: path.join(assets, 'dashboard.png') });
  await page.getByRole('button', { name: '開啟 金山區商業用地｜錯誤示範', exact: true }).click();
  await page.getByRole('button', { name: '文字版', exact: true }).click();
  await page.locator('[data-action="filter"][data-id="error"]').click();
  const road = page.locator('.check').filter({ has: page.getByRole('heading', { name: '面前道路寬度', exact: true }) });
  await road.getByRole('button', { name: '原文 p.3', exact: true }).click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: path.join(assets, 'review-errors.png') });
  await page.locator('.review-layout').screenshot({ path: path.join(assets, 'review-detail.png') });
  await road.getByRole('button', { name: '基準 p.7', exact: true }).click();
  await page.getByRole('dialog').screenshot({ path: path.join(assets, 'rule-matrix.png') });
  await page.getByRole('button', { name: '關閉', exact: true }).click();
  await road.getByRole('button', { name: '採用建議', exact: true }).click();
  await page.getByRole('button', { name: '修訂紀錄', exact: true }).click();
  await page.getByRole('dialog').getByText('採用建議：面前道路寬度', { exact: true }).waitFor();
  await page.getByRole('dialog').screenshot({ path: path.join(assets, 'audit.png') });
  await page.getByRole('button', { name: '關閉', exact: true }).click();
  await page.getByRole('button', { name: '返回案件工作台', exact: true }).click();
  await page.getByRole('button', { name: '開啟 金山區商業用地｜原始範例', exact: true }).click();
  await page.getByRole('button', { name: '文字版', exact: true }).count().then(async n => {
    if (n) await page.getByRole('button', { name: '文字版', exact: true }).click();
  });
  await page.locator('[data-action="filter"][data-id="pending"]').click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: path.join(assets, 'review-original.png') });
  const cases = await (await fetch('http://127.0.0.1:8012/api/cases')).json();
  const original = cases.find(c => !c.demo);
  fs.writeFileSync(path.join(assets, 'capture-manifest.json'), JSON.stringify({
    capturedAt: new Date().toISOString(), source: 'Isolated instance of the actual application',
    existingUserCasesModified: false, originalCounts: original.counts,
    note: 'Error-demo screenshots show explicitly seeded synthetic errors. No AI inference was enabled.'
  }, null, 2));
  console.log('Captured six application screenshots in ' + assets);
}
main().catch(e => { console.error(e); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  server.kill();
});
