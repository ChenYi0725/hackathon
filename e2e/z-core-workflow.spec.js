const {test,expect}=require('@playwright/test');
const path=require('node:path');

async function createCase(request){
 const rule={name:'瀏覽器合成流程',version:'browser-core-1',locality:'合成區',land_use:'合成用地',source:'瀏覽器固定驗收矩陣',direction:'列：比準地；欄：比較標的；矩陣值為百分點',rules:[
  {id:'width',name:'寬度',group:'道路',unit:'m',scope:'individual',source_page:1,bands:[{label:'窄',low:0,high:10},{label:'寬',low:10,high:null}],matrix:[[0,-2],[2,0]]},
  {id:'region',name:'區域條件',group:'區域',unit:'',scope:'regional',source_page:1,bands:[{label:'甲',values:['甲']},{label:'乙',values:['乙']}],matrix:[[0,-1],[1,0]]}]};
 const draft=await(await request.post('/api/rulesets',{data:rule})).json();
 const published=await(await request.post(`/api/rulesets/${draft.id}/publish`,{data:{reason:'人工核對合成測試',source_confirmed:true,matrix_confirmed:true,valid_from:'2026-01-01',valid_to:'2026-12-31'}})).json();
 return (await(await request.post('/api/cases',{data:{title:'瀏覽器核心流程 '+Date.now(),ruleset_id:published.id,valuation_date:'2026-09-01',locality:'合成區',land_use:'合成用地',subject_name:'合成比準地',subject_section:'S1',comparable_name:'合成比較標的',comparable_section:'S2',factors:[{id:'width',subject:'12',comparable:'8',entered_rate:2},{id:'region',subject:'甲',comparable:'甲',subject_grade:'甲',comparable_grade:'甲',entered_rate:0}],totals:{normal_price:100,time_rate:0,adjusted_price:100,regional_detail:0,regional_carried:0,individual:2,absolute:2,trial_price:102,weight:100}}})).json()).case;
}

test('real browser Excel upload, source adoption, confirmation, disposition and PDF export',async({page,request})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const c=await createCase(request);
 await page.goto('/');await page.getByRole('button',{name:'開啟 '+c.title,exact:true}).click();
 await page.getByRole('button',{name:'同案文件／Excel 核對',exact:true}).click();
 await page.locator('#case-document').setInputFiles(path.join(__dirname,'../tests/fixtures/core-workflow.xlsx'));
 await expect(page.getByRole('dialog')).not.toBeVisible();
 await page.getByRole('button',{name:'同案文件／Excel 核對',exact:true}).click();
 await expect(page.getByRole('dialog')).toContainText('勘查 · survey');
 await page.locator('#cell-sheet').fill('勘查');await page.locator('#cell-ref').fill('J11');
 await page.locator('#cell-target').selectOption('factors.width.subject');
 await page.getByRole('button',{name:'採用所選儲存格',exact:true}).click();
 await expect(page.getByRole('dialog')).not.toBeVisible();
 await page.getByRole('button',{name:'資料核對',exact:true}).click();
 await expect(page.locator('[data-factor="width"][data-key="subject"]')).toHaveValue('12');
 await page.locator('[data-factor="width"][data-key="confirmed"]').check();
 await page.getByRole('button',{name:'區域因素',exact:true}).click();
 await page.locator('[data-factor="region"][data-key="confirmed"]').check();
 await page.getByRole('button',{name:'案件與計算',exact:true}).click();
 await page.locator('[data-case="totals_confirmed"]').check();
 await page.getByRole('button',{name:'儲存並重新審查',exact:true}).click();
 let result=await(await request.get('/api/cases/'+c.id)).json();expect(result.review.complete).toBe(true);
 await page.getByRole('button',{name:'審查結果',exact:true}).click();
 const row=page.locator('.check').filter({has:page.getByRole('heading',{name:'寬度',exact:true})});
 await row.getByRole('button',{name:'原文 p.1',exact:true}).click();
 await expect(page.locator('.source-text')).toContainText('J11: 12');
 await page.getByRole('button',{name:'匯出成果',exact:true}).click();
 const link=await page.getByRole('link',{name:'下載 PDF 審查摘要 ↗',exact:true}).getAttribute('href');
 const downloadPromise=page.waitForEvent('download');await page.getByRole('link',{name:'下載 PDF 審查摘要 ↗',exact:true}).click();
 const download=await downloadPromise;expect(download.suggestedFilename()).toBe('review.pdf');
 await download.saveAs('test-results/core-review.pdf');
 await page.getByRole('button',{name:'關閉',exact:true}).click();
 await page.getByRole('button',{name:'資料核對',exact:true}).click();
 await page.getByRole('button',{name:'個別因素',exact:true}).click();
 await page.locator('[data-factor="width"][data-key="entered_rate"]').fill('9');
 await expect(page.locator('#review-version')).toContainText('過期');
 await page.getByRole('button',{name:'儲存並重新審查',exact:true}).click();
 expect((await request.get(link)).status()).toBe(409);
 await page.locator('[data-factor="width"][data-key="confirmed"]').check();
 await page.getByRole('button',{name:'儲存並重新審查',exact:true}).click();
 await page.getByRole('button',{name:'人工覆核',exact:true}).click();
 await page.locator('#decision-check').selectOption('width');await page.locator('#decision-value').selectOption('reject');await page.locator('#decision-reason').fill('合成拒絕理由，保留技術錯誤');
 await page.getByRole('button',{name:'保存人工處置',exact:true}).click();
 await expect(page.getByRole('dialog')).not.toBeVisible();
 result=await(await request.get('/api/cases/'+c.id)).json();expect(result.review.checks.find(x=>x.id==='width').status).toBe('error');expect(result.dispositions).toHaveLength(1);
 await page.getByRole('button',{name:'外部資料與 GIS',exact:true}).click();await page.locator('#external-mode').selectOption('mock');await page.getByRole('button',{name:'開始查證',exact:true}).click();
 await expect(page.getByRole('dialog')).toContainText('合成診斷：timeout');
 result=await(await request.get('/api/cases/'+c.id)).json();expect(result.review.complete).toBe(false);expect(result.review.checks.some(x=>x.external?.mode==='mock')).toBe(true);
 await page.getByRole('button',{name:'關閉',exact:true}).click();
 await page.screenshot({path:'test-results/core-workflow.png',fullPage:true});
 expect(errors).toEqual([]);
});

test('browser publishes a new immutable ruleset and adds an independent comparison',async({page,request})=>{
 const c=await createCase(request);await page.goto('/');await page.getByRole('button',{name:'開啟 '+c.title,exact:true}).click();
 await page.getByRole('button',{name:'比較標的管理',exact:true}).click();await page.getByRole('button',{name:'新增比較標的',exact:true}).click();
 await page.locator('#comparison-name').fill('合成第二比較標的');await page.locator('#comparison-section').fill('S3');
 await page.getByRole('button',{name:'儲存標的並重新審查',exact:true}).click();await expect(page.getByRole('dialog')).not.toBeVisible();
 let p=await(await request.get('/api/cases/'+c.id)).json();expect(p.case.additional_comparisons).toHaveLength(1);expect(p.case.comparable_name).toBe('合成比較標的');expect(p.review.complete).toBe(false);
 const draft=await(await request.post('/api/rulesets',{data:{...(await(await request.get('/api/rulesets')).json()).find(r=>r.id===c.ruleset_id),version:'browser-new-draft'}})).json();
 p.case.ruleset_id=draft.id;await request.put('/api/cases/'+c.id,{data:p.case});
 await page.reload();await page.getByRole('button',{name:'開啟 '+c.title,exact:true}).click();
 await page.getByRole('button',{name:'核對並發布基準',exact:true}).click();await page.locator('#publish-source').check();await page.locator('#publish-matrix').check();
 await page.locator('#publish-from').fill('2026-01-01');await page.locator('#publish-to').fill('2026-12-31');await page.locator('#publish-reason').fill('合成原文與矩陣核對');
 await page.getByRole('button',{name:'發布固定版本',exact:true}).click();await expect(page.getByRole('dialog')).not.toBeVisible();
 p=await(await request.get('/api/cases/'+c.id)).json();expect(p.case.ruleset_id).toBe(draft.id);
 const versions=await(await request.get('/api/rulesets')).json();expect(versions.some(r=>r.approved_from===draft.id&&r.approval_state==='published')).toBe(true);
});
