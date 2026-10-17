import {labels, number, validate, escapeHTML as esc, routeFrom} from './domain.mjs';

const $ = (selector, root=document) => root.querySelector(selector);
const main=$('#main');
const titles={overview:'估值總覽',assumptions:'假設沙盒',evidence:'模型與證據',status:'資料與驗證'};
const subtitles={overview:'看見價值的範圍，也看見假設的邊界。',assumptions:'調整關鍵假設，理解每一個變動的影響。',evidence:'沿著資料與模型，追溯每一項研究依據。',status:'知道哪些可用，哪些仍需查證。'};
const state={route:'',company:'aurora',data:null,results:new Map(),fiscalTargets:new Map(),dirty:false,pending:null,controller:null,sequence:0,busy:false};
let health=null;
const badge=status=>`<span class="badge ${esc(status)}">${esc(labels[status]||status)}</span>`;
const date=value=>value?new Date(value).toLocaleString('zh-TW',{timeZone:'UTC',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})+' UTC':'未提供';
const hashFor=(route,company=state.company)=>`#${route}?company=${encodeURIComponent(company)}`;
const announce=message=>{$('#announcement').textContent=message;};
const result=()=>state.results.get(state.company)||state.data.valuation;
const params=()=>result().parameters||state.data.company;
const targetMessage=()=>state.fiscalTargets.get(state.company)?`已指定 ${state.fiscalTargets.get(state.company)}；缺少該財年同目標比較資料，修訂判斷仍暫緩。`:'尚未指定財年目標，修訂判斷暫緩。';

async function api(path,options={}) {
  const response=await fetch(path,{...options,cache:'no-store'});
  let data;
  try {data=await response.json();} catch {throw new Error('服務回應格式不正確，請確認伺服器版本後重試。');}
  if(!response.ok) throw new Error(data.error||'無法取得資料');
  return data;
}
function navigate(route,company=state.company) {
  const next=hashFor(route,company);
  if(state.route===route && state.company===company) return;
  const action=()=>{state.dirty=false;location.hash=next;};
  if(state.dirty) {state.pending=action;$('#leave-dialog').showModal();} else action();
}
function companyButton() {
  const c=state.data.company;
  return `<button class="company-button" id="company-button" aria-haspopup="dialog" aria-label="選擇研究公司，目前為${esc(c.name)}"><span class="company-symbol">${esc(c.symbol)}</span><span class="company-name">${esc(c.name)}<small>${esc(c.english_name)}</small></span><span class="chevron" aria-hidden="true">⌄</span></button>`;
}
function heading() {
  return `<div class="page-heading"><div><p class="eyebrow">${{overview:'VALUATION OVERVIEW',assumptions:'ASSUMPTION SANDBOX',evidence:'MODEL & EVIDENCE',status:'DATA & VALIDATION'}[state.route]}</p><h1 tabindex="-1">${titles[state.route]}</h1><p class="muted">${subtitles[state.route]}</p></div><div class="heading-actions">${companyButton()}${state.route==='overview'?'<a class="button" href="#assumptions">調整假設 <span aria-hidden="true">↗</span></a>':''}</div></div>`;
}
function context() {
  return `<div class="context-line"><span>研究對象 <b>${esc(state.data.company.symbol)} · 虛構公司</b></span><span>資料截止 <b>${date(state.data.snapshot.as_of)}</b></span><span>幣別 <b>USD</b> · 每股估值</span><span>來源 <b>合成 fixture v${esc(state.data.fixture_version)}</b></span></div>`;
}
function noData() {
  return `<section class="panel empty"><span class="empty-icon" aria-hidden="true">◇</span><h2>還沒有可用的研究資料</h2><p>現金流、現金、負債與股數尚未提供。缺值不會自動補成 0，也不會產生估值或研究判斷。</p><button class="button" id="empty-company">選擇示範公司</button><a class="button secondary" href="#status">檢查資料狀態</a></section>`;
}
function negativeWarning(r) {
  return r.negative_equity_warning?'<p class="callout negative">負股權提醒：模型輸出低於 0，已依原值保留。此結果不能解讀為可成交股價、賣空建議或下限保證。</p>':'';
}
function chart(r) {
  const valid=r.scenarios.filter(s=>s.status==='available');
  const values=valid.map(s=>Number(s.per_share));
  const lo=Math.min(0,...values),hi=Math.max(0,...values),pad=Math.max((hi-lo)*0.12,1);
  const min=lo-pad,max=hi+pad,x=v=>55+(v-min)/(max-min)*490;
  const zero=x(0);
  const positions=valid.map(s=>x(Number(s.per_share)));
  return `<svg class="chart" viewBox="0 0 600 200" role="img" aria-labelledby="range-title range-desc"><title id="range-title">WACC 敏感度估值範圍</title><desc id="range-desc">${valid.map(s=>`${s.label}，WACC ${number(s.wacc_pct,1)}%，每股 ${number(s.per_share)} USD`).join('；')}。非信賴區間；零與負值保留。</desc><line class="axis" x1="35" y1="135" x2="570" y2="135"/><line class="zero" x1="${zero}" y1="57" x2="${zero}" y2="142"/><text x="${zero}" y="161" text-anchor="middle">0</text>${positions.length>1?`<line class="range-line" x1="${Math.min(...positions)}" y1="98" x2="${Math.max(...positions)}" y2="98"/>`:''}${valid.map(s=>{const base=s.label==='基準';return `<circle class="${base?'base-point':'point'}" cx="${x(Number(s.per_share))}" cy="98" r="${base?8:5}"/>${base?`<text class="chart-value" x="${x(Number(s.per_share))}" y="67" text-anchor="middle">$${number(s.per_share)}</text>`:''}`;}).join('')}<text x="35" y="186">${number(min,1)}</text><text x="570" y="186" text-anchor="end">${number(max,1)} USD / 股</text></svg>`;
}
function forecastTable(r,compact=false) {
  const flows=r.cashflows||[];
  return `<section class="panel below"><div class="panel-head"><div><h2>現金流路徑</h2><p>合成 FCFF 輸入 · 不是正式財務預測</p></div><span class="subtle-tag">${compact?'5 YEAR':'SYNTHETIC'}</span></div><div class="table-wrap" tabindex="0" role="region" aria-label="研究資料表"><table><caption>單位：百萬 USD。Y1–Y5 為相對年度，未對應正式財年。</caption><thead><tr><th scope="col">假設項目</th>${flows.map((_,i)=>`<th scope="col">Y${i+1}</th>`).join('')}</tr></thead><tbody><tr><th scope="row">FCFF（合成）</th>${flows.map(v=>`<td>${number(v,1)}</td>`).join('')}</tr><tr><th scope="row">資料狀態</th>${flows.map(()=>`<td>${badge('unverified')}</td>`).join('')}</tr></tbody></table></div><p class="table-note">直接提供合成 FCFF；未將未調整 CFO − capex 標示為 FCFF。正式研究仍需可追溯的財報調節。</p></section>`;
}
function overview() {
  const r=result();
  if(r.status!=='available') return noData();
  const values=r.scenarios.filter(s=>s.status==='available').map(s=>Number(s.per_share));
  return `${negativeWarning(r)}<div class="metrics"><section class="metric primary"><div class="metric-label">DCF 基準估值 <span class="mini-tag">SYNTHETIC</span></div><div class="metric-value">$${number(r.per_share)}<small>USD / 股</small></div><p class="metric-foot">敏感度範圍 $${number(Math.min(...values))} – $${number(Math.max(...values))}</p></section><section class="metric"><div class="metric-label">市場價格 ${badge('unavailable')}</div><div class="metric-value unavailable">— <small>USD / 股</small></div><p class="metric-foot">未連接報價；價格差距不計算</p></section><section class="metric"><div class="metric-label">研究判斷 <span class="subtle-tag">WITHHELD</span></div><div class="metric-value unavailable">暫緩</div><p class="metric-foot"><span class="warn">缺少正式資料綁定與驗證</span></p></section></div><div class="content-grid"><section class="panel"><div class="panel-head"><div><h2>價值是一個範圍</h2><p>WACC ±1 個百分點 · 其他參數固定</p></div><span class="subtle-tag">DCF SENSITIVITY</span></div><div class="panel-body">${chart(r)}<div class="chart-caption"><span><i class="dot"></i>基準估值</span><span>端點：折現率變動情境 · 非機率 / 非信賴區間</span></div><dl class="scenario-grid">${r.scenarios.map(s=>`<div class="scenario"><dt>${esc(s.label)}</dt><dd>${s.status==='available'?'$'+number(s.per_share):'—'}</dd><small>WACC ${number(s.wacc_pct,1)}%${s.status!=='available'?' · 不可用':''}</small></div>`).join('')}</dl></div></section><section class="panel"><div class="panel-head"><div><h2>研究備忘</h2><p>在形成判斷之前，先看這些限制。</p></div><span class="subtle-tag">3 項待確認</span></div><div class="panel-body"><ul class="research-list"><li><span class="research-icon" aria-hidden="true">◇</span><div><strong>正式 Regime 尚未綁定</strong><p>company、run 與 checkpoint 缺一不可。</p></div></li><li><span class="research-icon" aria-hidden="true">⌁</span><div><strong>AI 內容維持隔離</strong><p>未綁定證據不調整量化估值。</p></div></li><li><span class="research-icon" aria-hidden="true">◷</span><div><strong>${state.fiscalTargets.get(state.company)?'修訂比較資料缺少':'修訂目標尚未選擇'}</strong><p>${state.fiscalTargets.get(state.company)?'已選擇 '+esc(state.fiscalTargets.get(state.company))+'；尚無同目標比較資料。':'先指定明確財年，才可比較同一目標。'}</p></div></li></ul></div><div class="research-footer"><span>沒有模型核准或完成度評分</span><a href="#evidence">追溯證據 ↗</a></div></section></div>${forecastTable(r,true)}`;
}
const fieldInfo={wacc:['折現率 WACC','%','0.1–50%；須高於終端成長率'],terminal_growth:['終端成長率 g','%','−20–20%；須低於 WACC'],growth:['額外年成長率','%','−50–100%；第 n 年現金流 × (1 + r)ⁿ'],cash:['現金','百萬 USD','現金與負債均須明確填寫，可為 0'],debt:['負債','百萬 USD','允許負股權估值；不將輸出截斷為 0'],shares:['流通股數','百萬股','必須大於 0；不是 EPS 加權平均股數']};
function sandboxResult(r) {
  if(r.status!=='available') return `<p class="callout">${esc(r.reason||'結果尚不可用')}</p>`;
  return `<p class="result-label">${state.results.has(state.company)?'已套用的沙盒結果':'合成基準結果'}</p><div class="result-value">$${number(r.per_share)} <small>USD / 股</small></div>${negativeWarning(r)}<hr class="result-separator"><dl class="definition"><dt>企業價值 EV</dt><dd>${number(r.enterprise_value)} 百萬 USD</dd><dt>股權價值</dt><dd>${number(r.equity_value)} 百萬 USD</dd><dt>模型版本</dt><dd>DCFPolicyV1</dd><dt>報價 / 預期報酬</dt><dd>無法取得 / 不計算</dd></dl><p class="sandbox-note">只計算合成情境。未執行正式預測、Regime、AI 或投資決策流程。</p>`;
}
function assumptions() {
  if(!state.data.company.cashflows) return noData();
  const values=params();
  return `<div class="form-layout"><form class="panel" id="assumption-form" novalidate><div class="panel-head"><div><h2>你的假設，清楚展開</h2><p>全部欄位必填；不會寫入研究資料庫。</p></div><span class="subtle-tag">SANDBOX</span></div><div class="form-section"><h3>估值參數</h3><div class="form-grid">${['wacc','terminal_growth','growth'].map(key=>field(key,values)).join('')}</div></div><div class="form-section"><h3>股權價值調整</h3><div class="form-grid">${['cash','debt','shares'].map(key=>field(key,values)).join('')}</div></div><p id="form-status" class="inline-status" role="status">輸入變更後，按「計算情境」套用。</p><div class="form-actions"><p>僅保留於本次瀏覽；重新整理會重設。</p><div class="form-buttons"><button type="button" class="button secondary" id="reset-assumptions">還原示範值</button><button type="submit" class="button" id="calculate">計算情境 <span aria-hidden="true">↗</span></button></div></div></form><section class="panel" aria-labelledby="sandbox-result-title"><div class="panel-head"><h2 id="sandbox-result-title">情境計算</h2><span class="subtle-tag">合成資料</span></div><div class="panel-body" id="sandbox-result" aria-live="polite">${sandboxResult(result())}</div></section></div><div id="sandbox-forecast">${forecastTable(result())}</div>`;
}
function field(key,values) {
  const [label,unit,hint]=fieldInfo[key];
  return `<div class="field"><label for="${key}">${label} <span>${unit}</span></label><input id="${key}" name="${key}" type="number" step="any" inputmode="decimal" required value="${esc(values[key])}" aria-describedby="${key}-hint ${key}-error"><small id="${key}-hint">${hint}</small><p id="${key}-error" class="field-error"></p></div>`;
}
function evidence() {
  return `<div class="two-cols"><div class="evidence-list">${state.data.evidence.map(e=>`<article class="evidence-card"><div class="evidence-title"><h3>${esc(e.title)}</h3>${badge(e.status)}</div><p>${esc(e.detail)}</p><div class="evidence-meta"><span>來源：${esc(e.source)}</span><span>時點：${date(e.timestamp)}</span></div></article>`).join('')}</div><div class="panel"><div class="panel-head"><div><h2>同一財年，才有可比性</h2><p>Forecast Revision · 明確財務目標</p></div></div><div class="panel-body"><div class="select-group"><label for="fiscal-target">修訂比較目標</label><select id="fiscal-target"><option value="">請選擇財年或季度</option><option>FY2027</option><option>FY2027-Q3</option></select><small>選項只用於展示明確目標格式，不代表有該期研究。</small></div><p id="revision-status" class="callout below" role="status">尚未指定財年目標，修訂判斷暫緩。</p><hr class="result-separator"><dl class="definition"><dt>正式 company ID</dt><dd>未綁定</dd><dt>forecast run ID</dt><dd>未綁定</dd><dt>checkpoint</dt><dd>未綁定</dd><dt>AI 納入估值</dt><dd>否 · 已隔離</dd></dl></div><details class="details"><summary>為什麼不顯示研究訊號？</summary><p>示範資料無法證明正式來源、批次或資訊截止時間。系統維持暫緩狀態；暫緩不是持有、買進或賣出建議。選擇財年不會建立比較資料或解鎖決策。</p></details></div></div>`;
}
function statusPage() {
  return `<div class="two-cols"><div><section class="panel"><div class="panel-head"><div><h2>資料邊界與時點</h2><p>明確呈現缺口，不將缺值視為零。</p></div><span class="subtle-tag">DEMO ONLY</span></div><div class="panel-body"><dl class="definition"><dt>資料模式</dt><dd>內建合成示範資料</dd><dt>資料截止（合成）</dt><dd>${date(state.data.snapshot.as_of)}</dd><dt>快照時間（合成）</dt><dd>${date(state.data.snapshot.checkpoint)}</dd><dt>本次 API 回應時間</dt><dd>${date(state.data.served_at)}</dd><dt>正式研究 run / company</dt><dd>未綁定 / 未綁定</dd><dt>後端來源基線（整合前）</dt><dd class="code">${esc(state.data.backend_baseline)}</dd></dl><div class="legend">${Object.keys(labels).map(badge).join('')}</div><p class="callout">所有公司與財務數值都是合成資料。API 回應時間僅表示本機服務讀取時間，不能當作資料更新時間。未讀取原始資料庫或 .env。</p></div></section><section class="panel below"><div class="panel-head"><div><h2>輸出限制</h2><p>保留原後端的計算與治理語意。</p></div></div><div class="table-wrap" tabindex="0" role="region" aria-label="研究資料表"><table><caption>這是契約說明，並非模型核准或測試完成度評分。</caption><thead><tr><th scope="col">檢查項目</th><th scope="col">本版行為</th></tr></thead><tbody><tr><th scope="row">零 / 負 DCF</th><td>原值保留</td></tr><tr><th scope="row">缺少 / 非有限數值</th><td>拒絕計算，不補 0</td></tr><tr><th scope="row">WACC ≤ g</th><td>拒絕計算</td></tr><tr><th scope="row">正式 Regime 綁定</th><td>缺少，維持暫緩</td></tr><tr><th scope="row">未綁定 AI</th><td>隔離，不納入</td></tr><tr><th scope="row">明確財年目標</th><td>必須指定；仍需正式比較資料</td></tr></tbody></table></div></section></div><section class="panel"><div class="panel-head"><h2>本機服務</h2><button class="button secondary" id="refresh-health">重新檢查</button></div><div class="panel-body"><div id="health-status" aria-live="polite">${healthMarkup()}</div><hr class="result-separator"><h3>真實研究資料</h3><p class="sandbox-note">本示範頁不讀取研究資料庫。離線匯入結果可在獨立的<a href="/research">匯入研究結果</a>頁唯讀檢視；正式核准仍未綁定。</p><p class="sandbox-note">不執行資料同步、遷移或付費模型 API。此處沒有交易功能。</p><button class="button secondary below" id="status-help">開啟使用指南 ↗</button></div></section></div>`;
}
function healthMarkup() {
  if(!health) return '<p class="muted">尚未檢查服務</p>';
  if(health.error) return `<p class="callout negative">${esc(health.error)}。請確認終端機服務是否仍在執行，再重新檢查。</p>`;
  return `<ul class="status-list"><li><div>本機 API<small>僅綁定 127.0.0.1</small></div><span class="status-value">運作中</span></li><li><div>計算引擎<small>既有 DCFPolicyV1 · 合成輸入</small></div><span class="status-value">可用</span></li><li><div>研究資料庫<small>未配置連線</small></div><span class="status-value off">未連接</span></li><li><div>報價 / 模型 API<small>未設定供應商</small></div><span class="status-value off">未啟用</span></li></ul>`;
}
async function refreshHealth() {
  const button=$('#refresh-health'); if(button) button.disabled=true;
  try {health=await api('/api/health');} catch(error) {health={error:error.message};}
  if(state.route==='status' && $('#health-status')) $('#health-status').innerHTML=healthMarkup();
  if(button) button.disabled=false;
}
function render(focus=true) {
  const views={overview,assumptions,evidence,status:statusPage};
  main.innerHTML=heading()+context()+views[state.route]();
  main.setAttribute('aria-busy','false');
  $('#breadcrumb').textContent=titles[state.route];
  document.title=`${titles[state.route]} · ${state.data.company.name} — StockOS`;
  document.querySelectorAll('[data-route]').forEach(a=>{a.href=hashFor(a.dataset.route);if(a.dataset.route===state.route)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  ['#company-button','#empty-company'].forEach(s=>$(s)?.addEventListener('click',openCompanies));
  $('#assumption-form')?.addEventListener('input',()=>{state.dirty=true;$('#form-status').textContent='有未套用的變更；右側仍顯示上一次計算。';});
  $('#assumption-form')?.addEventListener('submit',calculate);
  $('#reset-assumptions')?.addEventListener('click',()=>{state.controller?.abort();state.sequence++;state.results.delete(state.company);state.dirty=false;state.busy=false;render(false);announce('已還原示範值');});
  if($('#fiscal-target')) {$('#fiscal-target').value=state.fiscalTargets.get(state.company)||'';$('#revision-status').textContent=targetMessage();}
  $('#fiscal-target')?.addEventListener('change',event=>{state.fiscalTargets.set(state.company,event.target.value);$('#revision-status').textContent=targetMessage();});
  $('#refresh-health')?.addEventListener('click',refreshHealth);
  $('#status-help')?.addEventListener('click',()=>$('#help-dialog').showModal());
  if(state.route==='status') refreshHealth();
  if(focus) {$('h1',main)?.focus({preventScroll:true});window.scrollTo(0,0);}
}
async function load(route,company,focus=true) {
  state.controller?.abort(); const sequence=++state.sequence;
  state.controller=new AbortController(); state.busy=false;
  const same=state.data && state.company===company;
  state.route=route;state.company=company;state.dirty=false;
  if(same) {render(focus);return;}
  main.setAttribute('aria-busy','true');
  main.innerHTML='<div class="loading" role="status"><span class="busy-mark" aria-hidden="true"></span>正在載入研究工作區…</div>';
  try {
    const data=await api(`/api/workspace?company=${encodeURIComponent(company)}`,{signal:state.controller.signal});
    if(sequence!==state.sequence) return;
    state.data=data;render(focus);announce(`已載入${data.company.name}，合成示範資料`);
  } catch(error) {
    if(error.name==='AbortError'||sequence!==state.sequence)return;
    state.data=null;main.setAttribute('aria-busy','false');
    main.innerHTML=`<section class="panel empty" role="alert"><span class="empty-icon" aria-hidden="true">!</span><h1>工作區暫時無法載入</h1><p>${esc(error.message)}。請確認本機伺服器是否執行中。</p><button class="button" id="retry-load">重新載入</button><button class="button secondary" id="return-demo">返回預設示範</button></section>`;
    $('#retry-load').addEventListener('click',()=>load(route,company));$('#return-demo').addEventListener('click',()=>{location.hash=hashFor('overview','aurora');});
  }
}
async function calculate(event) {
  event.preventDefault();if(state.busy)return;
  const form=event.currentTarget,values=Object.fromEntries(new FormData(form)),errors=validate(values);
  for(const key of Object.keys(fieldInfo)) {$('#'+key+'-error').textContent=errors[key]||'';$('#'+key).setAttribute('aria-invalid',errors[key]?'true':'false');}
  if(Object.keys(errors).length) {$('#form-status').classList.add('error');$('#form-status').textContent='請修正標示欄位，再重新計算。';$('#'+Object.keys(errors)[0]).focus();return;}
  const button=$('#calculate'),status=$('#form-status');state.busy=true;button.disabled=true;status.classList.remove('error');status.textContent='正在計算合成情境…';
  form.querySelectorAll('input').forEach(input=>{input.disabled=true;});
  const company=state.company,sequence=++state.sequence;state.controller?.abort();state.controller=new AbortController();
  try {
    const calculated=await api('/api/sandbox',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({company,...values}),signal:state.controller.signal});
    if(sequence!==state.sequence||company!==state.company)return;
    state.results.set(company,calculated);state.dirty=false;
    $('#sandbox-result').innerHTML=sandboxResult(calculated);$('#sandbox-forecast').innerHTML=forecastTable(calculated);
    status.textContent='情境已套用；未寫入資料庫。';announce('情境計算完成，僅為合成資料。');
  } catch(error) {if(error.name!=='AbortError'&&sequence===state.sequence){status.classList.add('error');status.textContent=`計算未完成：${error.message}。輸入已保留，可重試。`;}}
  finally {if(sequence===state.sequence){state.busy=false;button.disabled=false;form.querySelectorAll('input').forEach(input=>{input.disabled=false;});}}
}
function openCompanies() {
  if(!state.data)return;
  $('#company-search').value='';companyList('');$('#company-dialog').showModal();$('#company-search').focus();
}
function companyList(query) {
  const rows=state.data.companies.filter(c=>(c.name+c.symbol+c.english_name).toLowerCase().includes(query.toLowerCase()));
  $('#company-list').innerHTML=rows.length?rows.map(c=>`<button class="company-option" data-company="${esc(c.id)}"><span class="company-symbol">${esc(c.symbol)}</span><span class="company-name">${esc(c.name)}<small>${esc(c.description)}</small></span><span>${c.id===state.company?'目前選擇':'→'}</span></button>`).join(''):'<p class="no-results" role="status">找不到公司。試試 AUR、ATL 或 NEW。</p>';
  document.querySelectorAll('[data-company]').forEach(button=>button.addEventListener('click',()=>{$('#company-dialog').close();navigate(state.route,button.dataset.company);}));
}
document.addEventListener('click',event=>{
  const anchor=event.target.closest('a[href^="#"]');
  if(!anchor||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
  if(anchor.classList.contains('skip')) {event.preventDefault();main.focus();main.scrollIntoView({block:'start'});return;}
  const target=routeFrom(anchor.hash);event.preventDefault();
  navigate(target.route,new URLSearchParams(anchor.hash.split('?')[1]||'').get('company')||state.company);
});
document.querySelectorAll('[data-close]').forEach(b=>b.addEventListener('click',()=>$('#'+b.dataset.close).close()));
$('#help-button').addEventListener('click',()=>$('#help-dialog').showModal());
$('#company-search').addEventListener('input',event=>companyList(event.target.value));
$('#stay').addEventListener('click',()=>{$('#leave-dialog').close();state.pending=null;});
$('#leave-dialog').addEventListener('cancel',()=>{state.pending=null;});
$('#discard').addEventListener('click',()=>{const action=state.pending;state.pending=null;$('#leave-dialog').close();action?.();});
window.addEventListener('beforeunload',event=>{if(state.dirty){event.preventDefault();event.returnValue='';}});
window.addEventListener('hashchange',()=>{
  const target=routeFrom(location.hash);
  if(state.dirty) {history.replaceState(null,'',hashFor(state.route));state.pending=()=>{state.dirty=false;location.hash=hashFor(target.route,target.company);};if(!$('#leave-dialog').open)$('#leave-dialog').showModal();return;}
  load(target.route,target.company);
});
const initial=routeFrom(location.hash);history.replaceState(null,'',hashFor(initial.route,initial.company));load(initial.route,initial.company,false);
