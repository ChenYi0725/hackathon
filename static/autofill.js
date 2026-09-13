// The server selects registered sources/functions and owns every candidate value.
export function setupAutofill({state,api,modal,esc,save,acceptPayload}) {
 const fieldNames={case_number:'案號',valuation_date:'估價基準日',subject_name:'比準地名稱',comparable_name:'比較標的名稱',subject_address:'比準地地址',comparable_address:'比較標的地址',subject_section:'比準地區段號',comparable_section:'比較標的區段號',subject:'比準地',comparable:'比較標的',subject_grade:'比準地等級',comparable_grade:'比較標的等級',entered_rate:'修正率',normal_price:'正常單價',time_rate:'日期調整率',adjusted_price:'基準日單價',regional_detail:'區域因素合計',regional_carried:'跨表區域調整率',individual:'個別因素合計',absolute:'絕對值加總',trial_price:'試算價格',weight:'權重'};
 const safeUrl=value=>{try{const u=new URL(value);return u.protocol==='https:'&&['data.ntpc.gov.tw','stats.moe.gov.tw'].includes(u.hostname)?u.href:null}catch{return null}};
 document.addEventListener('click',async event=>{
  if(event.target.closest('[data-action]')?.dataset.action!=='autofill')return;
  if(state.dirty&&!await save())return;
  const current={id:state.current.id,revision:state.current.revision};
  const rules=state.rulesets.find(r=>r.id===state.current.ruleset_id);
  const names=Object.fromEntries(rules.rules.map(r=>[r.id,r.name]));
  modal('依來源自動選填',`<p>重新讀取已辨識的文件、查詢已登錄的政府資料，並呼叫既有分級與計算函式。只補空欄，保留人工填值。</p>
   <label>學年度（查學校時必填）<input id="autofill-year" type="number" min="103" max="200" placeholder="依題目填寫，例如 111"></label>
   <label><input id="autofill-public" type="checkbox" checked>查詢新北市／教育部現有公開資料</label>
   <details><summary>補充已有來源的量測資料（選填）</summary><p>沒有數據請留空，系統不會將缺值當作零。</p>${['subject','comparable'].map(side=>`<fieldset><legend>${side==='subject'?'比準地':'比較標的'}</legend><label>已開闢道路寬度（公尺，以逗號分隔）<input id="autofill-${side}-roads" placeholder="6, 8, 10"></label><label>已建築使用土地面積（㎡）<input id="autofill-${side}-built" type="number" min="0"></label><label>區段總面積（㎡）<input id="autofill-${side}-area" type="number" min="0"></label><label>量測資料來源<input id="autofill-${side}-source" placeholder="文件名稱、頁碼或勘查紀錄"></label></fieldset>`).join('')}</details>
   <p class="smalltext">地址／地號定位服務尚未設定。設施清冊可供核對，查無結果不會自動勾「無」。</p>
   <button id="autofill-start" class="primary">查詢並產生選填草稿</button><div id="autofill-output" aria-live="polite"></div>`);
  const root=document.getElementById('dialog'),output=root.querySelector('#autofill-output'),start=root.querySelector('#autofill-start');
  async function showJob(jobId){
   start.disabled=true;
   try {
    while(root.open&&output.isConnected){
     const job=await api(`/api/cases/${current.id}/autofill/jobs/${jobId}`);
     if(job.status==='error'||job.status==='stale')throw new Error(job.error);
     if(job.status==='done'){
      const data=job.result;
      output.innerHTML=`<h3>可補 ${data.patches.length} 個欄位</h3><p>${esc(data.message)}</p>${data.patches.map(p=>`<div class="ai-card"><strong>${esc(names[p.factor_id]||'案件欄位')} · ${esc(fieldNames[p.field]||p.field)}</strong><p>${esc(p.value)}</p><small>來源：${esc(p.source.reference)}<br>${esc(p.source.detail)}</small></div>`).join('')}
       <button id="autofill-apply" class="primary" ${data.patches.length?'':'disabled'}>套用全部有來源的空欄</button>
       <h3>各欄位查詢狀態</h3>${data.coverage.map(c=>`<p><strong>${esc(c.name)}</strong>：${c.missing_fields.length?'仍待補 '+c.missing_fields.map(f=>esc(fieldNames[f]||f)).join('、'):'已有草稿值'}<br><small>${c.sources.length?'已登錄來源：'+c.sources.map(s=>esc(s.name)).join('、'):'沒有對應的政府資料來源；使用文件或既有計算'}</small></p>`).join('')}
       <h3>政府資料來源</h3>${data.public_data.sources.map(s=>{const url=safeUrl(s.url);return `<p>${url?`<a href="${esc(url)}" target="_blank" rel="noopener">${esc(s.title)}</a>`:esc(s.title)} · ${esc(s.status)}<br><small>${esc(s.period)} · ${esc(s.fetched_at)}</small></p>`}).join('')||'<p>本次沒有取得政府資料來源。</p>'}
       <details><summary>查到 ${data.public_data.record_count||0} 筆候選設施（尚未認定區段歸屬）</summary>${data.public_data.candidates.map(c=>`<p>${esc(c.name)} · ${esc(c.address||'未提供地址')}</p>`).join('')}</details>
       <h3>仍需補充</h3>${[...data.gaps,...data.public_data.gaps].map(g=>`<p>${esc(names[g.factor_id]||fieldNames[g.field]||g.source_key||'案件')}：${esc(g.reason)}</p>`).join('')||'<p>請核對來源與結果後確認。</p>'}`;
      root.querySelector('details').open=false;
      output.scrollIntoView({block:'start'});
      root.querySelector('#autofill-apply').onclick=async e=>{
       e.target.disabled=true;
       try{const payload=await api(`/api/cases/${current.id}/autofill/apply`,{method:'POST',body:JSON.stringify({revision:current.revision,token:data.token})});state.autofillJob=null;root.close();await acceptPayload(payload)}catch(error){output.insertAdjacentHTML('afterbegin',`<p role="alert">${esc(error.message)}</p>`);e.target.disabled=false}
      };
      return;
     }
     output.textContent=job.status==='queued'?'排隊查詢中…':'正在查詢資料並計算；可關閉視窗，稍後再開啟查看。';
     await new Promise(resolve=>setTimeout(resolve,1500));
    }
   }catch(error){output.textContent=error.message;state.autofillJob=null}
   finally{start.disabled=false}
  }
  start.onclick=async()=>{
   start.disabled=true;
   try{
    const year=root.querySelector('#autofill-year').value;
    const body={revision:current.revision,school_year:year?Number(year):null,query_public_data:root.querySelector('#autofill-public').checked};
    for(const side of ['subject','comparable']){
     const roads=root.querySelector(`#autofill-${side}-roads`).value.trim(),built=root.querySelector(`#autofill-${side}-built`).value,area=root.querySelector(`#autofill-${side}-area`).value;
     body[side]={opened_road_widths_m:roads?roads.split(/[,，、]/).map(s=>s.trim()):null,built_land_area_m2:built||null,section_total_area_m2:area||null,source:root.querySelector(`#autofill-${side}-source`).value};
    }
    const job=await api(`/api/cases/${current.id}/autofill/jobs`,{method:'POST',body:JSON.stringify(body)});
    state.autofillJob={...current,jobId:job.job_id};await showJob(job.job_id);
   }catch(error){output.textContent=error.message}finally{start.disabled=false}
  };
  if(state.autofillJob?.id===current.id&&state.autofillJob.revision===current.revision)await showJob(state.autofillJob.jobId);
 });
}
