// RAG never edits case fields or computes valuation values.
export function setupRag({state,api,modal,esc,save}) {
 document.addEventListener('click',async event=>{
  const action=event.target.closest('[data-action]')?.dataset.action;
  if(action!=='rag')return;
  if(state.dirty&&!await save())return;
  const currentCase={id:state.current.id,revision:state.current.revision,ruleset_id:state.current.ruleset_id};
  const rules=state.rulesets.find(r=>r.id===currentCase.ruleset_id);
  modal('依據問答',`<p>基準：${esc(rules.name)} / ${esc(rules.version)}。只檢索相同地區、用地與適用期間的文件；案件日期需為 YYYY-MM-DD 或民國 YYYMMDD。</p>
   <label for="rag-question">想核對的規則或依據</label><textarea id="rag-question" maxlength="1000" placeholder="例如：面前道路寬度的級距如何規定？"></textarea>
   <p><label><input type="checkbox" id="rag-consent">我已確認問題、案件資料與來源文件符合上雲規範，不含個資或財務資訊。</label></p>
   <div class="actions"><button id="rag-search">本機查找來源</button><button id="rag-answer">AWS 生成說明</button><button id="rag-agent">Agent 自動查詢</button></div>
   <div id="rag-results" aria-live="polite"></div>
   <details><summary>管理這個基準版本的來源 PDF</summary>
    <p>上傳後由 PaddleOCR 在本機辨識。請依文件確認適用期間；這不會修改計算規則，也不代表 OCR 或規則已獲核准。</p>
    <label>適用起日 <input id="rag-from" type="date"></label><label>適用迄日（含） <input id="rag-to" type="date"></label>
    <label>基準 PDF <input id="rag-file" type="file" accept="application/pdf,.pdf"></label>
    <button id="rag-upload">辨識並加入來源</button><div id="rag-documents"></div></details>`);
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
   list.innerHTML=docs.length?docs.map(d=>`<p>${esc(d.name)} · ${esc(d.valid_from)}～${esc(d.valid_to)} <a target="_blank" rel="noopener" href="/api/documents/${encodeURIComponent(d.document_id)}/file">原始 PDF</a></p>`).join(''):'<p>尚未加入來源，請先上傳適用的基準文件。</p>';
  }
  root.querySelector('#rag-upload').onclick=()=>run(async()=>{
   const file=root.querySelector('#rag-file').files[0],from=root.querySelector('#rag-from').value,to=root.querySelector('#rag-to').value;
   if(!file||!from||!to||from>to)throw new Error('請選擇 PDF 並填寫有效的適用起迄日。');
   if(file.size>20*1024*1024)throw new Error('PDF 上限 20 MB。');
   output.textContent='PaddleOCR 正在辨識來源文件…';
   const query=new URLSearchParams({name:file.name,valid_from:from,valid_to:to});
   await api('/api/rulesets/'+currentCase.ruleset_id+'/evidence-documents?'+query,{method:'POST',body:file,headers:{'Content-Type':'application/pdf'}});
   output.textContent='來源已加入。請查找原文並核對 OCR。';await refresh();
  });
  async function query(generate,agent=false){
   const question=root.querySelector('#rag-question').value.trim(),approved=root.querySelector('#rag-consent').checked;
   if(!question)throw new Error('請輸入問題。');
   if(generate&&!approved)throw new Error('請先確認問題與文件的上雲適用性。');
   output.textContent=agent?'Agent 正在選擇工具並查詢…':generate?'正在檢索並生成說明…':'正在本機查找來源…';
   const result=await api('/api/cases/'+currentCase.id+(agent?'/agent-evidence':'/evidence'),{method:'POST',body:JSON.stringify({revision:currentCase.revision,question,...(agent?{}:{generate}),cloud_data_approved:approved})});
   if(state.current.id!==currentCase.id||state.current.revision!==currentCase.revision||state.dirty)throw new Error('案件已變更，舊問答不再顯示。');
   const numbers=new Map(result.hits.map((h,i)=>[h.id,i+1]));
   output.innerHTML=`<p>${esc(result.message)}</p>${result.tool_trace?.length?`<p>工具紀錄：${result.tool_trace.map(t=>esc(t.tool)+'（'+esc(t.status)+'）').join(' → ')}</p>`:''}${result.review?`<details><summary>程式審查結果（版本 ${result.case_revision}）</summary><p>通過 ${result.review.counts.pass}／錯誤 ${result.review.counts.error}／待確認 ${result.review.counts.pending}／缺資料 ${result.review.counts.missing}</p>${result.review.checks.map(c=>`<p>${esc(c.title)}：${esc(c.message)}</p>`).join('')}</details>`:''}${result.status==='no_evidence'?'<p>找不到符合版本、日期與問題的來源。</p>':''}${result.status==='insufficient_evidence'?'<p>現有原文不足以回答，請人工核對或補充文件。</p>':''}
    ${result.external_observations?.length?`<details><summary>外部查證預覽（尚未保存至案件）</summary><p>正式佐證請使用案件的「外部資料與 GIS」；失敗不代表沒有設施。</p><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(JSON.stringify(result.external_observations,null,2))}</pre></details>`:''}
    ${result.statements.map(s=>`<p>${esc(s.text)} ${s.citation_ids.map(id=>`<a href="#rag-cite-${esc(id)}">[${numbers.get(id)}]</a>`).join('')}</p>`).join('')}
    ${result.hits.map((h,i)=>`<article id="rag-cite-${esc(h.id)}"><h4>[${i+1}] ${esc(h.document_name)} · 第 ${h.source.page} 頁</h4><p>基準版本 ${esc(h.ruleset_version)} · ${esc(h.valid_from)}～${esc(h.valid_to)}</p><blockquote style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(h.source.quote)}</blockquote><a target="_blank" rel="noopener" href="/api/documents/${encodeURIComponent(h.source.document_id)}/file#page=${h.source.page}">查看原始 PDF</a></article>`).join('')}`;
  }
  root.querySelector('#rag-search').onclick=()=>run(()=>query(false));
  root.querySelector('#rag-answer').onclick=()=>run(()=>query(true));
  root.querySelector('#rag-agent').onclick=()=>run(()=>query(true,true));
  await run(refresh);
 });
}
