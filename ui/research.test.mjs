import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {SourceTextModule} from 'node:vm';
import {JSDOM} from 'jsdom';
const root=new URL('../',import.meta.url);
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check){for(let i=0;i<200;i++){if(check())return;await wait(10);}throw new Error('Research UI did not settle');}
const run={run_id:'rw1_test',input_hash:'test',generated_at:'2026-10-17T00:00:00Z',classification:'research_reconstructed_not_historical_oos',bundle:{ticker:'TEST',name:'<img src=x onerror=alert(1)>',data_kind:'real',as_of:'2020-01-01T00:00:00Z',sources:[{id:'source',url:'https://example.com/<script>',published_at:'2019-01-01T00:00:00Z',retrieved_at:'2026-10-17T00:00:00Z',sha256:'a'.repeat(64)}]},valuation:{status:'available',per_share:'0',negative_equity_warning:false}};
async function app(handler){
 const dom=new JSDOM(await readFile(new URL('ui/research.html',root),'utf8'),{url:'http://127.0.0.1:8501/research',runScripts:'outside-only'});
 dom.window.AbortController=globalThis.AbortController;
 dom.window.fetch=async(path,options)=>({ok:true,json:async()=>handler(path,options)});
 const context=dom.getInternalVMContext();
 const entry=new SourceTextModule(await readFile(new URL('ui/research.js',root),'utf8'),{context});
 await entry.link(async()=>new SourceTextModule(await readFile(new URL('ui/domain.mjs',root),'utf8'),{context}));await entry.evaluate();
 return {dom,doc:dom.window.document,choose(id){const s=dom.window.document.querySelector('#run');s.value=id;s.dispatchEvent(new dom.window.Event('change'));}};
}
test('unconfigured and empty research store never falls back to a synthetic estimate',async()=>{
 for(const configured of [false,true]){const a=await app(()=>({configured,runs:[]}));try{await until(()=>!a.doc.querySelector('#run').disabled);assert.match(a.doc.querySelector('#message').textContent,configured?/尚未匯入/:/未設定/);assert.equal(a.doc.querySelector('#result').textContent,'');}finally{a.dom.window.close();}}
});
test('zero valuation, explicit reconstruction, actual generation time and unverified source claims are displayed safely',async()=>{
 const a=await app(path=>path.endsWith('/runs')?{configured:true,runs:[{ticker:'TEST',as_of:run.bundle.as_of,run_id:run.run_id}]}:run);
 try{await until(()=>!a.doc.querySelector('#run').disabled);a.choose(run.run_id);await until(()=>a.doc.querySelector('#result').textContent.includes('DCFPolicyV1'));
 assert.match(a.doc.querySelector('#result').textContent,/\$0.00/);assert.match(a.doc.querySelector('#result').textContent,/2026-10-17/);assert.match(a.doc.querySelector('#result').textContent,/research_reconstructed_not_historical_oos/);assert.match(a.doc.querySelector('#result').textContent,/尚未驗證/);assert.equal(a.doc.querySelector('#result img'),null);assert.equal(a.doc.querySelector('#result script'),null);
 }finally{a.dom.window.close();}
});
test('newer selection wins over late previous response; missing inputs remain unavailable',async()=>{
 let release;
 const a=await app(path=>path.endsWith('/runs')?{configured:true,runs:[{ticker:'OLD',as_of:run.bundle.as_of,run_id:'old'},{ticker:'NEW',as_of:run.bundle.as_of,run_id:'new'}]}:path.endsWith('old')?new Promise(resolve=>{release=()=>resolve(run);}):{...run,bundle:{...run.bundle,ticker:'NEW'},valuation:{status:'unavailable',reason:'missing_cash'}});
 try{await until(()=>!a.doc.querySelector('#run').disabled);a.choose('old');await until(()=>release);a.choose('new');await until(()=>a.doc.querySelector('#result').textContent.includes('missing_cash'));release();await wait(30);assert.match(a.doc.querySelector('#result').textContent,/NEW/);assert.doesNotMatch(a.doc.querySelector('#result').textContent,/\$0.00/);a.choose('');assert.equal(a.doc.querySelector('#result').textContent,'');}finally{a.dom.window.close();}
});
test('failed result read clears old content and refresh retries the selected immutable run',async()=>{
 let failed=true;
 const a=await app(path=>{if(path.endsWith('/runs'))return {configured:true,runs:[{ticker:'TEST',as_of:run.bundle.as_of,run_id:run.run_id}]};if(failed)throw new Error('store unavailable');return run;});
 try{await until(()=>!a.doc.querySelector('#run').disabled);a.choose(run.run_id);await until(()=>a.doc.querySelector('#message').textContent.includes('store unavailable'));assert.equal(a.doc.querySelector('#result').textContent,'');failed=false;a.doc.querySelector('#refresh').click();await until(()=>a.doc.querySelector('#result').textContent.includes('DCFPolicyV1'));assert.equal(a.doc.querySelector('#run').disabled,false);}finally{a.dom.window.close();}
});
