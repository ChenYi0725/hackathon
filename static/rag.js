// RAG never edits case fields or computes valuation values.
export function setupRag({state,api,modal,esc,save}) {
 document.addEventListener('click',async event=>{
  const action=event.target.closest('[data-action]')?.dataset.action;
  if(action!=='rag')return;
  if(state.dirty&&!await save())return;
  const currentCase={id:state.current.id,revision:state.current.revision,ruleset_id:state.current.ruleset_id};
  const config=await api('/api/rag/config');
  const rules=state.rulesets.find(r=>r.id===currentCase.ruleset_id);
  modal('依據問答',`<p>基準：${esc(rules.name)} / ${esc(rules.version)}。只檢索相同地區、用地與適用期間的文件；案件日期需為 YYYY-MM-DD 或民國 YYYMMDD。</p>
   <label for="rag-question">想核對的規則或依據</label><textarea id="rag-question" maxlength="1000" placeholder="例如：面前道路寬度的級距如何規定？"></textarea>
   <details><summary>補充量測資料供 Agent 選擇計算（選填）</summary><p>只填已取得的量測值。計算結果先供核對，尚不會寫回案件。</p>
   ${['subject','comparable'].map((side,i)=>`<fieldset><legend>${i?'比較標的':'比準地'}</legend>
    <label>已開闢道路寬度（公尺，以逗號分隔）<input data-measure="opened_road_widths_m" data-side="${side}" placeholder="6, 8, 10"></label>
    <label>已建築使用土地面積（平方公尺）<input data-measure="built_land_area_m2" data-side="${side}" inputmode="decimal"></label>
    <label>區段總面積（平方公尺）<input data-measure="section_total_area_m2" data-side="${side}" inputmode="decimal"></label>
    <label>兩點座標（同一公尺平面 x1,y1,x2,y2）<input data-measure="coordinates_m" data-side="${side}" placeholder="不得填經緯度"></label>
   </fieldset>`).join('')}</details>
   <p><label><input type="checkbox" id="rag-consent">我已確認問題、案件資料與來源文件符合上雲規範，不含個資或財務資訊。</label></p>
   <div class="actions"><button id="rag-search">${config.cloud_retrieval?'AWS 查找來源':'查找來源'}</button><button id="rag-answer">AWS 生成說明</button><button id="rag-agent">Agent 自動查詢</button></div>
   <div id="rag-results" aria-live="polite"></div>
   <details><summary>管理這個基準版本的來源 PDF</summary>
    <p>上傳後由伺服器 OCR 辨識。請依文件確認適用期間；這不會修改計算規則，也不代表 OCR 或規則已獲核准。</p>
    <label>適用起日 <input id="rag-from" type="date"></label><label>適用迄日（含） <input id="rag-to" type="date"></label>
    <label>基準 PDF <input id="rag-file" type="file" accept="application/pdf,.pdf"></label>
    <button id="rag-upload">辨識並加入來源</button>${config.cloud_retrieval?'<button id="rag-sync">同步這個基準至 AWS 知識庫</button><button id="rag-sync-status">查看 AWS 同步狀態</button><p>新增來源或確認新基準後，須同步成功才能在 AWS 查到；同步會上傳此基準的所有來源 PDF 與 OCR 原文。</p>':''}<div id="rag-documents"></div></details>`);
  const root=document.getElementById('dialog');
  const output=root.querySelector('#rag-results');
  const list=root.querySelector('#rag-documents');
  const controls=[...root.querySelectorAll('button,input,textarea')];
  let running=false;
  async function run(fn){
   if(running)return;
   running=true;for(const el of controls)el.disabled=true;
   try{await fn()}catch(error){output.textContent=error.message}
   finally{running=false;for(const el of controls)el.disabled=false}
  }
  async function refresh(){
   const docs=await api('/api/rulesets/'+currentCase.ruleset_id+'/evidence-documents');
   state.workflowDocs=docs;
   list.innerHTML=docs.length?docs.map(d=>`<p>${esc(d.name)} · ${esc(d.valid_from)}～${esc(d.valid_to)} <a target="_blank" rel="noopener" href="/api/documents/${encodeURIComponent(d.document_id)}/file">原始 PDF</a></p>`).join(''):'<p>尚未加入來源，請先上傳適用的基準文件。</p>';
  }
  root.querySelector('#rag-upload').onclick=()=>run(async()=>{
   const file=root.querySelector('#rag-file').files[0],from=root.querySelector('#rag-from').value,to=root.querySelector('#rag-to').value;
   if(!file||!from||!to||from>to)throw new Error('請選擇 PDF 並填寫有效的適用起迄日。');
   if(file.size>20*1024*1024)throw new Error('PDF 上限 20 MB。');
   output.textContent='OCR 正在辨識來源文件…';
   const query=new URLSearchParams({name:file.name,valid_from:from,valid_to:to});
   await api('/api/rulesets/'+currentCase.ruleset_id+'/evidence-documents?'+query,{method:'POST',body:file,headers:{'Content-Type':'application/pdf'}});
   output.textContent='來源已加入。請查找原文並核對 OCR。';await refresh();
  });
  async function query(generate,agent=false){
   const question=root.querySelector('#rag-question').value.trim(),approved=root.querySelector('#rag-consent').checked;
   if(!question)throw new Error('請輸入問題。');
   if((generate||config.cloud_retrieval)&&!approved)throw new Error('請先確認問題與文件的上雲適用性。');
   output.textContent=agent?'Agent 正在選擇工具並查詢…':generate?'正在檢索並生成說明…':'正在查找來源…';
   const measurements={subject:{},comparable:{}};
   if(agent)for(const input of root.querySelectorAll('[data-measure]')){
    const value=input.value.trim();if(!value)continue;
    measurements[input.dataset.side][input.dataset.measure]=['opened_road_widths_m','coordinates_m'].includes(input.dataset.measure)?value.split(/[,，]/).map(x=>x.trim()):value;
   }
   const result=await api('/api/cases/'+currentCase.id+(agent?'/agent-evidence':'/evidence'),{method:'POST',body:JSON.stringify({revision:currentCase.revision,question,...(agent?{measurements}:{generate}),cloud_data_approved:approved})});
   const external=result.api_sources||[];
   const numbers=new Map([...result.hits,...external].map((h,i)=>[h.id,i+1]));
   output.innerHTML=`<p>${esc(result.message)}</p>${result.tool_trace?.length?`<p>工具紀錄：${result.tool_trace.map(t=>esc(t.tool)+'（'+esc(t.status)+'）').join(' → ')}</p>`:''}${result.review?`<details><summary>程式審查結果（版本 ${result.case_revision}）</summary><p>通過 ${result.review.counts.pass}／錯誤 ${result.review.counts.error}／待確認 ${result.review.counts.pending}／缺資料 ${result.review.counts.missing}</p>${result.review.checks.map(c=>`<p>${esc(c.title)}：${esc(c.message)}</p>`).join('')}</details>`:''}${result.status==='no_evidence'?'<p>找不到符合版本、日期與問題的來源。</p>':''}${result.status==='insufficient_evidence'?'<p>現有原文不足以回答，請人工核對或補充文件。</p>':''}
    ${(result.field_gaps||[]).length?`<details open><summary>待補欄位</summary>${result.field_gaps.map(g=>`<p>${esc(g.name)}：${g.missing_fields.map(k=>esc(({subject:'比準地數值',comparable:'比較標的數值',entered_rate:'原填修正率'})[k]||k)).join('、')}</p>`).join('')}</details>`:''}
    ${(result.calculations||[]).map(c=>`<article><h4>${esc(c.check?.title||({average_road_width:'道路平均寬度',building_density:'建築密度',straight_line_distance:'直線距離'})[c.method]||c.method)}</h4><p>${c.check?esc(c.check.message):c.status==='missing'?'量測資料不足，請補充後重試。':esc(c.side==='subject'?'比準地':'比較標的')+'：'+esc(c.result)+' '+esc(c.unit)+'（待核對）'}</p>${c.check?'':`<p>${esc(c.warning||'')}</p>`}</article>`).join('')}
    ${(result.public_data||[]).map(p=>`<details open><summary>政府 API 候選資料（${esc(String(p.record_count||0))} 筆${p.truncated?'，僅顯示前 10 筆':''}）</summary><p>${esc(p.warning||'資料不足，請核對學年度與來源。')}${p.upstream_error_count?' 部分來源查詢失敗。':''}</p>${(p.candidates||[]).map(c=>`<p>${esc(c.name||c.category||'未命名')} · ${esc(c.address||'地址待確認')} <a href="#rag-cite-${esc(c.citation_id)}">[${numbers.get(c.citation_id)}]</a> · 區段歸屬、距離待確認</p>`).join('')}</details>`).join('')}
    ${result.statements.map(s=>`<p>${esc(s.text)} ${s.citation_ids.map(id=>`<a href="#rag-cite-${esc(id)}">[${numbers.get(id)}]</a>`).join('')}</p>`).join('')}
    ${external.map(s=>`<article id="rag-cite-${esc(s.id)}"><h4>[${numbers.get(s.id)}] ${esc(s.title)}</h4><p>${esc(s.locality)} · 查詢時間 ${esc(s.fetched_at)}；估價日期適用性待核對。</p><a href="${esc(s.url)}" target="_blank" rel="noopener">政府資料原始來源</a></article>`).join('')}
    ${result.hits.map((h,i)=>`<article id="rag-cite-${esc(h.id)}"><h4>[${i+1}] ${esc(h.document_name)} · 第 ${h.source.page} 頁</h4><p>基準版本 ${esc(h.ruleset_version)} · ${esc(h.valid_from)}～${esc(h.valid_to)}</p><blockquote style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(h.source.quote)}</blockquote><a target="_blank" rel="noopener" href="/api/documents/${encodeURIComponent(h.source.document_id)}/file#page=${h.source.page}">查看原始 PDF</a></article>`).join('')}`;
  }
  const syncLabels={not_synced:'尚未同步',publishing:'來源上傳中；若工作已中斷，請重新同步',starting:'同步啟動中',in_progress:'同步處理中',complete:'同步完成',failed:'同步失敗，請檢查 AWS 設定並重試',stopping:'停止中',stopped:'已停止'};
  function showSync(result){output.textContent='AWS 知識庫：'+(syncLabels[result.status]||result.status)+(result.ruleset_id?'；此次工作基準：'+result.ruleset_id:'');}
  if(config.cloud_retrieval){
   root.querySelector('#rag-sync').onclick=()=>run(async()=>{
    if(!root.querySelector('#rag-consent').checked)throw new Error('請先確認來源文件符合上雲規範。');
    output.textContent='正在上傳來源並啟動 AWS 知識庫同步…';
    showSync(await api('/api/rulesets/'+currentCase.ruleset_id+'/evidence-sync',{method:'POST',body:JSON.stringify({cloud_data_approved:true})}));
   });
   root.querySelector('#rag-sync-status').onclick=()=>run(async()=>showSync(await api('/api/rag/sync-status')));
  }
  root.querySelector('#rag-search').onclick=()=>run(()=>query(false));
  root.querySelector('#rag-answer').onclick=()=>run(()=>query(true));
  root.querySelector('#rag-agent').onclick=()=>run(()=>query(true,true));
  await run(refresh);
 });
}
