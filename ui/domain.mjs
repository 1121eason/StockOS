export const labels = {missing:'缺少資料', stale:'時點過期', unverified:'尚未驗證', quarantined:'已隔離', unavailable:'無法取得'};
export const limits = {wacc:[0.1,50], terminal_growth:[-20,20], growth:[-50,100], cash:[0,1e9], debt:[0,1e9], shares:[0.000001,1e9]};
export function number(value, digits=2) {
  if(!['string','number'].includes(typeof value) || String(value).trim()==='' || !Number.isFinite(Number(value))) return '—';
  return new Intl.NumberFormat('en-US',{minimumFractionDigits:digits,maximumFractionDigits:digits}).format(Number(value));
}
export function validate(values) {
  const errors={};
  for(const [key,[low,high]] of Object.entries(limits)) {
    const raw=values[key];
    if(raw===null || raw===undefined || typeof raw==='boolean' || String(raw).trim()==='') errors[key]='必填；缺值不會自動視為 0。';
    else if(!Number.isFinite(Number(raw)) || Number(raw)<low || Number(raw)>high) errors[key]=`請輸入 ${low} 至 ${high} 之間的數值。`;
  }
  if(!errors.wacc && !errors.terminal_growth && Number(values.wacc)<=Number(values.terminal_growth)) errors.wacc='WACC 必須大於終端成長率。';
  return errors;
}
export function escapeHTML(value) {return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
export function routeFrom(hash) {
  const [route,query]=hash.replace(/^#/,'').split('?');
  return {route:['overview','assumptions','evidence','status'].includes(route)?route:'overview',company:new URLSearchParams(query).get('company')||'aurora'};
}
