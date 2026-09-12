export function setupWorkflow({state,api,modal,esc,save,acceptPayload,render,toast}) {
 const cid=()=>`/api/cases/${state.current.id}`;
 const post=(path,body)=>api(path,{method:'POST',body:JSON.stringify(body)});
 const revision=()=>state.current.revision;
 let working=false;
 let comparisonDraft=null;
 const guard=async(fn)=>{if(working)return;working=true;const root=document.querySelector('#app');try{if(state.dirty&&!await save())return;root.inert=true;await fn()}catch(e){toast(e.message)}finally{root.inert=false;working=false}};
 function links(){if(!state.run)return '';return [['pdf','下載 PDF 審查摘要'],['xlsx','下載已確認勘查資料 Excel'],['bundle','下載完整審查包']].map(([k,label])=>`<a target="_blank" rel="noopener" href="${cid()}/artifacts/${k}?revision=${revision()}&run_id=${encodeURIComponent(state.run.id)}">${label} ↗</a>`).join('')}
 function stale(){
  document.querySelector('.metrics')?.classList.add('stale-results');
  const checks=document.querySelector('.checks');if(checks)checks.innerHTML='<div class="notice">資料已修改，舊結果過期；請儲存並重新審查。</div>';
  const marker=document.querySelector('#review-version');if(marker)marker.textContent='舊結果已過期；請儲存並重新審查';
 }
 function mount(){
  const layout=document.querySelector('.review-layout');if(!layout)return;
  const box=document.createElement('section');box.className='panel';box.style='padding:16px;margin-bottom:18px';
  box.innerHTML=`<div id="review-version">${state.dirty?'舊結果已過期':`檢核版本 ${revision()} · ${esc(state.run?.id.slice(0,12)||'預檢')}`}</div><div class="actions" style="margin-top:12px;flex-wrap:wrap"><button data-core="documents">同案文件／Excel 核對</button><button data-core="comparisons">比較標的管理</button><button data-core="plan">查核計畫</button><button data-core="external">外部資料與 GIS</button><button data-core="decisions">人工覆核</button><button data-core="publish">核對並發布基準</button><button data-core="run">重新檢核</button></div>`;
  layout.before(box);
  if(state.dirty)stale();
 }
 function editComparison(id){
  const old=(state.current.additional_comparisons||[]).find(c=>c.id===id);
  comparisonDraft=old?structuredClone(old):{id:crypto.randomUUID(),name:'',section:'',factors:state.current.factors.map(f=>({...structuredClone(f),comparable:null,entered_rate:null,comparable_grade:null,confirmed:false,evidence:{page:1,quote:'',method:'manual'}})),totals:Object.fromEntries(Object.keys(state.current.totals).map(k=>[k,null])),totals_confirmed:false};
  const d=comparisonDraft;
  modal('比較標的資料核對',`<p>穩定 ID ${esc(d.id)}。改值後請先儲存，再開啟確認；各標的資料與來源分開保存。</p><label>標的名稱<input id="comparison-name" value="${esc(d.name)}"></label><label>地價區段<input id="comparison-section" value="${esc(d.section)}"></label>${d.factors.map(f=>`<details><summary>${esc(f.id)}</summary>${['subject','comparable','entered_rate','subject_grade','comparable_grade'].map(k=>`<label>${esc(k)}<input data-comparison-factor="${esc(f.id)}" data-key="${k}" value="${esc(f[k])}" ${k==='entered_rate'?'type="number" step="any"':''}></label>`).join('')}<label><input type="checkbox" data-comparison-factor="${esc(f.id)}" data-key="confirmed" ${f.confirmed?'checked':''}>已核對本列</label></details>`).join('')}<h3>總計欄位</h3>${Object.entries(d.totals).map(([k,v])=>`<label>${esc(k)}<input type="number" step="any" data-comparison-total="${k}" value="${esc(v)}"></label>`).join('')}<label><input type="checkbox" id="comparison-confirmed" ${d.totals_confirmed?'checked':''}>已核對總計</label>`,`<button data-core="save-comparison">儲存標的並重新審查</button>`);
 }
 async function documents(){
  const ids=[...new Set([...(state.current.document_ids||[]),state.current.document_id].filter(Boolean))];
  const docs=await Promise.all(ids.map(id=>api('/api/documents/'+id)));
  modal('同案文件與儲存格來源',`<p>原始文件每次上傳保存新版本。Excel 依內容辨識；公式只顯示，不執行或採用快取。</p><label>新增 PDF／Excel <input id="case-document" type="file" accept=".pdf,.xlsx"></label><div id="document-progress" role="status"></div>${docs.map(d=>`<section><h3>${esc(d.name)}</h3><a href="/api/documents/${d.id}/file" target="_blank" rel="noopener">開啟原始文件</a>${d.pages.map(p=>p.sheet?`<details><summary>${esc(p.sheet)} · ${esc(p.kind)}${p.hidden?'（隱藏）':''}</summary><pre style="max-height:200px;overflow:auto">${esc(p.text)}</pre></details>`:`<details><summary>第 ${p.page} 頁</summary><pre style="max-height:200px;overflow:auto">${esc(p.text)}</pre></details>`).join('')}</section>`).join('')}<hr><h3>採用儲存格（仍須重新確認）</h3><label>文件<select id="cell-doc">${docs.filter(d=>d.pages.some(p=>p.sheet)).map(d=>`<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select></label><label>工作表名稱<input id="cell-sheet"></label><label>儲存格（例如 J11）<input id="cell-ref"></label><label>寫入欄位<select id="cell-target">${state.current.factors.flatMap(f=>['subject','comparable','entered_rate','subject_grade','comparable_grade'].map(k=>`<option value="factors.${esc(f.id)}.${k}">${esc(f.id)} · ${esc({subject:'比準地條件',comparable:'比較標的條件',entered_rate:'修正率',subject_grade:'比準地等級',comparable_grade:'比較標的等級'}[k])}</option>`)).join('')}${(state.current.additional_comparisons||[]).flatMap(c=>c.factors.flatMap(f=>['subject','comparable','entered_rate','subject_grade','comparable_grade'].map(k=>`<option value="comparisons.${esc(c.id)}.factors.${esc(f.id)}.${k}">${esc(c.name)} · ${esc(f.id)} · ${esc(k)}</option>`))).join('')}${Object.keys(state.current.totals).map(k=>`<option value="totals.${k}">總計 ${k}</option>`).join('')}${(state.current.additional_comparisons||[]).flatMap(c=>Object.keys(c.totals).map(k=>`<option value="comparisons.${esc(c.id)}.totals.${k}">${esc(c.name)} · 總計 ${esc(k)}</option>`)).join('')}${['valuation_date','subject_section','comparable_section','subject_name','comparable_name'].map(k=>`<option>${k}</option>`).join('')}</select></label>`,`<button data-core="apply-cell">採用所選儲存格</button>`);
 }
 document.addEventListener('change',e=>{if(e.target.id!=='case-document')return;const file=e.target.files[0];if(!file)return;guard(async()=>{
   const status=document.querySelector('#document-progress');status.textContent='正在上傳與解析，尚未完成審查…';
   try{const p=await api(`${cid()}/documents?revision=${revision()}&name=${encodeURIComponent(file.name)}`,{method:'POST',body:file});document.querySelector('#dialog').close();await acceptPayload(p);toast('文件解析及版本保存完成，請核對擷取內容。')}
   catch(err){status.textContent='解析失敗：'+err.message;throw err}
 })});
 document.addEventListener('click',e=>{const button=e.target.closest('[data-core]');if(!button)return;e.preventDefault();guard(async()=>{
  const action=button.dataset.core;
  if(action==='source-input'){const check=state.review.checks.find(c=>c.id===button.dataset.check);const ev=check.input_sources[button.dataset.side];state.doc=await api('/api/documents/'+ev.document_id);state.page=ev.page;state.sourceMode='text';state.quote=`${ev.sheet||'PDF'} ${ev.cell||''}: ${ev.quote}`;render();return;}
  if(action==='comparisons')return modal('比較標的管理',`<p>第一筆：${esc(state.current.comparable_name)}（由既有資料核對介面編輯）</p>${(state.current.additional_comparisons||[]).map(c=>`<p>${esc(c.name)} / ${esc(c.section)} <button data-core="edit-comparison" data-id="${esc(c.id)}">編輯與確認</button></p>`).join('')}${(state.current.additional_comparisons||[]).length<2?'<button data-core="edit-comparison">新增比較標的</button>':''}<p>最多三筆；權重合計須為 100%。未發布有來源的加權公式時，只做各標的檢核，不宣稱全案完成。</p>`);
  if(action==='edit-comparison')return editComparison(button.dataset.id);
  if(action==='save-comparison'){
   comparisonDraft.name=document.querySelector('#comparison-name').value;
   comparisonDraft.section=document.querySelector('#comparison-section').value;
   for(const input of document.querySelectorAll('[data-comparison-factor]')){
    const f=comparisonDraft.factors.find(f=>f.id===input.dataset.comparisonFactor);
    f[input.dataset.key]=input.type==='checkbox'?input.checked:input.type==='number'?(input.value===''?null:Number(input.value)):input.value||null;
   }
   for(const input of document.querySelectorAll('[data-comparison-total]'))comparisonDraft.totals[input.dataset.comparisonTotal]=input.value===''?null:Number(input.value);
   comparisonDraft.totals_confirmed=document.querySelector('#comparison-confirmed').checked;
   const body=structuredClone(state.current);body.additional_comparisons=body.additional_comparisons||[];
   const idx=body.additional_comparisons.findIndex(c=>c.id===comparisonDraft.id);
   if(idx<0)body.additional_comparisons.push(comparisonDraft);else body.additional_comparisons[idx]=comparisonDraft;
   const p=await api(cid(),{method:'PUT',body:JSON.stringify(body)});document.querySelector('#dialog').close();await acceptPayload(p);return;
  }
  if(action==='documents')return documents();
  if(action==='apply-cell'){
   const data=Object.fromEntries(['document_id','sheet','cell','target'].map((key,i)=>[key,document.getElementById(['cell-doc','cell-sheet','cell-ref','cell-target'][i]).value]));
   const p=await post(cid()+'/apply-cell',{revision:revision(),...data});document.querySelector('#dialog').close();await acceptPayload(p);return;
  }
  if(action==='run'){await post(cid()+'/review',{revision:revision()});await acceptPayload(await api(cid()));toast('已依最新輸入、規則及證據重新檢核。');return}
  if(action==='plan'){const plan=await api(cid()+'/plan');return modal('案件查核計畫',`<p>本機固定工具計畫；「依據問答 → Agent 自動查詢」可由 Bedrock 選擇查規則、查原文及程式檢核。</p>${plan.items.map(x=>`<p><b>${esc(x.factor_id)}</b>：${esc(x.table_check)}；${x.external_required?'另需外部事實佐證':'可先作表內比對'}</p>`).join('')}`)}
  if(action==='external')return modal('外部查證與空間計算',`<p>官方公園清冊是候選來源，無歷史時點及入口幾何時不宣稱驗證通過。Mock 為合成診斷。</p><label>比較標的<select id="external-comparison"><option value="primary">${esc(state.current.comparable_name)}（第一筆）</option>${(state.current.additional_comparisons||[]).map(c=>`<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('')}</select></label><label>因素<select id="external-factor">${state.current.factors.map(f=>`<option>${esc(f.id)}</option>`).join('')}</select></label><label>模式<select id="external-mode"><option value="live">官方公園清冊</option><option value="mock">Mock API 失敗</option><option value="geometry">GIS 直線距離</option></select></label><label>公園名稱<input id="external-name"></label><label>GIS 參數（WGS84 經度、緯度；角色須為入口、邊界或實測點）<textarea id="geometry-json" style="width:100%;height:180px">${esc(JSON.stringify({method:'straight_line',crs:'EPSG:4326',start:{role:'survey_point',coordinates:[121.4,25]},end:{role:'entrance',coordinates:[121.401,25]},source:'人工輸入待核對',data_date:null},null,2))}</textarea></label>`,`<button data-core="query-external">開始查證</button>`);
  if(action==='query-external'){
   const mode=document.querySelector('#external-mode').value;
   const query=mode==='geometry'?{...JSON.parse(document.querySelector('#geometry-json').value),mode}:{mode,name:document.querySelector('#external-name').value,scenario:'timeout'};
   query.comparison_id=document.querySelector('#external-comparison').value;
   const result=await post(cid()+'/external',{revision:revision(),factor_id:document.querySelector('#external-factor').value,query});
   await acceptPayload(await api(cid()));modal('查證結果',`<p>${esc(result.message)}</p><pre style="white-space:pre-wrap">${esc(JSON.stringify(result,null,2))}</pre>`);return;
  }
  if(action==='decisions')return modal('人工覆核',`<p>接受／拒絕建議只記錄處置；不會把技術錯誤改成通過。要修正數值請採用建議或編輯欄位，再重新確認。</p><label>檢核項目<select id="decision-check">${state.review.checks.map(c=>`<option value="${esc(c.id)}">${esc(c.title)} · ${esc(c.status)}</option>`).join('')}</select></label><label>處置<select id="decision-value"><option value="accept">接受建議，待修正</option><option value="reject">拒絕建議，保留技術判定</option></select></label><label>原因<textarea id="decision-reason"></textarea></label>${(state.dispositions||[]).map(d=>`<p>${esc(d.check_id)} · ${esc(d.decision)} · ${esc(d.reason)} · ${esc(d.at)} ${d.run_id===state.run.id?'':'（歷史處置）'}</p>`).join('')}`,`<button data-core="save-decision">保存人工處置</button>`);
  if(action==='save-decision'){
   await post(cid()+'/decisions',{revision:revision(),run_id:state.run.id,operation_id:crypto.randomUUID(),check_id:document.querySelector('#decision-check').value,decision:document.querySelector('#decision-value').value,reason:document.querySelector('#decision-reason').value});document.querySelector('#dialog').close();await acceptPayload(await api(cid()));return;
  }
  if(action==='publish'){
   const rules=state.rulesets.find(r=>r.id===state.current.ruleset_id);
   return modal('核對並發布案件基準',`<p>${esc(rules.name)} / ${esc(rules.version)} / ${esc(rules.approval_state||'既有未核准範例')}</p><p>發布產生另一個不可覆寫 ID；既有案件仍綁定原版。發布後需到「案件與計算」明確選擇新版。</p><details><summary>完整規則、矩陣與來源</summary><pre style="max-height:260px;overflow:auto">${esc(JSON.stringify(rules,null,2))}</pre></details><label><input id="publish-source" type="checkbox">已核對原文及適用性</label><label><input id="publish-matrix" type="checkbox">已核對級距與矩陣方向</label><label>適用起日<input id="publish-from" type="date"></label><label>適用迄日<input id="publish-to" type="date"></label><label>核對依據／原因<textarea id="publish-reason"></textarea></label>`,`<button data-core="publish-confirm">發布固定版本</button>`);
  }
  if(action==='publish-confirm'){
   await post(`/api/rulesets/${state.current.ruleset_id}/publish`,{source_confirmed:document.querySelector('#publish-source').checked,matrix_confirmed:document.querySelector('#publish-matrix').checked,valid_from:document.querySelector('#publish-from').value,valid_to:document.querySelector('#publish-to').value,reason:document.querySelector('#publish-reason').value});state.rulesets=await api('/api/rulesets');document.querySelector('#dialog').close();render();toast('已發布新 ID；請明確切換案件基準並重新確認。');
  }
 })});
 return {mount,links,stale,editComparison};
}
