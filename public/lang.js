// Shared language picker + Google Translate — full site translation
(function(){
'use strict';

// All 133 Google Translate supported languages
var LANGS=[
  ['en','🇬🇧','English'],
  ['af','🇿🇦','Afrikaans'],
  ['sq','🇦🇱','Albanian'],
  ['am','🇪🇹','Amharic'],
  ['ar','🇸🇦','Arabic'],
  ['hy','🇦🇲','Armenian'],
  ['as','🇮🇳','Assamese'],
  ['ay','🇧🇴','Aymara'],
  ['az','🇦🇿','Azerbaijani'],
  ['bm','🇲🇱','Bambara'],
  ['eu','🇪🇸','Basque'],
  ['be','🇧🇾','Belarusian'],
  ['bn','🇧🇩','Bengali'],
  ['bho','🇮🇳','Bhojpuri'],
  ['bs','🇧🇦','Bosnian'],
  ['bg','🇧🇬','Bulgarian'],
  ['ca','🇪🇸','Catalan'],
  ['ceb','🇵🇭','Cebuano'],
  ['zh-CN','🇨🇳','Chinese (Simplified)'],
  ['zh-TW','🇹🇼','Chinese (Traditional)'],
  ['co','🇫🇷','Corsican'],
  ['hr','🇭🇷','Croatian'],
  ['cs','🇨🇿','Czech'],
  ['da','🇩🇰','Danish'],
  ['dv','🇲🇻','Dhivehi'],
  ['doi','🇮🇳','Dogri'],
  ['nl','🇳🇱','Dutch'],
  ['eo','🌐','Esperanto'],
  ['et','🇪🇪','Estonian'],
  ['ee','🇬🇭','Ewe'],
  ['tl','🇵🇭','Filipino'],
  ['fi','🇫🇮','Finnish'],
  ['fr','🇫🇷','French'],
  ['fy','🇳🇱','Frisian'],
  ['gl','🇪🇸','Galician'],
  ['ka','🇬🇪','Georgian'],
  ['de','🇩🇪','German'],
  ['el','🇬🇷','Greek'],
  ['gn','🇵🇾','Guarani'],
  ['gu','🇮🇳','Gujarati'],
  ['ht','🇭🇹','Haitian Creole'],
  ['ha','🇳🇬','Hausa'],
  ['haw','🇺🇸','Hawaiian'],
  ['iw','🇮🇱','Hebrew'],
  ['hi','🇮🇳','Hindi'],
  ['hmn','🌏','Hmong'],
  ['hu','🇭🇺','Hungarian'],
  ['is','🇮🇸','Icelandic'],
  ['ig','🇳🇬','Igbo'],
  ['ilo','🇵🇭','Ilocano'],
  ['id','🇮🇩','Indonesian'],
  ['ga','🇮🇪','Irish'],
  ['it','🇮🇹','Italian'],
  ['ja','🇯🇵','Japanese'],
  ['jv','🇮🇩','Javanese'],
  ['kn','🇮🇳','Kannada'],
  ['kk','🇰🇿','Kazakh'],
  ['km','🇰🇭','Khmer'],
  ['rw','🇷🇼','Kinyarwanda'],
  ['gom','🇮🇳','Konkani'],
  ['ko','🇰🇷','Korean'],
  ['kri','🇸🇱','Krio'],
  ['ku','🏳️','Kurdish (Kurmanji)'],
  ['ckb','🏳️','Kurdish (Sorani)'],
  ['ky','🇰🇬','Kyrgyz'],
  ['lo','🇱🇦','Lao'],
  ['la','🏛️','Latin'],
  ['lv','🇱🇻','Latvian'],
  ['ln','🇨🇩','Lingala'],
  ['lt','🇱🇹','Lithuanian'],
  ['lg','🇺🇬','Luganda'],
  ['lb','🇱🇺','Luxembourgish'],
  ['mk','🇲🇰','Macedonian'],
  ['mai','🇮🇳','Maithili'],
  ['mg','🇲🇬','Malagasy'],
  ['ms','🇲🇾','Malay'],
  ['ml','🇮🇳','Malayalam'],
  ['mt','🇲🇹','Maltese'],
  ['mi','🇳🇿','Maori'],
  ['mr','🇮🇳','Marathi'],
  ['mni-Mtei','🇮🇳','Meitei (Manipuri)'],
  ['lus','🇮🇳','Mizo'],
  ['mn','🇲🇳','Mongolian'],
  ['my','🇲🇲','Myanmar (Burmese)'],
  ['ne','🇳🇵','Nepali'],
  ['no','🇳🇴','Norwegian'],
  ['ny','🇲🇼','Nyanja (Chichewa)'],
  ['or','🇮🇳','Odia (Oriya)'],
  ['om','🇪🇹','Oromo'],
  ['ps','🇦🇫','Pashto'],
  ['fa','🇮🇷','Persian'],
  ['pl','🇵🇱','Polish'],
  ['pt','🇵🇹','Portuguese'],
  ['pt-BR','🇧🇷','Portuguese (Brazil)'],
  ['pa','🇮🇳','Punjabi'],
  ['qu','🇵🇪','Quechua'],
  ['ro','🇷🇴','Română'],
  ['ru','🇷🇺','Russian'],
  ['sm','🇼🇸','Samoan'],
  ['sa','🇮🇳','Sanskrit'],
  ['gd','🏴󠁧󠁢󠁳󠁣󠁴󠁿','Scots Gaelic'],
  ['sr','🇷🇸','Serbian'],
  ['st','🇱🇸','Sesotho'],
  ['sn','🇿🇼','Shona'],
  ['sd','🇵🇰','Sindhi'],
  ['si','🇱🇰','Sinhala'],
  ['sk','🇸🇰','Slovak'],
  ['sl','🇸🇮','Slovenian'],
  ['so','🇸🇴','Somali'],
  ['es','🇪🇸','Spanish'],
  ['su','🇮🇩','Sundanese'],
  ['sw','🇰🇪','Swahili'],
  ['sv','🇸🇪','Swedish'],
  ['tg','🇹🇯','Tajik'],
  ['ta','🇮🇳','Tamil'],
  ['tt','🇷🇺','Tatar'],
  ['te','🇮🇳','Telugu'],
  ['th','🇹🇭','Thai'],
  ['ti','🇪🇷','Tigrinya'],
  ['ts','🇿🇦','Tsonga'],
  ['tr','🇹🇷','Turkish'],
  ['tk','🇹🇲','Turkmen'],
  ['ak','🇬🇭','Twi (Akan)'],
  ['uk','🇺🇦','Ukrainian'],
  ['ur','🇵🇰','Urdu'],
  ['ug','🇨🇳','Uyghur'],
  ['uz','🇺🇿','Uzbek'],
  ['vi','🇻🇳','Vietnamese'],
  ['cy','🏴󠁧󠁢󠁷󠁬󠁳󠁿','Welsh'],
  ['xh','🇿🇦','Xhosa'],
  ['yi','🇮🇱','Yiddish'],
  ['yo','🇳🇬','Yoruba'],
  ['zu','🇿🇦','Zulu']
];

var curLang=localStorage.getItem('af_lang')||'en';

// CSS — hide GT banner iframe only; DO NOT hide .skiptranslate (breaks translation)
var _css=document.createElement('style');
_css.textContent=
  'iframe.goog-te-banner-frame,'+
  '.goog-te-banner-frame,'+
  '#goog-gt-tt,'+
  '.goog-te-balloon-frame,'+
  '.goog-te-ftab-float,'+
  '[id^="google_translate_element"],'+
  '.VIpgJd-ZVi9od-aZ2wEe-wOHMyf,'+
  '.VIpgJd-ZVi9od-aZ2wEe{display:none!important}'+
  'body{top:0!important;margin-top:0!important;padding-top:0!important}'+
  '#af-gte{position:absolute;top:-999px;left:-999px;width:1px;height:1px;overflow:hidden}'+
  '.goog-tooltip,.goog-tooltip-input,.goog-te-balloon-frame{display:none!important}'+
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

// Set googtrans cookie (both root path and domain variants for reliability)
function _setCookie(lang){
  var exp='; expires=Thu, 01 Jan 2099 00:00:00 UTC; path=/';
  var val=lang==='en'?'':'/en/'+lang;
  if(!val){exp='; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/';}
  document.cookie='googtrans='+val+exp;
  document.cookie='googtrans='+val+exp.replace('path=/',
    'path=/; domain=.'+location.hostname);
}

// Google Translate init — autoDisplay:true so GT reads cookie and auto-translates
window.googleTranslateElementInit=function(){
  if(typeof google==='undefined'||!google.translate)return;
  new google.translate.TranslateElement({
    pageLanguage:'en',
    autoDisplay:true,
    multilanguagePage:false
  },'af-gte');
};

document.addEventListener('DOMContentLoaded',function(){
  // Ensure cookie matches localStorage on every page load
  if(curLang!=='en') _setCookie(curLang);

  // GT container (off-screen, not display:none — so GT can initialize)
  var gte=document.createElement('div');gte.id='af-gte';
  document.body.appendChild(gte);

  // Load GT script
  var sc=document.createElement('script');
  sc.src='//translate.google.com/translate_a/element.js?cb=googleTranslateElementInit';
  sc.async=true;
  document.body.appendChild(sc);

  // Keep GT banner hidden even after GT dynamically injects it
  var _bannerObs=new MutationObserver(function(){
    var fr=document.querySelector('iframe.goog-te-banner-frame,.goog-te-banner-frame');
    if(fr){fr.style.setProperty('display','none','important');}
    document.body.style.setProperty('top','0','important');
    document.body.style.setProperty('margin-top','0','important');
  });
  _bannerObs.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['style']});

  // Lang picker modal
  var modal=document.createElement('div');
  modal.className='af-lang-modal';modal.id='afLangModal';
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
  if(c)c.textContent=curLang.replace('-CN','').replace('-BR','').toUpperCase();
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
  curLang=code;
  _setCookie(code);
  AF_closeLang();
  _updateBtn();
  // Reload so Google Translate reads the cookie and auto-translates entire page
  location.reload();
};

// Backward-compat aliases
window.openLangModal=window.AF_openLang;
window.closeLangModal=window.AF_closeLang;
window.filterLangs=window.AF_filterLangs;

})();
