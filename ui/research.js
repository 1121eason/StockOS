import {escapeHTML as esc, number} from './domain.mjs';
const select=document.querySelector('#run'), message=document.querySelector('#message'), result=document.querySelector('#result');
let sequence=0, controller;
async function api(path, signal) {
  const response=await fetch(path,{cache:'no-store',signal});
  const body=await response.json();
  if(!response.ok) throw new Error(body.error||'研究資料讀取失敗');
  return body;
}
function inputRows(inputs) {
  return Object.entries(inputs||{}).flatMap(([key,value])=>(Array.isArray(value)?value.map((v,i)=>[`${key} Y${i+1}`,v]):[[key,value]])).map(([key,value])=>`<tr><th scope="row">${esc(key)}</th><td>${value.value===null?'缺值':esc(value.value)}</td><td>${esc(value.available_at||'缺值')}</td><td>${esc(value.source_ids.join(', '))}</td></tr>`).join('');
}
function render(run) {
  const b=run.bundle, v=run.valuation;
  const kind=b.data_kind==='real'?'真實資料聲明 · 尚未驗證':'合成測試資料';
  result.innerHTML=`<section class="panel below"><div class="panel-head"><h2>${esc(b.ticker)} · ${esc(b.name)}</h2><span class="subtle-tag">${esc(kind)}</span></div><div class="panel-body"><dl class="definition"><dt>資料截止 as-of</dt><dd>${esc(b.as_of)}</dd><dt>實際重建時間</dt><dd>${esc(run.generated_at)}</dd><dt>分類</dt><dd>${esc(run.classification)}</dd><dt>不可變結果 ID</dt><dd>${esc(run.run_id)}</dd><dt>輸入雜湊</dt><dd>${esc(run.input_hash)}</dd><dt>正式研究判斷</dt><dd>暫緩 · 未綁定核准流程</dd></dl><p class="callout">五年現金流為研究假設，非已公告的未來財報。資料單位依匯入契約；現金、負債與 FCFF 為 USD，股數為實際股數，每股估值為 USD。</p>${v.status==='available'?`<div class="metric-value">$${number(v.per_share)}<small>USD / 股</small></div><p>DCFPolicyV1 · 僅依匯入研究假設計算</p>${v.negative_equity_warning?'<p class="callout negative">負股權原值保留；不是可成交價格或賣空建議。</p>':''}`:`<h3>估值不可用</h3><p>${esc(v.reason)}</p>`}</div></section><section class="panel below"><div class="panel-head"><h2>唯讀輸入與逐項可用時點</h2></div><div class="table-wrap"><table><caption>利率為小數（0.10 = 10%），FCFF 為年度假設。取得時間不是歷史可用時點的證明。</caption><thead><tr><th scope="col">輸入</th><th scope="col">數值</th><th scope="col">可用時點聲明</th><th scope="col">來源 ID</th></tr></thead><tbody>${inputRows(b.inputs)}</tbody></table></div><div class="panel-body"><p>假設說明：${esc(b.assumptions?.rationale)}</p><p>WACC ±1 個百分點敏感度（非機率 / 信賴區間）：${(v.scenarios||[]).map(s=>`${esc(s.name)}: ${s.status==='available'?'$'+number(s.per_share):'不可用'}`).join('；')}</p></div></section><section class="panel below"><div class="panel-head"><h2>來源聲明與時點</h2></div><div class="panel-body">${b.sources.map(s=>`<article><h3>${esc(s.id)}</h3><p>${esc(s.url)}</p><p>發布 ${esc(s.published_at)} · 取得 ${esc(s.retrieved_at)}</p><p>SHA-256 ${esc(s.sha256)}</p></article>`).join('')||'<p>尚無來源。</p>'}</div></section>`;
}
async function loadRun() {
  controller?.abort();controller=new AbortController();const current=++sequence;
  result.replaceChildren();message.textContent='';
  if(!select.value)return;
  message.textContent='正在讀取已保存結果…';
  try {const run=await api('/api/research/run?id='+encodeURIComponent(select.value),controller.signal);if(current!==sequence)return;render(run);message.textContent='已載入；正式決策仍暫緩。';}
  catch(error){if(error.name!=='AbortError'&&current===sequence)message.textContent='無法讀取：'+error.message;}
}
async function refresh() {
  controller?.abort();controller=new AbortController();const current=++sequence;
  const previous=select.value;select.disabled=true;result.replaceChildren();message.textContent='正在檢查研究儲存區…';
  try {const data=await api('/api/research/runs',controller.signal);if(current!==sequence)return;
    select.replaceChildren(new Option('選擇研究結果',''));
    for(const row of data.runs)select.add(new Option(`${row.ticker} · ${row.data_kind==='real'?'真實聲明':'合成'} · ${row.as_of} · ${row.run_id.slice(0,12)}`,row.run_id));
    message.textContent=data.runs.length?'請選擇結果。':(data.configured?'尚未匯入研究結果。':'未設定獨立研究儲存區。');
    select.disabled=false;
    if(data.runs.some(r=>r.run_id===previous)){select.value=previous;await loadRun();}
  }catch(error){if(error.name!=='AbortError'&&current===sequence){select.replaceChildren(new Option('無法載入',''));message.textContent='無法讀取：'+error.message;}}
  finally{if(current===sequence)select.disabled=false;}
}
select.addEventListener('change',loadRun);document.querySelector('#refresh').addEventListener('click',refresh);refresh();
