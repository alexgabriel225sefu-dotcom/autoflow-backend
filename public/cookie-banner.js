// Minimal GDPR cookie consent banner — strictly-necessary-only site
(function(){
  if(localStorage.getItem('ck_consent'))return;
  var s=document.createElement('style');
  s.textContent='#ckb{position:fixed;bottom:0;left:0;right:0;z-index:9999;background:rgba(12,12,18,.97);border-top:1px solid rgba(255,255,255,.08);padding:14px 20px}'+
    '#ckb .ckw{max-width:1200px;margin:0 auto;display:flex;align-items:center;gap:16px;flex-wrap:wrap}'+
    '#ckb p{flex:1;font:400 13px/1.5 system-ui,sans-serif;color:#aaa;margin:0}'+
    '#ckb a{color:inherit;text-decoration:underline;opacity:.7}'+
    '#ckb .ckbtns{display:flex;gap:10px;flex-shrink:0}'+
    '#ckb .cka{background:#f59e0b;color:#000;border:none;border-radius:7px;padding:8px 18px;font:600 13px system-ui;cursor:pointer}'+
    '#ckb .ckn{background:transparent;color:#999;border:1px solid rgba(255,255,255,.15);border-radius:7px;padding:8px 18px;font:500 13px system-ui;cursor:pointer}';
  document.head.appendChild(s);
  var b=document.createElement('div');
  b.id='ckb';
  b.innerHTML='<div class="ckw"><p>We use cookies for payment processing (Stripe — strictly necessary) and to remember your preferences. No advertising or tracking cookies are used. <a href="/privacy#cookies">Cookie policy</a></p><div class="ckbtns"><button class="cka">Accept</button><button class="ckn">Necessary only</button></div></div>';
  document.body.appendChild(b);
  b.querySelector('.cka').onclick=function(){localStorage.setItem('ck_consent','all');b.remove();};
  b.querySelector('.ckn').onclick=function(){localStorage.setItem('ck_consent','necessary');b.remove();};
})();
