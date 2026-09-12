const { test, expect } = require('@playwright/test');
const path = require('node:path');

test('dashboard, evidence, fix, edit, persist and export', async ({ page }) => {
  const errors=[];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '案件工作台', exact: true })).toBeVisible();
  await expect(page.locator('.case-table tbody tr')).toHaveCount(2);
  await page.screenshot({ path: 'test-results/dashboard.png', fullPage: true });
  await page.getByRole('button', { name: '建立錯誤示範' }).click();
  await expect(page.getByRole('heading', { name: '金山區商業用地｜錯誤示範', exact: true })).toBeVisible();
  const road=page.locator('.check').filter({has:page.getByRole('heading',{name:'面前道路寬度',exact:true})});
  await road.getByRole('button',{name:'基準 p.7'}).click();
  await expect(page.getByRole('dialog')).toContainText('15 m 以上，未滿 20 m');
  await page.getByRole('button',{name:'關閉',exact:true}).click();
  await road.getByRole('button',{name:'採用建議'}).click();
  await expect(road.locator('.pill')).toHaveText('通過');
  await page.getByRole('button',{name:'資料核對',exact:true}).click();
  await page.locator('[data-factor="school"][data-key="subject"]').fill('150');
  await page.getByRole('button',{name:'儲存並重新審查'}).click();
  await expect(page.locator('.dirty-indicator')).toHaveText('所有變更已儲存');
  await page.getByRole('button',{name:'審查結果',exact:true}).click();
  const school=page.locator('.check').filter({has:page.getByRole('heading',{name:'接近學校之程度',exact:true})});
  await expect(school.locator('.pill')).toHaveText('通過');
  await school.getByRole('button',{name:'原文 p.3'}).click();
  await page.getByRole('button',{name:'文字版',exact:true}).click();
  await expect(page.locator('.source-text')).toContainText('比較法調查估價表');
  await page.screenshot({ path: 'test-results/review.png', fullPage: true });
  await page.getByRole('button',{name:'修訂紀錄',exact:true}).click();
  await expect(page.getByRole('dialog')).toContainText('採用建議：面前道路寬度');
  await page.getByRole('button',{name:'關閉',exact:true}).click();
  await page.getByRole('button',{name:'匯出成果',exact:true}).click();
  const href=await page.getByRole('link',{name:'審查報告 · 列印 / 另存 PDF ↗'}).getAttribute('href');
  const report=await page.request.get(href);
  expect(report.status()).toBe(200);
  expect(await report.text()).toContain('尚有疑點或待確認項目');
  await page.getByRole('button',{name:'關閉',exact:true}).click();
  await page.getByRole('button',{name:'返回案件工作台',exact:true}).click();
  await page.getByRole('textbox',{name:'搜尋案件'}).fill('錯誤示範');
  await expect(page.locator('.case-table tbody tr')).toHaveCount(2);
  expect(errors).toEqual([]);
});

test('scanned PDF upload through PaddleOCR and disabled Bedrock message', async ({ page }) => {
  test.setTimeout(120000);
  await page.goto('/');
  await page.locator('#pdf-input').setInputFiles(path.join(__dirname,'..','tests','fixtures','synthetic-scanned.pdf'));
  await expect(page.getByRole('heading',{name:'synthetic-scanned',exact:true})).toBeVisible({timeout:110000});
  await page.getByRole('button',{name:'文字版',exact:true}).click();
  await page.locator('#source-page').selectOption('1');
  await expect(page.locator('.source-text')).toContainText('寬度');
  await page.getByRole('button',{name:'資料核對',exact:true}).click();
  await expect(page.locator('[data-factor="width"][data-key="confirmed"]')).not.toBeChecked();
  await page.getByRole('button',{name:'AWS AI 抽取',exact:true}).click();
  await expect(page.getByRole('dialog')).toContainText('目前未啟用 Bedrock');
});

test('new rule version validates and can be selected for case', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button',{name:'評價基準庫',exact:true}).click();
  await expect(page.locator('.rule-card')).toHaveCount(47);
  await page.getByRole('button',{name:'建立基準版本',exact:true}).click();
  const rules=JSON.parse(await page.locator('#rule-json').inputValue());
  rules.name='瀏覽器測試基準';rules.version='test-1';
  await page.locator('#rule-json').fill(JSON.stringify(rules));
  await page.getByRole('button',{name:'驗證並建立版本',exact:true}).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await expect(page.locator('.content > .notice')).toContainText('瀏覽器測試基準');
  await page.getByRole('button',{name:/案件工作台/}).click();
  await page.getByRole('button',{name:'建立案件',exact:true}).click();
  await page.getByRole('button',{name:'案件與計算',exact:true}).click();
  await page.locator('[data-case="title"]').fill('持久化測試案件');
  await page.locator('[data-case="ruleset_id"]').selectOption({label:'瀏覽器測試基準 / test-1'});
  await page.getByRole('button',{name:'儲存並重新審查'}).click();
  await expect(page.getByRole('heading',{name:'持久化測試案件',exact:true})).toBeVisible();
  await page.reload();
  await page.getByRole('button',{name:'開啟 持久化測試案件',exact:true}).click();
  await expect(page.getByRole('heading',{name:'持久化測試案件',exact:true})).toBeVisible();
});

test('mobile navigation and layout fit the viewport', async ({ page }) => {
  await page.setViewportSize({width:390,height:844});
  await page.goto('/');
  await expect(page.getByRole('heading',{name:'案件工作台',exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:'test-results/mobile.png',fullPage:true});
  await page.getByRole('button',{name:'使用指南',exact:true}).click();
  await expect(page.getByRole('heading',{name:'使用指南',exact:true})).toBeVisible();
});

test('Bedrock consent, preview and manual confirmation state', async ({ page }) => {
  let cloudRequests = 0;
  await page.route('**/api/health', route => route.fulfill({json:{status:'ok',ai_configured:true,ai_provider:'bedrock',ai_model:'synthetic-test-model',ai_region:'us-west-2'}}));
  await page.route('**/api/cases/*/ai', async route => {
    cloudRequests++;
    const body = route.request().postDataJSON();
    expect(body.cloud_data_approved).toBe(true);
    await route.fulfill({json:{revision:body.revision,message:'合成 AI 草稿',factors:[{id:'width',subject:'5',comparable:'7',entered_rate:0,confirmed:false,evidence:{page:1,quote:'寬度 5 7',method:'bedrock:test'}}]}});
  });
  await page.goto('/');
  await page.getByRole('button',{name:'建立錯誤示範'}).click();
  await page.getByRole('button',{name:'資料核對',exact:true}).click();
  await page.locator('[data-factor="width"][data-key="note"]').fill('保留人工核對備註');
  await page.getByRole('button',{name:'儲存並重新審查'}).click();
  await page.getByRole('button',{name:'AWS AI 抽取',exact:true}).click();
  await expect(page.getByRole('dialog')).toContainText('競賽禁止');
  await page.getByRole('button',{name:'開始抽取',exact:true}).click();
  expect(cloudRequests).toBe(0);
  await page.locator('#cloud-data-approved').check();
  await page.getByRole('button',{name:'開始抽取',exact:true}).click();
  await expect(page.getByRole('dialog')).toContainText('合成 AI 草稿');
  await page.locator('[data-ai-index="0"]').check();
  await page.getByRole('button',{name:'套用勾選草稿',exact:true}).click();
  await expect(page.locator('[data-factor="width"][data-key="confirmed"]')).not.toBeChecked();
  await expect(page.locator('[data-factor="width"][data-key="note"]')).toHaveValue('保留人工核對備註');
  expect(cloudRequests).toBe(1);
  await page.screenshot({path:'test-results/bedrock-draft.png',fullPage:true});
});
