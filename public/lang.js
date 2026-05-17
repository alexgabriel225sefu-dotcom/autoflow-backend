// Shared language picker + Google Translate integration
(function(){
'use strict';

var LANGS=[['en','🇬🇧','English'],['ro','🇷🇴','Română'],['de','🇩🇪','Deutsch'],['fr','🇫🇷','Français'],['es','🇪🇸','Español'],['it','🇮🇹','Italiano'],['pt','🇵🇹','Português'],['nl','🇳🇱','Nederlands'],['pl','🇵🇱','Polski'],['sv','🇸🇪','Svenska'],['no','🇳🇴','Norsk'],['da','🇩🇰','Dansk'],['fi','🇫🇮','Suomi'],['cs','🇨🇿','Čeština'],['sk','🇸🇰','Slovenčina'],['hu','🇭🇺','Magyar'],['hr','🇭🇷','Hrvatski'],['bg','🇧🇬','Български'],['uk','🇺🇦','Українська'],['ru','🇷🇺','Русский'],['el','🇬🇷','Ελληνικά'],['tr','🇹🇷','Türkçe'],['ar','🇸🇦','العربية'],['he','🇮🇱','עברית'],['fa','🇮🇷','فارسی'],['hi','🇮🇳','हिन्दी'],['bn','🇧🇩','বাংলা'],['ur','🇵🇰','اردو'],['zh','🇨🇳','中文'],['ja','🇯🇵','日本語'],['ko','🇰🇷','한국어'],['vi','🇻🇳','Tiếng Việt'],['th','🇹🇭','ภาษาไทย'],['id','🇮🇩','Bahasa Indonesia'],['ms','🇲🇾','Bahasa Melayu'],['tl','🇵🇭','Filipino'],['sw','🇰🇪','Kiswahili'],['am','🇪🇹','አማርኛ'],['ha','🇳🇬','Hausa'],['yo','🇳🇬','Yorùbá'],['ig','🇳🇬','Igbo'],['zu','🇿🇦','isiZulu'],['af','🇿🇦','Afrikaans'],['lt','🇱🇹','Lietuvių'],['lv','🇱🇻','Latviešu'],['et','🇪🇪','Eesti'],['sl','🇸🇮','Slovenščina'],['sr','🇷🇸','Српски'],['mk','🇲🇰','Македонски'],['sq','🇦🇱','Shqip'],['ka','🇬🇪','ქართული'],['hy','🇦🇲','Հայերեն'],['az','🇦🇿','Azərbaycan'],['kk','🇰🇿','Қазақша'],['uz','🇺🇿','O\'zbek'],['mn','🇲🇳','Монгол'],['my','🇲🇲','မြန်မာ'],['km','🇰🇭','ខ្មែរ'],['lo','🇱🇦','ລາວ'],['si','🇱🇰','සිංහල'],['ne','🇳🇵','नेपाली'],['gu','🇮🇳','ગુજરાતી'],['ta','🇮🇳','தமிழ்'],['te','🇮🇳','తెలుగు'],['kn','🇮🇳','ಕನ್ನಡ'],['ml','🇮🇳','മലയാളം'],['mr','🇮🇳','मराठी'],['pa','🇮🇳','ਪੰਜਾਬੀ'],['so','🇸🇴','Soomaali'],['rw','🇷🇼','Kinyarwanda'],['mg','🇲🇬','Malagasy'],['mt','🇲🇹','Malti'],['is','🇮🇸','Íslenska'],['eu','🇪🇸','Euskara'],['gl','🇪🇸','Galego'],['ca','🇪🇸','Català'],['cy','🏴󠁧󠁢󠁷󠁬󠁳󠁿','Cymraeg'],['ga','🇮🇪','Gaeilge'],['lb','🇱🇺','Lëtzebuergesch'],['tk','🇹🇲','Türkmen'],['ps','🇦🇫','پښتو'],['ku','🏳️','Kurdî']];

var curLang=localStorage.getItem('af_lang')||'en';

// Inject CSS (Google Translate toolbar hide + lang picker styles)
var _css=document.createElement('style');
_css.textContent=
  '.goog-te-banner-frame,.goog-te-gadget,.goog-te-menu-frame,.goog-tooltip,.goog-tooltip-input,.skiptranslate{display:none!important}'+
  'body{top:0!important}'+
  '#af-gte{display:none!important}'+
  '.af-lang-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:99999;align-items:center;justify-content:center}'+
  '.af-lang-modal.open{display:flex}'+
  '.af-lang-box{background:#111;border:1px solid rgba(229,62,46,.2);border-radius:12px;padding:20px;width:min(90vw,480px);max-height:72vh;display:flex;flex-direction:column;gap:10px}'+
  '.af-lang-search{background:#161616;border:1px solid rgba(229,62,46,.15);border-radius:6px;padding:8px 12px;color:#f5f5f5;font-size:14px;width:100%;outline:none;font-family:inherit}'+
  '.af-lang-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(128px,1fr));gap:6px;overflow-y:auto}'+
  '.af-lang-opt{padding:7px 10px;border-radius:6px;border:1px solid rgba(229,62,46,.1);background:#161616;cursor:pointer;font-size:12px;color:#f5f5f5;text-align:left;font-family:inherit}'+
  '.af-lang-opt:hover,.af-lang-opt.active{background:rgba(229,62,46,.12);border-color:rgba(229,62,46,.4)}'+
  '.af-lang-btn{display:inline-flex;align-items:center;gap:5px;padding:6px 10px;border:1px solid rgba(229,62,46,.2);border-radius:6px;background:none;color:#E53E2E;font-size:12px;cursor:pointer;font-family:inherit;transition:all .2s;white-space:nowrap}'+
  '.af-lang-btn:hover{background:rgba(229,62,46,.08)}';
document.head.appendChild(_css);

// Google Translate widget setup
window.googleTranslateElementInit=function(){
  if(typeof google==='undefined'||!google.translate)return;
  new google.translate.TranslateElement({pageLanguage:'en',autoDisplay:false},'af-gte');
};

document.addEventListener('DOMContentLoaded',function(){
  // Google Translate hidden element
  var gte=document.createElement('div');
  gte.id='af-gte';
  document.body.appendChild(gte);

  // Google Translate script
  var sc=document.createElement('script');
  sc.src='//translate.google.com/translate_a/element.js?cb=googleTranslateElementInit';
  sc.async=true;
  document.body.appendChild(sc);

  // Language picker modal
  var modal=document.createElement('div');
  modal.className='af-lang-modal';
  modal.id='afLangModal';
  modal.addEventListener('click',function(e){if(e.target===modal)AF_closeLang();});
  modal.innerHTML=
    '<div class="af-lang-box">'+
    '<input class="af-lang-search" id="afLangSearch" placeholder="🔍 Search language..." oninput="AF_filterLangs(this.value)" autocomplete="off"/>'+
    '<div class="af-lang-grid" id="afLangGrid"></div>'+
    '</div>';
  document.body.appendChild(modal);

  _updateBtn();
  document.addEventListener('keydown',function(e){if(e.key==='Escape')AF_closeLang();});
});

function _updateBtn(){
  var entry=LANGS.find(function(l){return l[0]===curLang;});
  var f=document.getElementById('langFlag');var c=document.getElementById('langCode');
  if(f)f.textContent=entry?entry[1]:'🌐';
  if(c)c.textContent=curLang.toUpperCase();
}

function _buildGrid(list){
  var g=document.getElementById('afLangGrid');if(!g)return;
  g.innerHTML='';
  list.forEach(function(l){
    var b=document.createElement('button');
    b.className='af-lang-opt'+(l[0]===curLang?' active':'');
    b.textContent=l[1]+' '+l[2];
    b.onclick=function(){AF_setLang(l[0]);};
    g.appendChild(b);
  });
}

window.AF_openLang=function(){
  var m=document.getElementById('afLangModal');if(m)m.classList.add('open');
  var s=document.getElementById('afLangSearch');if(s){s.value='';s.focus();}
  _buildGrid(LANGS);
};
window.AF_closeLang=function(){
  var m=document.getElementById('afLangModal');if(m)m.classList.remove('open');
};
window.AF_filterLangs=function(q){
  _buildGrid(q?LANGS.filter(function(l){return l[2].toLowerCase().includes(q.toLowerCase());}):LANGS);
};
window.AF_setLang=function(code){
  localStorage.setItem('af_lang',code);
  AF_closeLang();
  if(code==='en'){
    document.cookie='googtrans=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/';
    document.cookie='googtrans=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/; domain=.'+location.hostname;
    location.reload();
  } else {
    document.cookie='googtrans=/en/'+code+'; path=/';
    location.reload();
  }
};

// Backward-compat aliases (for pages using old openLangModal / filterLangs names)
window.openLangModal=window.AF_openLang;
window.closeLangModal=window.AF_closeLang;
window.filterLangs=window.AF_filterLangs;

})();
