import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {SourceTextModule} from 'node:vm';
import {JSDOM} from 'jsdom';
const root=new URL('../',import.meta.url);
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check){for(let i=0;i<150;i++){if(check())return;await wait(10);}throw new Error('Workbench UI did not settle');}
function fixture(){
 const metrics=Object.fromEntries(['revenue','operating_income','net_income','eps_diluted','ocf','capex','fcf'].map(k=>[k,{value:'100',source_ids:[1],fact_ids:[10]}]));
 const quarter={quarter:'FY2027-Q2',checkpoint:'2026-08-27T13:30:00Z',period_end:'2026-07-26',metrics,valuation:{status:'available',base:'250',low:'200',high:'300',scenarios:[{wacc:'.10',terminal_growth:'.025',per_share:'250'}],wacc:'.10',terminal_growth:'.025',basis_date:'2026-08-27',cash:'20',debt:'10',shares:{share_count:'10',source_document_id:1}},regime:{confirmed_regime:'Growth',candidate_regime:'Hypergrowth',transition_status:'PENDING_CONFIRMATION',composite_confidence:'.7',policy_version:'SyntheticRegime'},valuation_model:'SyntheticValuation'};
 return {configured:true,snapshot_id:'synthetic',research:{current:quarter,previous:{...structuredClone(quarter),quarter:'FY2027-Q1'},verified_at:new Date().toISOString(),quote:{status:'available',price:'200',quoted_at:new Date().toISOString(),source_url:'https://finance.yahoo.com/quote/NVDA/'},price_comparison:{status:'available',gap:'.25',split_factor:'1'},revisions:[{target:'FY2027',status:'AVAILABLE',metrics:{revenue:'.1',eps:'-.2',free_cash_flow:null},revision_id:1},{target:'FY2028',status:'AVAILABLE',metrics:{revenue:'.3',eps:'.4',free_cash_flow:'.5'},revision_id:2}],sources:[{id:1,url:'https://nvidianews.nvidia.com/news/synthetic',official_disclosure:true,provider:'Synthetic source',published_at:new Date().toISOString(),retrieved_at:new Date().toISOString(),sha256:'a'.repeat(64)}]}};
}
async function app(handler){
 const dom=new JSDOM(await readFile(new URL('ui/nvda.html',root),'utf8'),{url:'http://127.0.0.1:8510/nvda',runScripts:'outside-only'});
 dom.window.fetch=async(path,options)=>({ok:true,json:async()=>handler(path,options)});
 const context=dom.getInternalVMContext(),entry=new SourceTextModule(await readFile(new URL('ui/nvda.js',root),'utf8'),{context});
 await entry.link(async()=>new SourceTextModule(await readFile(new URL('ui/domain.mjs',root),'utf8'),{context}));await entry.evaluate();
 return {dom,doc:dom.window.document};
}
test('real workspace renders API values, fiscal-target revisions and quarantined AI together',async()=>{
 const a=await app(()=>fixture());try{assert.match(a.doc.querySelector('#market-price').textContent,/200.00/);assert.match(a.doc.querySelector('#model-price').textContent,/250.00/);assert.match(a.doc.querySelector('#revision-result').textContent,/\+10.00%/);assert.match(a.doc.querySelector('#revision-result').textContent,/-20.00%/);assert.match(a.doc.body.textContent,/AI 不修改估值/);assert.match(a.doc.body.textContent,/\+25.00%/);const select=a.doc.querySelector('#fiscal-year');select.value='FY2028';select.dispatchEvent(new a.dom.window.Event('change'));assert.match(a.doc.querySelector('#revision-result').textContent,/\+30.00%/);}finally{a.dom.window.close();}
});
test('missing quote and missing valuation never become zero or demo data',async()=>{
 const d=fixture();d.research.quote={status:'unavailable',price:null};d.research.current.valuation={status:'unavailable',base:null,reason:'synthetic missing shares'};d.research.price_comparison={status:'unavailable'};
 const a=await app(()=>d);try{assert.match(a.doc.querySelector('#market-price').textContent,/資料不足/);assert.match(a.doc.querySelector('#model-price').textContent,/資料不足/);assert.doesNotMatch(a.doc.body.textContent,/\$0.00|雲曜|aurora/);}finally{a.dom.window.close();}
});
test('manual update sends an empty request and failure preserves last good screen',async()=>{
 let calls=0;const a=await app((path,options)=>{if(options.method==='POST'){calls++;assert.equal(path,'/api/nvda/update');assert.equal(options.body,'{}');throw new Error('synthetic source failure');}return fixture();});
 try{a.doc.querySelector('#update').click();await until(()=>!a.doc.querySelector('#update').disabled);assert.equal(calls,1);assert.match(a.doc.querySelector('#message').textContent,/上一份正常研究仍保留/);assert.match(a.doc.querySelector('#model-price').textContent,/250.00/);}finally{a.dom.window.close();}
});
test('successful update replaces the saved snapshot and releases busy controls',async()=>{
 const next=fixture();next.research.current.valuation.base='260';const a=await app((path,options)=>options.method==='POST'?next:fixture());try{a.doc.querySelector('#update').click();await until(()=>!a.doc.querySelector('#update').disabled);assert.match(a.doc.querySelector('#model-price').textContent,/260.00/);assert.match(a.doc.querySelector('#message').textContent,/研究已更新並保存/);}finally{a.dom.window.close();}
});
test('unsafe source labels and URLs cannot create script markup or executable links',async()=>{
 const d=fixture();d.research.sources[0].provider='<img src=x onerror=alert(1)>';d.research.sources[0].url='javascript:alert(1)';const a=await app(()=>d);try{assert.equal(a.doc.querySelector('#research img'),null);assert.equal(a.doc.querySelector('#source-1 a').getAttribute('href'),'#');assert.equal(a.doc.querySelector('#research script'),null);}finally{a.dom.window.close();}
});
test('old quote is labeled stale and cannot show a current-price comparison',async()=>{
 const d=fixture();d.research.quote.quoted_at='2020-01-01T00:00:00Z';const a=await app(()=>d);try{assert.match(a.doc.body.textContent,/報價已過期/);assert.doesNotMatch(a.doc.querySelector('.comparison-note').textContent,/\+25.00%/);}finally{a.dom.window.close();}
});
test('automated product shows real quote, pending target and source queue without inventing a target',async()=>{
 const d=fixture();Object.assign(d,{operations:{worker_running:true,coverage:'synthetic official source coverage',heartbeat_at:new Date().toISOString(),jobs:[{id:1,label:'股價更新',status:'Succeeded',attempts:1}]},target_valuation:{reason:'12 個月方法待驗收'},publication_status:'Partial',events:[{title:'<img src=x onerror=alert(1)>',url:'javascript:bad()',publication_date:'2026-10-21',received_at:new Date().toISOString(),model_impact:'待對帳',status:'parsed_pending_reconciliation'}],alerts:[]});
 const a=await app(()=>d);try{assert.equal(a.doc.querySelector('#operations').hidden,false);assert.match(a.doc.querySelector('#operations').textContent,/背景更新運作中/);assert.match(a.doc.querySelector('.target-card').textContent,/尚未發布/);assert.match(a.doc.querySelector('#model-price').textContent,/250.00/);assert.equal(a.doc.querySelector('#operations img'),null);assert.equal(a.doc.querySelector('#operations a').getAttribute('href'),'#');}finally{a.dom.window.close();}
});
test('automated refresh reports queued work rather than successful publication',async()=>{
 const d=fixture();Object.assign(d,{operations:{worker_running:true,coverage:'synthetic',jobs:[]},target_valuation:{reason:'未提供'},publication_status:'Partial',events:[],alerts:[],refresh_queued:true});
 const a=await app(()=>d);try{a.doc.querySelector('#update').click();await until(()=>!a.doc.querySelector('#update').disabled);assert.match(a.doc.querySelector('#message').textContent,/已排入/);assert.doesNotMatch(a.doc.querySelector('#message').textContent,/研究已更新並保存/);}finally{a.dom.window.close();}
});
test('automated startup can show operational state before the first research publication',async()=>{
 const a=await app(()=>({configured:true,research:null,operations:{worker_running:true,coverage:'synthetic',jobs:[]},publication_status:'Updating',events:[],alerts:[]}));try{assert.equal(a.doc.querySelector('#operations').hidden,false);assert.match(a.doc.querySelector('#operations').textContent,/背景更新運作中/);assert.match(a.doc.querySelector('#research').textContent,/還沒有可讀取/);}finally{a.dom.window.close();}
});
test('cloud deployment label and newest announcement order follow the API',async()=>{
 const d=fixture();Object.assign(d,{operations:{deployment:'cloud',worker_running:true,coverage:'synthetic',jobs:[]},publication_status:'Partial',events:[{title:'Older item',url:'https://example.com/old',publication_date:'2026-01-01'},{title:'Newer item',url:'https://example.com/new',publication_date:'2026-10-21'}],alerts:[]});
 const a=await app(()=>d);try{assert.match(a.doc.querySelector('#environment-label').textContent,/雲端/);assert.match(a.doc.querySelector('#operations').textContent,/不受個人電腦關機影響/);assert.match(a.doc.querySelector('#operations a').textContent,/Newer item/);}finally{a.dom.window.close();}
});
test('financial refresh failure leaves model price visible and explains the blocked source',async()=>{
 const d=fixture();Object.assign(d,{operations:{mode:'financial_refresh',worker_running:true,coverage:'synthetic',jobs:[],financial_refresh:{value:{status:'blocked',quarter:'FY2027-Q3',reason:'公司公告與 SEC 數字不一致，需人工核對。'}}},publication_status:'Partial',events:[],alerts:[]});
 const a=await app(()=>d);try{assert.match(a.doc.querySelector('#model-price').textContent,/250.00/);assert.match(a.doc.querySelector('#operations').textContent,/SEC 數字不一致/);assert.match(a.doc.querySelector('#evidence').textContent,/失敗時保留上一版/);assert.match(a.doc.body.textContent,/AI 不修改估值/);}finally{a.dom.window.close();}
});

test('live forecast comparison does not require a legacy revision ID',async()=>{
 const d=fixture();d.research.revisions.forEach(r=>{delete r.revision_id;r.forecast_run_id=123;r.previous_run_id=122;});
 const a=await app(()=>d);try{assert.doesNotMatch(a.doc.querySelector('#revision-result').textContent,/NaN|undefined/);assert.match(a.doc.querySelector('#revision-result').textContent,/來源與限制/);}finally{a.dom.window.close();}
});

function synthesis(candidate=false){
 return {version:'StockOSResearchSynthesisV1',quarter:'FY2027-Q2',status:candidate?'candidate_pending_review':'quant_only',headline:'財務與預測需要一併觀察',conclusion:'量化研究已可閱讀；AI 觀點仍待審查。',financial_summary:[{metric:'revenue',label:'營收',current:'1000000000',previous:'800000000',change_ratio:'.25',source_ids:[1]}],forecast_revisions:[{target:'FY2027',status:'AVAILABLE',metrics:{revenue:'.1',eps:'-.2',free_cash_flow:null}}],regime_summary:{confirmed_regime:'Growth',candidate_regime:'Hypergrowth',transition_status:'PENDING_CONFIRMATION'},valuation_summary:{status:'available',base:'250',low:'200',high:'300',basis_date:'2026-08-27',label:'研究日合理價值'},ai:{status:candidate?'candidate_pending_review':'not_generated',reason:candidate?'候選內容待獨立品質審查。':'本季尚未產生 AI 分析。',sections:candidate?[{kind:'drivers',title:'成長驅動因素',claims:[{kind:'management_outlook',text:'管理層預期需求持續。',citations:[{source_id:1,quote:'Demand continues across our platforms.',paragraph_id:'p-7'}]}]},{kind:'risks',title:'風險與反證',claims:[{kind:'inference',text:'需求變動仍可能影響營運。',citations:[{source_id:1,quote:'Demand may change.',paragraph_id:'p-8'}]}]}]:[]},blockers:['尚待真人品質驗收'],decision_ready:false,affects_valuation:false};
}

test('candidate synthesis displays evidence and risks while retaining pending status and Quant value',async()=>{
 const d=fixture();d.research.synthesis=synthesis(true);const a=await app(()=>d);
 try{const panel=a.doc.querySelector('#synthesis');assert.ok(panel);assert.match(panel.textContent,/綜合研究摘要/);assert.match(panel.textContent,/量化重點/);assert.match(panel.textContent,/AI 解釋待驗收/);assert.match(panel.textContent,/候選內容，尚未核准/);assert.match(panel.textContent,/管理層展望/);assert.match(panel.textContent,/分析推論/);assert.match(panel.textContent,/風險與反證/);assert.match(panel.textContent,/不能據此視為最終綜合判斷已完成/);assert.doesNotMatch(panel.textContent,/已核准|正式通過|配置 \d/);assert.equal(panel.querySelectorAll('.synthesis-citation').length,2);const detail=panel.querySelector('.synthesis-citation');assert.equal(detail.open,false);detail.open=true;assert.match(detail.querySelector('blockquote').textContent,/Demand continues/);assert.match(detail.textContent,/p-7/);assert.equal(detail.querySelector('a').getAttribute('href'),d.research.sources[0].url);assert.match(a.doc.querySelector('#model-price').textContent,/250.00/);}finally{a.dom.window.close();}
});

test('Quant-only synthesis reports missing AI and does not promote stray candidate text',async()=>{
 const d=fixture();d.research.synthesis=synthesis();d.research.synthesis.ai.sections=synthesis(true).ai.sections;const a=await app(()=>d);
 try{const panel=a.doc.querySelector('#synthesis');assert.match(panel.textContent,/量化摘要 · AI 待補/);assert.match(panel.textContent,/本季尚未產生 AI 分析/);assert.match(panel.textContent,/目前只提供量化研究摘要/);assert.equal(panel.querySelector('.synthesis-claim'),null);assert.doesNotMatch(panel.textContent,/管理層預期需求持續/);assert.match(panel.textContent,/尚待真人品質驗收/);}finally{a.dom.window.close();}
});

test('synthesis preserves zero and negative financial values and keeps missing data explicit',async()=>{
 const d=fixture(),s=synthesis();s.financial_summary=[{metric:'eps_diluted',label:'稀釋每股盈餘',current:0,previous:'-1.25',change_ratio:null,source_ids:[1]},{metric:'fcf',label:'自由現金流',current:'-2000000000',previous:'0',change_ratio:0,source_ids:[1]},{metric:'revenue',label:'營收',current:null,previous:undefined,change_ratio:null,source_ids:[]}];s.valuation_summary.base=0;s.valuation_summary.low=0;s.valuation_summary.high=0;d.research.synthesis=s;const a=await app(()=>d);
 try{const panel=a.doc.querySelector('#synthesis'),rows=panel.querySelectorAll('tbody tr');assert.match(rows[0].textContent,/\$0.00/);assert.match(rows[0].textContent,/\$-1.25/);assert.match(rows[0].textContent,/資料不足/);assert.match(rows[1].textContent,/-2.00 十億/);assert.match(rows[1].textContent,/0.00%/);assert.match(rows[2].textContent,/資料不足/);assert.doesNotMatch(panel.textContent,/NaN|undefined/);assert.match(panel.querySelector('.synthesis-metrics').textContent,/\$0.00/);}finally{a.dom.window.close();}
});

test('AI claim text, quotes, source URLs and metadata are escaped without executable content',async()=>{
 const d=fixture(),s=synthesis(true),attack='<img src=x onerror=alert(1)>';s.headline=attack;s.conclusion=attack;s.blockers=[attack];s.regime_summary.confirmed_regime=attack;s.valuation_summary.label=attack;s.forecast_revisions[0].target=attack;s.financial_summary[0].label=attack;s.ai.sections[1].title=attack;s.ai.sections[1].claims[0].text=attack;s.ai.sections[1].claims[0].citations[0].quote='<script>alert(1)</script>';s.ai.sections[1].claims[0].citations[0].paragraph_id=attack;d.research.sources[0].url='javascript:alert(1)';d.research.synthesis=s;const a=await app(()=>d);
 try{const panel=a.doc.querySelector('#synthesis');assert.equal(panel.querySelector('img,script,[onerror]'),null);assert.match(panel.textContent,/<img src=x/);assert.equal(panel.querySelectorAll('.synthesis-citation a')[1].getAttribute('href'),'#');assert.equal(panel.querySelectorAll('blockquote')[1].textContent,'<script>alert(1)</script>');assert.match(panel.querySelectorAll('.synthesis-citation')[1].textContent,/<img src=x/);}finally{a.dom.window.close();}
});

test('wrong-quarter or unsupported synthesis cannot be shown as current AI interpretation',async()=>{
 for(const changed of [{quarter:'FY2023-Q2'},{version:'UnverifiedVersion'},{status:'approved'}]){const d=fixture();d.research.synthesis={...synthesis(true),...changed};const a=await app(()=>d);try{assert.equal(a.doc.querySelector('#synthesis'),null);assert.match(a.doc.querySelector('.ai-panel').textContent,/沒有適用本研究版本的核准結果/);assert.doesNotMatch(a.doc.querySelector('.ai-panel').textContent,/管理層預期需求持續/);}finally{a.dom.window.close();}}
});

test('blocked AI and unavailable valuation remain incomplete while financial summary is visible',async()=>{
 const d=fixture(),s=synthesis();s.ai={status:'blocked',reason:'來源版本不符，需要重新分析。',sections:[]};s.valuation_summary={status:'unavailable',base:null};s.forecast_revisions=[{target:'FY2027',status:'UNAVAILABLE',metrics:{}}];d.research.synthesis=s;const a=await app(()=>d);
 try{const panel=a.doc.querySelector('#synthesis');assert.match(panel.textContent,/目前受阻/);assert.match(panel.textContent,/來源版本不符/);assert.match(panel.textContent,/營收/);assert.match(panel.querySelector('.synthesis-metrics').textContent,/資料不足/);assert.match(panel.textContent,/最終綜合判斷已完成/);assert.equal(panel.querySelector('.synthesis-claim'),null);}finally{a.dom.window.close();}
});

test('missing AI citation remains visibly unusable and unknown sources never receive a false link',async()=>{
 const d=fixture(),s=synthesis(true);s.ai.sections[0].claims[0].citations=[];s.ai.sections[1].claims[0].citations[0].source_id=999;d.research.synthesis=s;const a=await app(()=>d);
 try{const claims=a.doc.querySelectorAll('.synthesis-claim');assert.match(claims[0].textContent,/缺少引用，尚不可採用/);assert.match(claims[1].textContent,/來源無法對齊，尚不可採用/);assert.equal(claims[1].querySelector('a'),null);}finally{a.dom.window.close();}
});

test('open AI evidence remains readable when the same research is refreshed',async()=>{
 const d=fixture();d.research.synthesis=synthesis(true);const a=await app(()=>structuredClone(d));
 try{a.doc.querySelector('.synthesis-citation').open=true;a.doc.querySelector('#update').click();await until(()=>!a.doc.querySelector('#update').disabled);assert.equal(a.doc.querySelector('.synthesis-citation').open,true);}finally{a.dom.window.close();}
});

test('expanded AI citations include the complete original paragraph as escaped text',async()=>{
 const d=fixture(),s=synthesis(true),paragraph='Context before the quote.\nDemand continues across our platforms.\n<script>untrusted source text</script>';s.ai.sections[0].claims[0].citations[0].paragraph=paragraph;d.research.synthesis=s;const a=await app(()=>d);
 try{const detail=a.doc.querySelector('.synthesis-citation');detail.open=true;assert.match(detail.textContent,/段落全文/);assert.equal(detail.querySelector('.synthesis-paragraph').textContent,paragraph);assert.equal(detail.querySelector('script'),null);assert.equal(detail.querySelector('blockquote').textContent,'Demand continues across our platforms.');}finally{a.dom.window.close();}
});
