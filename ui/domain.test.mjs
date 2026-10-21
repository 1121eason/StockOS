import test from 'node:test';
import assert from 'node:assert/strict';
import {number,validate,escapeHTML,routeFrom} from './domain.mjs';
const valid={wacc:10,terminal_growth:2.5,growth:0,cash:0,debt:0,shares:100};
test('missing is distinct from zero; negative DCF remains visible',()=>{
  assert.equal(number(null),'—');assert.equal(number(undefined),'—');assert.equal(number(''),'—');assert.equal(number(' '),'—');assert.equal(number(false),'—');
  assert.equal(number(0),'0.00');assert.equal(number(-12.34),'-12.34');assert.equal(number('NaN'),'—');
  assert.deepEqual(validate(valid),{});
});
test('rejects every missing input, booleans, nonfinite and incompatible rates',()=>{
  for(const field of Object.keys(valid))for(const raw of ['',null,undefined,true,'NaN','Infinity'])assert.ok(validate({...valid,[field]:raw})[field]);
  assert.ok(validate({...valid,shares:0}).shares);assert.ok(validate({...valid,debt:-1}).debt);
  assert.ok(validate({...valid,wacc:2,terminal_growth:2}).wacc);
});
test('hash routes survive deep links and invalid routes fail to overview',()=>{
  assert.deepEqual(routeFrom('#evidence?company=atlas'),{route:'evidence',company:'atlas'});
  assert.deepEqual(routeFrom('#bad'),{route:'overview',company:'aurora'});
});
test('source text is rendered as text, never executable markup',()=>{
  assert.equal(escapeHTML('<img src=x onerror="bad">'),'&lt;img src=x onerror=&quot;bad&quot;&gt;');
});
