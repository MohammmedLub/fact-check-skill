// Shared "Trackers" bar. Included as the first thing in <body> on every tracker page.
(function(){
  var T=[
    {href:'/dashboard/',label:'Job dashboard',lang:'en'},
    {href:'/nl/',label:'Nederlands',lang:'nl'},
    {href:'/fr/',label:'Français',lang:'fr'},
    {href:'/en/',label:'English',lang:'en'},
    {href:'/',label:'Carte de parcours',lang:'fr'}
  ];
  var p=location.pathname.replace(/index\.html$/,'');
  if(p.charAt(p.length-1)!=='/')p+='/';
  var cur=T.filter(function(t){return t.href!=='/'&&p.indexOf(t.href)===0})[0]||(p==='/'?T[4]:null);
  var css='.trk{position:sticky;top:0;z-index:50;background:#1B232B;color:#C9D2D9;font:500 13px/1.2 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;border-bottom:1px solid #000}'
   +'.trk-in{max-width:1180px;margin:0 auto;display:flex;align-items:center;gap:4px;padding:6px 12px;overflow-x:auto;white-space:nowrap;scrollbar-width:none;-webkit-overflow-scrolling:touch}'
   +'.trk-in::-webkit-scrollbar{display:none}'
   +'.trk-lab{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#8C99A4;margin-right:6px;flex:none}'
   +'.trk a{flex:none;color:#E6ECF0;text-decoration:none;padding:6px 10px;border-radius:999px;min-height:18px}'
   +'.trk a:hover{background:#2C3843}'
   +'.trk a:focus-visible{outline:2px solid #8EC5E0;outline-offset:1px}'
   +'.trk a[aria-current="page"]{background:#FFFFFF;color:#17212B;font-weight:700}'
   +'.trk .sep{color:#55626D;flex:none}'
   +'@media print{.trk{display:none}}';
  var st=document.createElement('style');st.textContent=css;
  var nav=document.createElement('nav');nav.className='trk';nav.setAttribute('aria-label','Trackers');
  var html='<div class="trk-in"><span class="trk-lab">Trackers</span>';
  T.forEach(function(t,i){
    if(i)html+='<span class="sep" aria-hidden="true">·</span>';
    // Same browser tab for every tracker: the bar works like the tabs of one site.
    html+='<a href="'+t.href+'" lang="'+t.lang+'"'+(t===cur?' aria-current="page"':'')+'>'+t.label+'</a>';
  });
  nav.innerHTML=html+'</div>';
  var s=document.currentScript;
  if(s&&s.parentNode){s.parentNode.insertBefore(st,s);s.parentNode.insertBefore(nav,s)}
  else{document.head.appendChild(st);document.body.insertBefore(nav,document.body.firstChild)}
})();
