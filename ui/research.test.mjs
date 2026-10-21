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

function typedRun() {
 return {
  ...structuredClone(run),schema_version:2,economic_as_of:'2022-06-30T00:00:00Z',historical_oos:false,
  source_vintages_verified:false,model_vintages_verified:false,price_vintages_verified:false,
  formal_decision:'withheld',source_verification:'asserted_unverified',
  provenance_limitations:['Current reconstruction is not historical out-of-sample evidence.','Source, model and price vintages remain unverified.'],
  bundle:{...structuredClone(run.bundle),schema_version:2,name:'Synthetic internal policy test',
   economic_as_of:'2022-06-30T00:00:00Z',as_of:'2026-10-16T00:00:00Z',
   assumptions:{rationale:'Synthetic fixed research policy; no return fitting.'},
   inputs:{wacc:{value:'0.10',available_at:'2026-10-15T00:00:00Z',source_ids:['internal_policy']},terminal_growth:{value:'0.02',available_at:'2026-10-15T00:00:00Z',source_ids:['internal_policy']},cash:{value:null,available_at:null,source_ids:[]}},
   sources:[{...structuredClone(run.bundle.sources[0]),kind:'external_document',retrieved_at:'2026-10-14T00:00:00Z'},
    {kind:'internal_policy_artifact',id:'internal_policy',source_type:'fixed_research_policy_not_return_fitted',
     policy_version:'SyntheticPolicyV1',assumption_set_id:1,content_sha256:'b'.repeat(64),assumption_content_hash:'c'.repeat(64),
     content:{version:'SyntheticPolicyV1',classification:'research_reconstructed_internal',effective_from:'2026-01-01T00:00:00Z',wacc_base:'0.10',terminal_growth_base:'0.02',notes:{statement:'Synthetic fixture only'}},
     created_at:'2026-01-02T00:00:00Z',effective_from:'2026-01-01T00:00:00Z',observed_at:'2026-10-15T00:00:00Z',
     published_at:null,historical_available_at:null,source_reference:'Synthetic internal policy fixture; no public publication claimed',
     parameter_records:[{record_id:11,parameter:'wacc',value:'0.10',created_at:'2026-01-02T00:00:01Z'},{record_id:12,parameter:'terminal_growth',value:'0.02',created_at:'2026-01-02T00:00:02Z'}],
    }],
  },
 };
}
function summary(saved) {
 return {ticker:saved.bundle.ticker,data_kind:saved.bundle.data_kind,as_of:saved.bundle.as_of,run_id:saved.run_id,schema_version:saved.bundle.schema_version,economic_as_of:saved.bundle.economic_as_of};
}
function definitionValue(scope,label) {
 const term=[...scope.querySelectorAll('dt')].find(node=>node.textContent===label);
 assert.ok(term,`Missing definition: ${label}`);
 return term.nextElementSibling.textContent;
}
async function chooseAndWait(a,id=run.run_id) {
 await until(()=>!a.doc.querySelector('#run').disabled);a.choose(id);
 await until(()=>a.doc.querySelector('#message').textContent==='已載入；正式決策仍暫緩。');
}
test('schema 2 separates economic checkpoint, reconstruction cutoff and generation time; all evidence gates stay explicit',async()=>{
 const saved=typedRun();
 const a=await app(path=>path.endsWith('/runs')?{configured:true,runs:[summary(saved)]}:saved);
 try{
  await chooseAndWait(a);const result=a.doc.querySelector('#result');
  assert.equal(definitionValue(result,'歷史經濟檢查點 economic_as_of'),'2022-06-30T00:00:00Z');
  assert.equal(definitionValue(result,'本次重建截止 as_of'),'2026-10-16T00:00:00Z');
  assert.equal(definitionValue(result,'實際重建時間 generated_at'),'2026-10-17T00:00:00Z');
  for(const label of ['歷史樣本外 historical_oos','來源版本已驗證 source_vintages_verified','模型版本已驗證 model_vintages_verified','價格版本已驗證 price_vintages_verified'])assert.equal(definitionValue(result,label),'false');
  assert.equal(definitionValue(result,'正式決策 formal_decision'),'withheld');
  assert.equal(definitionValue(result,'來源驗證 source_verification'),'asserted_unverified');
  assert.deepEqual([...result.querySelectorAll('.provenance-limitations li')].map(li=>li.textContent),saved.provenance_limitations);
  assert.match(result.textContent,/經濟檢查點不能證明當時已取得資料或已有此模型/);
  assert.match(result.textContent,/內部政策 available_at 是本次觀察後的可用聲明/);
  assert.match(a.doc.querySelector('#run').selectedOptions[0].textContent,/經濟 2022-06-30T00:00:00Z · 重建截止 2026-10-16T00:00:00Z/);
  assert.match(result.textContent,/缺值/);
 }finally{a.dom.window.close();}
});
test('typed source cards preserve null publication and historical availability, distinct dates, original and compact hashes, records and full content',async()=>{
 const saved=typedRun(), source=saved.bundle.sources[1];
 const a=await app(path=>path.endsWith('/runs')?{configured:true,runs:[summary(saved)]}:saved);
 try{
  await chooseAndWait(a);const internal=a.doc.querySelector('.internal-policy-source'),external=a.doc.querySelector('.external-document-source');
  assert.ok(internal);assert.ok(external);
  assert.match(internal.textContent,/internal_policy_artifact/);assert.match(external.textContent,/external_document/);
  assert.equal(definitionValue(internal,'發布時間 published_at'),'NULL · 不主張公開發布');
  assert.equal(definitionValue(internal,'歷史可用時間 historical_available_at'),'NULL · 不主張歷史可用');
  for(const [label,key] of [['建立時間 created_at','created_at'],['生效時間 effective_from','effective_from'],['本次觀察時間 observed_at','observed_at'],['原始假設內容雜湊 assumption_content_hash','assumption_content_hash'],['緊湊標準化內容雜湊 content_sha256','content_sha256'],['來源參照 source_reference','source_reference'],['來源類型 source_type','source_type'],['政策版本 policy_version','policy_version'],['原始假設集合 ID assumption_set_id','assumption_set_id']])assert.equal(definitionValue(internal,label),String(source[key]));
  assert.equal(definitionValue(external,'發布時間 published_at'),saved.bundle.sources[0].published_at);
  assert.equal(definitionValue(external,'取得時間 retrieved_at'),saved.bundle.sources[0].retrieved_at);
  assert.equal(definitionValue(external,'文件 SHA-256 sha256'),saved.bundle.sources[0].sha256);
  assert.equal(internal.querySelector('pre').textContent,JSON.stringify(source.content,null,2));
  assert.deepEqual([...internal.querySelectorAll('tbody tr')].map(row=>[...row.children].map(cell=>cell.textContent)),[['11','wacc','0.10','2026-01-02T00:00:01Z'],['12','terminal_growth','0.02','2026-01-02T00:00:02Z']]);
  assert.equal(internal.querySelector('a'),null);assert.doesNotMatch(internal.textContent,/undefined/);
 }finally{a.dom.window.close();}
});
test('schema 1 keeps its date meaning, external sources, zero valuation and selector without inferred schema-2 gates',async()=>{
 const saved={...structuredClone(run),bundle:{...structuredClone(run.bundle),schema_version:1}};
 const a=await app(path=>path.endsWith('/runs')?{configured:true,runs:[summary(saved)]}:saved);
 try{
  await chooseAndWait(a);const result=a.doc.querySelector('#result');
  assert.equal(definitionValue(result,'資料截止 as-of'),saved.bundle.as_of);
  assert.doesNotMatch(result.textContent,/economic_as_of|historical_oosfalse|source_vintages_verified|historical_available_at/);
  assert.equal(result.querySelector('.internal-policy-source'),null);assert.ok(result.querySelector('.external-document-source'));
  assert.match(result.textContent,/\$0.00/);
  assert.equal(a.doc.querySelector('#run').selectedOptions[0].textContent,`TEST · 真實聲明 · ${saved.bundle.as_of} · ${saved.run_id}`);
 }finally{a.dom.window.close();}
});
test('all displayed schema-2 provenance fields, nested content, input fields and limitations are escaped as text',async()=>{
 const saved=typedRun(), injection='</pre><img src=x onerror=alert(1)><svg onload=alert(2)><script>alert(3)</script>&"\'', strings=[];
 const hostile=label=>{const value=label+injection;strings.push(value);return value;};
 for(const key of ['input_hash','generated_at','classification','historical_oos','source_vintages_verified','model_vintages_verified','price_vintages_verified','formal_decision','source_verification'])saved[key]=hostile(key);
 for(const key of ['ticker','name','economic_as_of','as_of'])saved.bundle[key]=hostile(key);
 saved.bundle.assumptions.rationale=hostile('rationale');
 saved.provenance_limitations=[hostile('limitation')];
 const external=saved.bundle.sources[0], internal=saved.bundle.sources[1];
 for(const key of ['id','url','published_at','retrieved_at','sha256'])external[key]=hostile('external_'+key);
 for(const key of ['id','source_type','policy_version','assumption_set_id','content_sha256','assumption_content_hash','created_at','effective_from','observed_at','published_at','historical_available_at','source_reference'])internal[key]=hostile('internal_'+key);
 for(const key of ['record_id','parameter','value','created_at'])internal.parameter_records[0][key]=hostile('record_'+key);
 internal.content={['content_key'+injection]:{nested:['content_value'+injection]}};
 const inputKey=hostile('input_key'), inputValue=hostile('input_value'), available=hostile('available_at'), sourceId=hostile('input_source_id');
 saved.bundle.inputs={[inputKey]:{value:inputValue,available_at:available,source_ids:[sourceId]}};
 saved.valuation.scenarios=[{name:hostile('scenario_name'),status:'available',per_share:'0'}];
 const a=await app(path=>path.endsWith('/runs')?{configured:true,runs:[summary(saved)]}:saved);
 try{
  await chooseAndWait(a);const result=a.doc.querySelector('#result');
  for(const value of strings)assert.ok(result.textContent.includes(value),`Missing literal ${value.split('<')[0]}`);
  assert.equal(result.querySelector('pre').textContent,JSON.stringify(internal.content,null,2));
  assert.equal(result.querySelector('img,svg,script,iframe,object,embed'),null);
  assert.equal(a.doc.querySelector('#run').querySelector('img,svg,script'),null);
  for(const element of result.querySelectorAll('*'))for(const attribute of element.attributes)assert.equal(attribute.name.startsWith('on'),false);
 }finally{a.dom.window.close();}
});
test('unknown typed source kinds are escaped and never mislabeled as external documents',async()=>{
 const saved=typedRun();saved.bundle.sources=[{id:'unknown',kind:'<img src=x onerror=alert(1)>'}];
 const a=await app(path=>path.endsWith('/runs')?{configured:true,runs:[summary(saved)]}:saved);
 try{await chooseAndWait(a);assert.match(a.doc.querySelector('#result').textContent,/未支援的來源類型：<img/);assert.equal(a.doc.querySelector('.external-document-source,.internal-policy-source,#result img'),null);}finally{a.dom.window.close();}
});
test('late schema-2 response and stale refresh failure cannot overwrite a newer schema-1 selection or list',async()=>{
 let release, rejectRefresh, requests=0;
 const a=await app(path=>{
  if(path.endsWith('/runs')){requests++;return requests===2?new Promise((resolve,reject)=>{rejectRefresh=()=>reject(new Error('obsolete list failure'));}):{configured:true,runs:[{...summary(run),run_id:'v1'},{...summary(typedRun()),run_id:'v2'}]};}
  return path.endsWith('v2')?new Promise(resolve=>{release=()=>resolve(typedRun());}):run;
 });
 try{
  await until(()=>!a.doc.querySelector('#run').disabled);a.choose('v2');await until(()=>release);
  a.choose('v1');await until(()=>a.doc.querySelector('#result').textContent.includes('資料截止 as-of'));release();await wait(30);
  assert.equal(a.doc.querySelector('.internal-policy-source'),null);
  a.doc.querySelector('#refresh').click();await until(()=>rejectRefresh);
  a.doc.querySelector('#refresh').click();await until(()=>a.doc.querySelector('#result').textContent.includes('資料截止 as-of'));rejectRefresh();await wait(30);
  assert.equal(a.doc.querySelector('#run').disabled,false);assert.equal(a.doc.querySelector('#run').value,'v1');
  assert.doesNotMatch(a.doc.querySelector('#message').textContent,/obsolete/);
 }finally{a.dom.window.close();}
});
test('a failed refresh clears saved content and never renders an error message as HTML',async()=>{
 let failed=false;
 const a=await app(path=>{if(path.endsWith('/runs')){if(failed)throw new Error('<img src=x onerror=alert(1)>');return {configured:true,runs:[summary(run)]};}return run;});
 try{
  await chooseAndWait(a);failed=true;a.doc.querySelector('#refresh').click();
  await until(()=>a.doc.querySelector('#message').textContent.includes('<img'));
  assert.equal(a.doc.querySelector('#result').textContent,'');assert.equal(a.doc.querySelector('#message img'),null);
  assert.equal(a.doc.querySelector('#run').disabled,false);assert.equal(a.doc.querySelector('#run').value,'');
 }finally{a.dom.window.close();}
});
