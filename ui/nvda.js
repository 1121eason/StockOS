import {escapeHTML as esc, number} from './domain.mjs';

const root=document.querySelector('#research'), message=document.querySelector('#message'), update=document.querySelector('#update');
let saved=null, selectedYear=null;
const operationsRoot=document.querySelector('#operations');
const regimes={Hypergrowth:'高速成長',Growth:'成長', 'Mature Growth':'成熟成長','Cyclical Downturn':'景氣下行','Structural Deterioration':'結構惡化'};
const money=v=>v===null||v===undefined?'資料不足':`$${number(v)}`;
const billion=v=>v===null||v===undefined?'—':`${number(Number(v)/1e9)} 十億`;
const pct=v=>v===null||v===undefined?'—':`${Number(v)>0?'+':''}${number(Number(v)*100)}%`;
const date=v=>v?new Intl.DateTimeFormat('zh-TW',{dateStyle:'medium',timeStyle:'short',timeZone:'America/New_York'}).format(new Date(v))+' ET':'未提供';
const quarter=q=>q.replace(/^FY(\d+)-Q(\d)$/,'FY$1 第 $2 季');
const safeLink=url=>{try{const u=new URL(url);return u.protocol==='https:'?esc(u.href):'#';}catch{return '#';}};
function change(current,previous){return current===null||previous===null||Number(previous)<=0?null:Number(current)/Number(previous)-1;}
function trend(value){return `<span class="${Number(value)<0?'down':'trend'}">${esc(pct(value))}</span>`;}
function sourceLinks(ids){return (ids||[]).map(id=>`<a class="source-link" href="#source-${Number(id)}">來源 ${Number(id)}</a>`).join(' · ')||'缺少來源';}
async function api(path,method='GET'){
  const response=await fetch(path,{method,cache:'no-store',headers:method==='POST'?{'Content-Type':'application/json'}:{},...(method==='POST'?{body:'{}'}:{})});
  const body=await response.json();if(!response.ok)throw new Error(body.error||'研究讀取失敗');return body;
}
function empty(text){root.innerHTML=`<section class="empty"><h2>還沒有可讀取的研究快照</h2><p>${esc(text)}</p><p>保留缺值，不以示範公司或合成數字替代。</p></section>`;}
function financialRows(d){
  const labels={revenue:'營收',operating_income:'營業利益',net_income:'稅後淨利',eps_diluted:'稀釋每股盈餘',ocf:'營業現金流',capex:'資本支出',fcf:'自由現金流'};
  return Object.entries(labels).map(([key,label])=>{const cur=d.current.metrics[key],prev=d.previous.metrics[key];const fmt=key==='eps_diluted'?money:billion;return `<tr><th scope="row">${label}</th><td>${fmt(cur.value)}</td><td>${fmt(prev.value)}</td><td>${trend(change(cur.value,prev.value))}</td><td>${sourceLinks(cur.source_ids)}</td></tr>`;}).join('');
}
function matrix(v){
  if(v.status!=='available')return `<div class="panel-body"><h3>目前無法估值</h3><p class="muted">${esc(v.reason)}</p></div>`;
  const rates=[...new Set(v.scenarios.map(s=>s.wacc))],growths=[...new Set(v.scenarios.map(s=>s.terminal_growth))];
  return `<div class="table-wrap" tabindex="0" role="region" aria-label="估值敏感度"><table class="matrix"><thead><tr><th scope="col">WACC ／終端成長</th>${growths.map(g=>`<th scope="col">${number(Number(g)*100,1)}%</th>`).join('')}</tr></thead><tbody>${rates.map(w=>`<tr><th scope="row">${number(Number(w)*100,0)}%</th>${growths.map(g=>{const s=v.scenarios.find(c=>c.wacc===w&&c.terminal_growth===g);return `<td class="${Number(w)===Number(v.wacc)&&Number(g)===Number(v.terminal_growth)?'selected':''}">${money(s?.per_share)}</td>`;}).join('')}</tr>`).join('')}</tbody></table></div><p class="caption">每股價值 · USD。陰影為基準假設。區間是不同假設的敏感度，並非信賴區間。</p>`;
}
function revisionMarkup(d){
  const row=d.revisions.find(r=>r.target===selectedYear)||d.revisions[0];
  if(!row||row.status!=='AVAILABLE')return `<div class="panel-body muted">同一財年的預測修訂資料不足：${esc(row?.reason||'未提供')}</div>`;
  return `<table><thead><tr><th>同一財年 ${esc(row.target)}</th><th>相較上一季預測</th></tr></thead><tbody>${[['revenue','營收預測'],['eps','EPS 預測'],['free_cash_flow','自由現金流預測']].map(([key,label])=>`<tr><th scope="row">${label}</th><td>${trend(row.metrics[key])}</td></tr>`).join('')}</tbody></table><p class="caption">${esc(d.previous.quarter)} → ${esc(d.current.quarter)} · 嚴格比較同一財年，非 FY1／FY2 標籤直接互比。預測來源與版本見下方「來源與限制」。</p>`;
}
function render(payload){
  saved=payload;renderOperations(payload);
  const d=payload.research;if(!d){empty(payload.message||'請按上方按鈕，完成資料核對、計算與保存。');root.before(operationsRoot);return;}
  const evidenceOpen=Boolean(document.querySelector('.evidence-details')?.open);
  saved=payload;selectedYear=selectedYear||d.revisions[0]?.target;
  const c=d.current,p=d.previous,v=c.valuation,q=d.quote,comparison=d.price_comparison;
  const recent=q.status==='available'&&(Date.now()-new Date(q.quoted_at).getTime())<=5*86400000;
  const stage=regimes[c.regime.confirmed_regime]||c.regime.confirmed_regime;
  document.querySelector('#period').textContent=`${quarter(c.quarter)} · 截至 ${c.period_end} ｜與 ${quarter(p.quarter)} 比較`;
  document.querySelector('#saved-at').textContent=`最近核對 ${date(payload.operations?.research_verified_at||d.verified_at)}`;
  root.innerHTML=`
  <section id="overview" class="overview-grid" aria-label="研究概覽">
    <article class="card"><p class="card-label">目前股價 <span class="badge ${recent?'':'amber'}">${recent?'最近常規交易':q.price?'報價已過期':'無法取得'}</span></p><p class="big-number" id="market-price">${money(q.price)}<small>USD</small></p><p class="small muted">${q.quoted_at?esc(date(q.quoted_at)):'報價服務暫時無法核對'}</p><p class="card-sub"><a href="${safeLink(q.source_url)}" target="_blank" rel="noopener noreferrer">Yahoo Finance ↗</a> · 延遲時間未確認 · 常規交易報價</p></article>
    <article class="card model-card"><p class="card-label">研究日合理價值 <span class="badge">基準假設</span></p><p class="big-number" id="model-price">${money(v.base)}<small>USD</small></p><p class="small muted">${v.status==='available'?`敏感度 ${money(v.low)} – ${money(v.high)}`:esc(v.reason)}</p><p class="card-sub">研究日期 ${esc(c.checkpoint.slice(0,10))} · ${esc(c.valuation_model)}</p></article>
    ${payload.target_valuation?`<article class="card target-card"><p class="card-label">未來 12 個月目標價 <span class="badge amber">待完成</span></p><p class="big-number">尚未發布</p><p class="small muted">${esc(payload.target_valuation.reason)}</p><p class="card-sub">目標日期：尚未建立</p></article>`:''}
    <article class="card regime-card"><p class="card-label">目前營運階段</p><p class="regime-title">${esc(stage)} <span class="badge">Regime</span></p><p class="small">已確認：${esc(c.regime.confirmed_regime)}<br>候選：${esc(c.regime.candidate_regime)}</p><p class="card-sub">${esc(c.regime.transition_status)} · ${esc(c.regime.policy_version)}</p></article>
  </section>
  <p class="comparison-note">${recent&&comparison.status==='available'?`模型值相對報價差距 <strong>${esc(pct(comparison.gap))}</strong>（模型值 ÷ 報價 − 1）。${Number(comparison.split_factor)!==1?`已依供應商拆股紀錄換算至報價股數基準，模型換算值 ${money(comparison.model_on_quote_basis)}。`:''}`:'估值或新近報價不足，目前不計算價格差距。'} 模型使用 ${esc(c.checkpoint.slice(0,10))} 的季度研究假設，未因今天股價重估；差距不代表預期報酬或買賣建議。</p>
  <section id="financials"><div class="section-heading"><h2>公司現在好不好？</h2><span class="muted">GAAP · 除每股盈餘外，單位為十億美元</span></div><div class="panel table-wrap" tabindex="0" role="region" aria-label="季度財務比較"><table><thead><tr><th>財務指標</th><th>${esc(c.quarter)}</th><th>${esc(p.quarter)}</th><th>季變化</th><th>查核依據</th></tr></thead><tbody>${financialRows(d)}</tbody></table></div><p class="comparison-note">自由現金流沿用既有財務定義；估值使用 NOPAT 現金轉換 FCFF proxy，兩者並非同一個輸入。缺值與非正分母不補零。</p></section>
  <section id="valuation"><div class="section-heading"><h2>依模型假設，大約值多少？</h2><span class="muted">沿用已驗收財務公式</span></div><div class="two-column"><div class="panel">${matrix(v)}</div><div class="panel panel-body"><p class="eyebrow">MODEL ASSUMPTIONS</p><h3>價值來自哪些假設</h3><dl class="metric-list"><dt>基準折現率 WACC</dt><dd>${v.wacc?number(Number(v.wacc)*100)+'%':'—'}</dd><dt>終端成長率</dt><dd>${v.terminal_growth?number(Number(v.terminal_growth)*100)+'%':'—'}</dd><dt>現金／負債</dt><dd>${billion(v.cash)} ／ ${billion(v.debt)}</dd><dt>估值股數</dt><dd>${v.shares?number(Number(v.shares.share_count)/1e9)+' 十億股':'—'}</dd><dt>估值股數基準日</dt><dd>${esc(v.basis_date||'未提供')}</dd><dt>上一季模型價值</dt><dd>${money(p.valuation.base)}</dd></dl><p class="small muted">五年顯式現金流、固定政策假設。重算結果須逐格吻合已保存值，才可更新研究。</p></div></div></section>
  <section id="changes"><div class="section-heading"><h2>跟上一季相比，改變了什麼？</h2><label class="small muted">預測目標 <select id="fiscal-year" class="year-select">${d.revisions.map(r=>`<option value="${esc(r.target)}" ${r.target===selectedYear?'selected':''}>${esc(r.target)}</option>`).join('')}</select></label></div><div class="two-column"><div class="panel" id="revision-result">${revisionMarkup(d)}</div><div class="panel panel-body"><p class="eyebrow">OPERATING REGIME</p><h3>${esc(regimes[p.regime.confirmed_regime]||p.regime.confirmed_regime)} → ${esc(stage)}</h3><dl class="metric-list"><dt>上一季狀態</dt><dd>${esc(p.regime.transition_status)}</dd><dt>這一季狀態</dt><dd>${esc(c.regime.transition_status)}</dd><dt>本季綜合信心</dt><dd>${number(Number(c.regime.composite_confidence)*100,1)}%</dd></dl><p class="small muted">營運階段由既有量化模型辨識，並非投資評級；候選狀態不等於已確認轉換。</p></div></div></section>
  <section class="panel ai-panel" aria-label="AI 研究補充"><span class="ai-icon" aria-hidden="true">✧</span><div><h3>AI 研究補充 <span class="badge amber">待正式驗收</span></h3><p>需求、競爭與風險的分析將連同逐項證據列於此處。目前沒有適用本研究版本的核准結果。AI 不修改估值、不產生買賣建議；未核准候選保持隔離。</p><p>歷史 FY2023-Q2 已完成單季真實分析，兩份評閱意見已獲採用，修訂候選正在複核。第二份已填原件仍待核對；修訂與意見採用不代表品質通過。本頁 ${esc(c.quarter)} 的 AI 分析須按其季度另行驗收。</p></div></section>
  <section id="evidence"><div class="section-heading"><h2>這些結論，有什麼依據？</h2><span class="muted">${d.sources.length} 份文件通過本機內容雜湊核對</span></div><div class="panel"><div class="sources">${d.sources.filter(s=>s.official_disclosure&&[...c.metrics.revenue.source_ids,...p.metrics.revenue.source_ids,v.shares?.source_document_id].includes(s.id)).map(sourceMarkup).join('')}</div><details class="evidence-details"><summary>展開全部來源、數字出處與模型紀錄</summary><div class="sources">${d.sources.filter(s=>!(s.official_disclosure&&[...c.metrics.revenue.source_ids,...p.metrics.revenue.source_ids,v.shares?.source_document_id].includes(s.id))).map(sourceMarkup).join('')}</div><div class="provenance"><div><h3>每個數字的資料紀錄</h3><pre>${esc(JSON.stringify({current:c.metrics,previous:p.metrics},null,2))}</pre></div><div><h3>模型與快照身分</h3><pre>${esc(JSON.stringify({snapshot_id:payload.snapshot_id,source_database_sha256:d.source_database_sha256,forecast_run_id:c.forecast_run_id,previous_run_id:p.forecast_run_id,valuation_id:c.valuation_id,valuation:c.valuation,assumption_set_id:c.assumption_set_id,forecast_model:c.forecast_model,valuation_model:c.valuation_model,regime_model:c.regime.policy_version,information_cutoff:c.information_cutoff,classification:c.classification,quote:q},null,2))}</pre></div></div></details></div><ul class="notes"><li>財務與預測為既有研究重建；沒有證明模型在歷史當時已存在，也未完成歷史樣本外驗證。</li><li>本機原始文件雜湊吻合，不等於獨立證明所有歷史發布時間。供應商報價與拆股資料未獨立核證。</li><li>${payload.operations?.mode==='financial_refresh'?'新財報會先與 SEC 核對，再以既有財務模型重建預測、營運階段與研究日合理價值。失敗時保留上一版；12 個月目標價仍待方法驗收。':payload.operations?'背景已啟用行情、官方公告收集與既有研究核對。新財報的解析結果保留在待對帳區，尚未自動產生新的正式預測與目標價。':'更新只核對既有財務來源、重算既有估值、保存獨立工作台快照並取得報價；尚未自動下載新財報、重建正式預測或啟動排程。'}</li><li>AI、正式投資決策與長期自動運作仍待驗收。缺少資料或更新失敗時，保留上一份正常研究。</li></ul></section>`;
  if(payload.operations)document.querySelector('.comparison-note').after(operationsRoot);
  document.querySelector('.evidence-details').open=evidenceOpen;
  document.querySelector('#fiscal-year').addEventListener('change',event=>{selectedYear=event.target.value;document.querySelector('#revision-result').innerHTML=revisionMarkup(d);});
}
function sourceMarkup(s){return `<article class="source-item" id="source-${Number(s.id)}"><div><a href="${safeLink(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.official_disclosure?s.provider:'補充來源：'+s.provider)} · 文件 ${Number(s.id)} ↗</a><p>發布 ${esc(s.published_at?date(s.published_at):s.availability_records?.find(r=>r.published_at)?date(s.availability_records.find(r=>r.published_at).published_at):'原始紀錄未提供')} · 取得 ${esc(date(s.retrieved_at))}</p><code>SHA-256 ${esc(s.sha256)}</code>${(s.availability_records||[]).filter((r,i,a)=>a.findIndex(v=>v.source_url===r.source_url)===i).map(r=>`<p>歷史可用時間 ${esc(date(r.available_at))} · <a href="${safeLink(r.source_url)}" target="_blank" rel="noopener noreferrer">時間憑證 ↗</a>（${esc(r.precision)}）</p>`).join('')}</div><span class="badge">內容已核對</span></article>`;}
async function refresh(){update.disabled=true;root.setAttribute('aria-busy','true');message.className='';message.textContent='正在核對來源、重算估值、取得報價並保存研究…';try{const result=await api('/api/nvda/update','POST');render(result);message.textContent=result.refresh_queued?'已排入股價、官方財報檢查與研究更新，完成後畫面會自動更新。':'研究已更新並保存。估值與既有後端結果一致；AI 維持待驗收。';}catch(error){message.className='error';message.textContent=`更新未完成：${error.message}${saved?' 上一份正常研究仍保留在畫面。':''}`;}finally{update.disabled=false;root.setAttribute('aria-busy','false');}}
update.addEventListener('click',refresh);
try{const data=await api('/api/nvda');render(data);update.disabled=!data.configured;if(data.last_attempt?.status==='failed'){message.className='error';message.textContent=`上次更新未完成：${data.last_attempt.reason}`;}}catch(error){empty(error.message);}finally{root.setAttribute('aria-busy','false');}

function renderOperations(payload){
  const el=operationsRoot,o=payload.operations;
  const expanded=Array.from(el.querySelectorAll('details'),d=>d.open);
  if(!o){el.hidden=true;return;}el.hidden=false;
  const states={Queued:'排隊中',Running:'更新中',Succeeded:'已完成',RetryableFailed:'等待重試',Failed:'失敗'};
  const publication={Updating:'更新中',Partial:'部分完成',Stale:'需要更新',Blocked:'受阻',Current:'已更新'};
  update.textContent='立即檢查更新';
  const cloud=o.deployment==='cloud';
  document.querySelector('#environment-label').textContent=cloud?'雲端研究 · NVDA':'本機研究 · NVDA';
  el.innerHTML=`<div class="panel panel-body operation-summary"><div><p class="eyebrow">持續研究 · ${cloud?'雲端運行':'本機試運轉'}</p><h2>${o.worker_running?'背景更新運作中':'背景更新已停止'} <span class="badge amber">${esc(publication[payload.publication_status]||payload.publication_status)}</span></h2><p>股價每 5 分鐘、官方公告與財報更新每小時、已保存研究每 6 小時檢查。${cloud?'雲端服務持續執行，不受個人電腦關機影響；服務重新啟動後續接。':'關閉服務或電腦休眠會暫停，重新啟動後續接。'}</p><p class="small muted">${esc(o.coverage)}。AI 尚待驗收；通知保存於此頁。</p>${o.financial_refresh?`<p class="${o.financial_refresh.value.status==='blocked'?'error':''}">${esc(o.financial_refresh.value.quarter||'本次更新')}：${esc(o.financial_refresh.value.reason||'財務已核對，預測與估值已重建保存。')}</p>`:''}</div><details><summary>查看更新工作與失敗原因</summary><ul class="job-list">${o.jobs.slice(0,12).map(j=>`<li>${esc(j.label)} · ${esc(states[j.status]||j.status)} · 第 ${Number(j.attempts)} 次${j.error?' · '+esc(j.reason||j.error):''}</li>`).join('')}</ul><p class="small muted">最後活動 ${esc(date(o.heartbeat_at))}</p></details></div>
  <details class="panel operation-events"><summary>官方公告與待處理資料 <span class="badge">${payload.events.length}</span></summary><div class="sources">${[...payload.events].sort((a,b)=>(b.publication_date||'').localeCompare(a.publication_date||'')).map(e=>`<article class="source-item"><div><a href="${safeLink(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.title)} ↗</a><p>發布日 ${esc(e.publication_date||'未確認')} · 首次取得 ${esc(date(e.received_at))}</p><p>${esc(e.model_impact)}</p><p class="small muted">${e.status==='research_rebuilt'?'已完成研究更新':e.status==='research_unchanged_verified'?'已核對，財務未改變':e.status==='parse_blocked'?'解析受阻，需要檢查來源格式':e.status==='parsed_pending_reconciliation'?'財務與指引已解析，待對帳':'待研究其重要性與影響'}</p></div></article>`).join('')||'<p>正在檢查官方來源，尚無已保存公告。</p>'}</div></details>
  <details class="panel operation-events"><summary>更新紀錄與提醒 <span class="badge">${payload.alerts.length}</span></summary><ul class="job-list">${payload.alerts.slice(0,12).map(a=>`<li>${esc(a.message)}<br><span class="small muted">${esc(date(a.created*1000))}</span></li>`).join('')||'<li>尚無提醒。</li>'}</ul></details>`;
  el.querySelectorAll('details').forEach((d,i)=>{d.open=Boolean(expanded[i]);});
}
setInterval(async()=>{
  if(!saved?.operations||document.hidden||update.disabled||document.activeElement?.id==='fiscal-year')return;
  try{const payload=await api('/api/nvda');render(payload);}
  catch{message.className='error';message.textContent='目前無法連線到背景服務，畫面保留上次資料。';}
},15000);
