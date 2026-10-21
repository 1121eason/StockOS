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
