import {after,before,test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createServer} from 'node:net';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {SourceTextModule} from 'node:vm';
import {JSDOM,VirtualConsole} from 'jsdom';

const root=new URL('../',import.meta.url);
let child,base;
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check) {for(let i=0;i<200;i++){if(check())return;await wait(10);}throw new Error('UI state did not settle');}
before(async()=>{
  const socket=createServer();socket.listen(0,'127.0.0.1');await once(socket,'listening');
  const port=socket.address().port;await new Promise(resolve=>socket.close(resolve));
  base=`http://127.0.0.1:${port}`;
  child=spawn('python3',['scripts/serve_ui.py','--port',String(port)],{cwd:root,stdio:['ignore','pipe','ignore']});
  await once(child.stdout,'data');
  assert.equal((await fetch(base+'/api/health')).status,200);
});
after(async()=>{if(child&&!child.killed){child.kill('SIGTERM');await once(child,'exit');}});

async function app(hash='#overview?company=aurora') {
  const html=await readFile(new URL('ui/index.html',root),'utf8');
  const dom=new JSDOM(html,{url:base+'/'+hash,runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:new VirtualConsole()});
  const w=dom.window,doc=w.document;
  w.scrollTo=()=>{};w.Element.prototype.scrollIntoView=()=>{};
  w.HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
  w.HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');};
  w.AbortController=globalThis.AbortController;
  const controls={fail:false,hold:false,release:null,calls:0};
  w.fetch=async(path,options)=>{
    if(path==='/api/sandbox') {
      controls.calls++;
      if(controls.fail)throw new Error('Simulated offline');
      if(controls.hold)await new Promise(resolve=>{controls.release=resolve;});
    }
    return fetch(new URL(path,base),options);
  };
  const context=dom.getInternalVMContext();
  const entry=new SourceTextModule(await readFile(new URL('ui/app.js',root),'utf8'),{context});
  await entry.link(async spec=>{assert.equal(spec,'./domain.mjs');return new SourceTextModule(await readFile(new URL('ui/domain.mjs',root),'utf8'),{context});});
  await entry.evaluate();await until(()=>doc.querySelector('#main').getAttribute('aria-busy')==='false');
  const click=selector=>{const element=doc.querySelector(selector);assert.ok(element,selector);element.click();};
  const fill=(selector,value)=>{const input=doc.querySelector(selector);input.value=value;input.dispatchEvent(new w.Event('input',{bubbles:true}));};
  const route=async name=>{click(`[data-route="${name}"]`);await until(()=>doc.querySelector('h1')?.textContent===({overview:'估值總覽',assumptions:'假設沙盒',evidence:'模型與證據',status:'資料與驗證'}[name]));};
  return {dom,w,doc,controls,click,fill,route};
}

test('invalid and missing inputs focus errors; repeated clicks submit once; applied values survive navigation',async()=>{
  const a=await app('#assumptions?company=aurora');
  try {
    a.fill('#wacc','2');a.click('#calculate');
    assert.equal(a.doc.activeElement.id,'wacc');assert.match(a.doc.querySelector('#wacc-error').textContent,/WACC/);assert.equal(a.controls.calls,0);
    a.fill('#wacc','12');a.fill('#cash','');a.click('#calculate');assert.equal(a.doc.activeElement.id,'cash');assert.equal(a.controls.calls,0);
    a.fill('#cash','0');a.fill('#debt','0');a.click('#calculate');a.click('#calculate');
    await until(()=>a.doc.querySelector('#form-status').textContent.includes('已套用'));
    assert.equal(a.controls.calls,1);assert.match(a.doc.querySelector('#sandbox-result').textContent,/已套用的沙盒結果/);
    await a.route('overview');assert.match(a.doc.querySelector('.scenario-grid').textContent,/12.0%/);
    a.w.history.back();await until(()=>a.doc.querySelector('#wacc'));
    assert.equal(Number(a.doc.querySelector('#wacc').value),12);
    a.click('.skip');assert.equal(a.doc.activeElement.id,'main');assert.match(a.w.location.hash,/assumptions/);
  } finally {a.dom.window.close();}
});

test('unsaved navigation can be cancelled or discarded; fiscal target persists and never unlocks a decision',async()=>{
  const a=await app('#assumptions?company=aurora');
  try {
    a.fill('#wacc','11');a.click('[data-route="evidence"]');
    assert.ok(a.doc.querySelector('#leave-dialog').open);a.click('#stay');assert.equal(a.doc.querySelector('#wacc').value,'11');
    a.click('[data-route="evidence"]');a.click('#discard');await until(()=>a.doc.querySelector('#fiscal-target'));
    const select=a.doc.querySelector('#fiscal-target');select.value='FY2027';select.dispatchEvent(new a.w.Event('change'));
    assert.match(a.doc.querySelector('#revision-status').textContent,/仍暫緩/);
    await a.route('overview');assert.match(a.doc.querySelector('.research-list').textContent,/FY2027/);assert.match(a.doc.querySelector('.metrics').textContent,/暫緩/);
    await a.route('evidence');assert.equal(a.doc.querySelector('#fiscal-target').value,'FY2027');
  } finally {a.dom.window.close();}
});

test('company search, negative DCF and empty data remain distinct',async()=>{
  const a=await app();
  try {
    a.click('#company-button');a.fill('#company-search','does not exist');assert.match(a.doc.querySelector('#company-list').textContent,/找不到公司/);
    a.fill('#company-search','ATL');a.click('[data-company="atlas"]');await until(()=>a.doc.querySelector('.company-name')?.textContent.includes('衡川'));
    assert.match(a.doc.querySelector('.negative').textContent,/原值保留/);assert.match(a.doc.querySelector('.metric-value').textContent,/\$-/);
    a.click('#company-button');a.fill('#company-search','NEW');a.click('[data-company="empty"]');await until(()=>a.doc.querySelector('#empty-company'));
    assert.match(a.doc.querySelector('#main').textContent,/還沒有可用/);assert.doesNotMatch(a.doc.querySelector('#main').textContent,/\$0\.00/);
    await a.route('status');await until(()=>a.doc.querySelector('#health-status')?.textContent.includes('未連接'));assert.match(a.doc.querySelector('#main').textContent,/未連接/);
  } finally {a.dom.window.close();}
});

test('interrupted calculation cannot overwrite a reset; failed calculation keeps inputs for retry',async()=>{
  const a=await app('#assumptions?company=aurora');
  try {
    a.controls.hold=true;a.fill('#wacc','12');a.click('#calculate');await until(()=>a.controls.release);
    assert.ok(a.doc.querySelector('#wacc').disabled);a.click('#reset-assumptions');a.controls.release();await wait(30);
    assert.equal(Number(a.doc.querySelector('#wacc').value),10);assert.match(a.doc.querySelector('#sandbox-result').textContent,/合成基準結果/);
    assert.ok(!a.doc.querySelector('#calculate').disabled);assert.ok(!a.doc.querySelector('#wacc').disabled);
    a.controls.hold=false;a.controls.fail=true;a.fill('#wacc','12');a.click('#calculate');await until(()=>a.doc.querySelector('#form-status').textContent.includes('計算未完成'));
    assert.equal(a.doc.querySelector('#wacc').value,'12');assert.ok(!a.doc.querySelector('#calculate').disabled);
    a.controls.fail=false;a.click('#calculate');await until(()=>a.doc.querySelector('#form-status').textContent.includes('已套用'));
  } finally {a.dom.window.close();}
});

test('unknown company shows recoverable error instead of invented results',async()=>{
  const a=await app('#overview?company=unknown');
  try {assert.match(a.doc.querySelector('h1').textContent,/暫時無法載入/);assert.ok(a.doc.querySelector('#retry-load'));assert.ok(a.doc.querySelector('#return-demo'));}
  finally {a.dom.window.close();}
});
