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
function definitionRows(rows) {
  return rows.map(([label,value])=>`<dt>${esc(label)}</dt><dd>${esc(value===undefined?'未提供':value)}</dd>`).join('');
}
function absentTimestamp(value, description) {
  return value===null?`NULL · ${description}`:value;
}
function sourceMarkup(source, schema2) {
  // Schema 1 has no kind field and retains its external-document meaning.
  const kind=schema2?source.kind:'external_document';
  if(kind==='internal_policy_artifact') {
    return `<article class="research-source internal-policy-source"><h3>${esc(source.id)}</h3><p class="source-kind">內部政策原件 · internal_policy_artifact</p><p class="callout">固定研究政策，非依報酬擬合。建立、生效與本次觀察均不是歷史發布證明；可用時點以本次觀察為保守界線。</p><dl class="definition">${definitionRows([
      ['來源類型 source_type',source.source_type],
      ['政策版本 policy_version',source.policy_version],
      ['原始假設集合 ID assumption_set_id',source.assumption_set_id],
      ['建立時間 created_at',source.created_at],
      ['生效時間 effective_from',source.effective_from],
      ['本次觀察時間 observed_at',source.observed_at],
      ['發布時間 published_at',absentTimestamp(source.published_at,'不主張公開發布')],
      ['歷史可用時間 historical_available_at',absentTimestamp(source.historical_available_at,'不主張歷史可用')],
      ['原始假設內容雜湊 assumption_content_hash',source.assumption_content_hash],
      ['緊湊標準化內容雜湊 content_sha256',source.content_sha256],
      ['來源參照 source_reference',source.source_reference],
    ])}</dl><p class="source-note">兩個 SHA-256 分別保留原始假設 JSON 與緊湊標準化 JSON 的內容身分；重算吻合不代表已驗證匯出者或來源資料庫。</p><div class="table-wrap" tabindex="0" role="region" aria-label="內部政策參數紀錄"><table><caption>參數紀錄：紀錄建立時間與原件建立、本次觀察時間分開列示。</caption><thead><tr><th scope="col">紀錄 ID</th><th scope="col">參數</th><th scope="col">數值</th><th scope="col">紀錄建立 created_at</th></tr></thead><tbody>${(source.parameter_records||[]).map(record=>`<tr><th scope="row">${esc(record.record_id)}</th><td>${esc(record.parameter)}</td><td>${esc(record.value)}</td><td>${esc(record.created_at)}</td></tr>`).join('')}</tbody></table></div><details class="policy-content"><summary>完整政策內容 content（匯入者聲明）</summary><pre>${esc(JSON.stringify(source.content,null,2))}</pre></details></article>`;
  }
  if(kind==='external_document') {
    return `<article class="research-source external-document-source"><h3>${esc(source.id)}</h3><p class="source-kind">外部文件 · external_document</p><dl class="definition">${definitionRows([
      ['URL',source.url],
      ['發布時間 published_at',source.published_at],
      ['取得時間 retrieved_at',source.retrieved_at],
      ['文件 SHA-256 sha256',source.sha256],
    ])}</dl></article>`;
  }
  // A malformed API response must never acquire an external or internal label by default.
  return `<article class="research-source"><h3>${esc(source.id)}</h3><p>未支援的來源類型：${esc(kind)}</p></article>`;
}
function provenanceMarkup(run) {
  return `<section class="panel below"><div class="panel-head"><h2>研究證據邊界</h2></div><div class="panel-body"><dl class="definition">${definitionRows([
    ['歷史樣本外 historical_oos',run.historical_oos],
    ['來源版本已驗證 source_vintages_verified',run.source_vintages_verified],
    ['模型版本已驗證 model_vintages_verified',run.model_vintages_verified],
    ['價格版本已驗證 price_vintages_verified',run.price_vintages_verified],
    ['來源驗證 source_verification',run.source_verification],
    ['正式決策 formal_decision',run.formal_decision],
  ])}</dl><p class="callout">false 表示未通過該項驗證。asserted_unverified 僅是匯入者聲明；withheld 表示正式決策暫緩。經濟檢查點不能證明當時已取得資料或已有此模型。</p><ul class="provenance-limitations">${(run.provenance_limitations||[]).map(item=>`<li>${esc(item)}</li>`).join('')}</ul></div></section>`;
}
function render(run) {
  const b=run.bundle, v=run.valuation, schema2=b.schema_version===2;
  const kind=b.data_kind==='real'?'真實資料聲明 · 尚未驗證':'合成測試資料';
  const dates=schema2?[
    ['歷史經濟檢查點 economic_as_of',b.economic_as_of],
    ['本次重建截止 as_of',b.as_of],
  ]:[['資料截止 as-of',b.as_of]];
  result.innerHTML=`<section class="panel below"><div class="panel-head"><h2>${esc(b.ticker)} · ${esc(b.name)}</h2><span class="subtle-tag">${esc(kind)}</span></div><div class="panel-body"><dl class="definition">${definitionRows([
    ...dates,
    ['實際重建時間 generated_at',run.generated_at],
    ['分類',run.classification],
    ['不可變結果 ID',run.run_id],
    ['輸入雜湊',run.input_hash],
    ['正式研究判斷','暫緩 · 未綁定核准流程'],
  ])}</dl><p class="callout">五年現金流為研究假設，非已公告的未來財報。資料單位依匯入契約；現金、負債與 FCFF 為 USD，股數為實際股數，每股估值為 USD。</p>${v.status==='available'?`<div class="metric-value">$${number(v.per_share)}<small>USD / 股</small></div><p>DCFPolicyV1 · 僅依匯入研究假設計算</p>${v.negative_equity_warning?'<p class="callout negative">負股權原值保留；不是可成交價格或賣空建議。</p>':''}`:`<h3>估值不可用</h3><p>${esc(v.reason)}</p>`}</div></section>${schema2?provenanceMarkup(run):''}<section class="panel below"><div class="panel-head"><h2>唯讀輸入與逐項可用時點</h2></div><div class="table-wrap" tabindex="0" role="region" aria-label="研究輸入與可用時點"><table><caption>利率為小數（0.10 = 10%），FCFF 為年度假設。取得時間不是歷史可用時點的證明。${schema2?'內部政策 available_at 是本次觀察後的可用聲明，不是歷史發布。':''}</caption><thead><tr><th scope="col">輸入</th><th scope="col">數值</th><th scope="col">可用時點聲明</th><th scope="col">來源 ID</th></tr></thead><tbody>${inputRows(b.inputs)}</tbody></table></div><div class="panel-body"><p>假設說明：${esc(b.assumptions?.rationale)}</p><p>WACC ±1 個百分點敏感度（非機率 / 信賴區間）：${(v.scenarios||[]).map(s=>`${esc(s.name)}: ${s.status==='available'?'$'+number(s.per_share):'不可用'}`).join('；')}</p></div></section><section class="panel below"><div class="panel-head"><h2>來源聲明與時點</h2></div><div class="panel-body">${b.sources.map(s=>sourceMarkup(s,schema2)).join('')||'<p>尚無來源。</p>'}</div></section>`;
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
    for(const row of data.runs) {
      const dates=row.schema_version===2?`經濟 ${row.economic_as_of} · 重建截止 ${row.as_of}`:row.as_of;
      select.add(new Option(`${row.ticker} · ${row.data_kind==='real'?'真實聲明':'合成'} · ${dates} · ${row.run_id.slice(0,12)}`,row.run_id));
    }
    message.textContent=data.runs.length?'請選擇結果。':(data.configured?'尚未匯入研究結果。':'未設定獨立研究儲存區。');
    select.disabled=false;
    if(data.runs.some(r=>r.run_id===previous)){select.value=previous;await loadRun();}
  }catch(error){if(error.name!=='AbortError'&&current===sequence){select.replaceChildren(new Option('無法載入',''));message.textContent='無法讀取：'+error.message;}}
  finally{if(current===sequence)select.disabled=false;}
}
select.addEventListener('change',loadRun);document.querySelector('#refresh').addEventListener('click',refresh);refresh();
