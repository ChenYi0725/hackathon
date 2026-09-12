const {test,expect}=require('@playwright/test');

for(const width of [1440,390]){
 test(`Agent public API citations at width ${width}`,async({page})=>{
  await page.setViewportSize({width,height:900});
  await page.goto('/');
  await page.getByRole('button',{name:'建立錯誤示範'}).click();
  await page.getByRole('button',{name:'依據問答',exact:true}).click();
  await page.locator('#rag-question').fill('查詢樹林官方資料');
  const sourceUrl='https://data.ntpc.gov.tw/api/datasets/12345678-1234-1234-1234-123456789abc/json?page=0&size=1';
  await page.route('**/api/cases/*/agent-evidence',route=>route.fulfill({json:{
   status:'draft',message:'公開資料待核對',hits:[],review:null,
   statements:[{text:'合成資料來源',citation_ids:['public1']}],
   tool_trace:[{tool:'search_public_datasets',status:'success'},{tool:'read_public_dataset',status:'success'}],
   public_sources:[{id:'public1',title:'合成樹林資料',source_url:sourceUrl,fetched_at:'2026-09-12T00:00:00Z',
    page:0,message:'取得時間不是生效日；適用性待確認。',quote:'<img src=x onerror="window.apiInjected=true">'}]
  }}));
  await page.locator('#rag-consent').check();
  await page.locator('#rag-agent').click();
  await expect(page.locator('#rag-results')).toContainText('read_public_dataset（success）');
  await page.getByRole('link',{name:'[1]',exact:true}).click();
  await expect(page.locator('#rag-cite-public1')).toContainText('取得時間不是生效日');
  await expect(page.getByRole('link',{name:'查看官方 API 原始資料'})).toHaveAttribute('href',sourceUrl);
  await expect(page.locator('#rag-cite-public1')).toContainText('<img');
  expect(await page.evaluate(()=>window.apiInjected)).toBeUndefined();
 });
}
