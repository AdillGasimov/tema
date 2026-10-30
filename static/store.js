import {$, esc, fmt, api} from './common.js';
import {REVIEWS} from './reviews.js';

let products=[], categories=[], settings={delivery_fee:399}, current=null, variant=null, quantity=1, delivery='metro', cart=[];
let preview=false, pending=null, submitted=false, busy=false, referralTimer;
const search = new URLSearchParams(location.search);
const canBuy = (p,v,q=1) => !!(p && p.available && v && v.available && v.stock >= q);
const variantLabel = v => [v.size,v.colour].filter(Boolean).join(' / ') || 'Standart';
function line(p,v,q) {
  const percent=p.legacy_towel ? (q>=3?15:q===2?10:0) : 0;
  const subtotal=v.effective_price*q, discount=Math.floor((subtotal*percent+50)/100);
  return {p,v,q,subtotal,discount,total:subtotal-discount};
}
function chosenLines() {
  if (!cart.length) return current && variant ? [line(current,variant,quantity)] : [];
  return cart.map(i=>{
    const p=products.find(p=>p.id===i.product_id), v=p?.variants.find(v=>v.id===i.variant_id);
    return p && v ? line(p,v,i.quantity) : null;
  }).filter(Boolean);
}
function totals() {
  const lines=chosenLines(), subtotal=lines.reduce((s,l)=>s+l.subtotal,0), discount=lines.reduce((s,l)=>s+l.discount,0), fee=delivery==='metro'?0:settings.delivery_fee;
  return {lines,subtotal,discount,fee,total:subtotal-discount+fee};
}
function showError(message) { $('ferr').textContent=message; $('ferr').hidden=false; }
function toast(message) { $('toastMsg').textContent=message; $('toast').classList.add('show'); setTimeout(()=>$('toast').classList.remove('show'),2500); }

function renderCatalog() {
  const q=$('catalogSearch').value.toLocaleLowerCase('az'), c=$('catalogCategory').value;
  const list=products.filter(p=>(!c||p.category_id===c)&&`${p.name} ${p.description}`.toLocaleLowerCase('az').includes(q));
  $('productGrid').innerHTML=list.map(p=>{
    const prices=p.variants.map(v=>v.effective_price), price=prices.length?Math.min(...prices):p.price;
    const image=p.images[0];
    return `<button type="button" class="product-card" data-product="${esc(p.id)}" aria-pressed="${p.id===current?.id}">${image?`<img src="${esc(image.thumbnail_url)}" alt="${esc(p.name)}" loading="lazy" width="480" height="480">`:''}<b>${esc(p.name)}</b><span>${fmt(price)}${new Set(prices).size>1?' – başlayaraq':''}</span><small>${p.variants.some(v=>canBuy(p,v))?'Sifariş mümkündür':'Hazırda mövcud deyil'}</small></button>`;
  }).join('');
  $('catalogStatus').textContent=list.length?`${list.length} məhsul`:'Məhsul tapılmadı.';
  document.querySelectorAll('[data-product]').forEach(b=>b.onclick=()=>selectProduct(b.dataset.product,true));
}
function gallery() {
  $('gTrack').innerHTML=current.images.map((im,i)=>{
    const smallWidth=Math.round(im.width*Math.min(1,480/Math.max(im.width,im.height)));
    const srcset=smallWidth<im.width?`srcset="${esc(im.thumbnail_url)} ${smallWidth}w, ${esc(im.url)} ${im.width}w" sizes="(min-width:900px) 500px, 95vw"`:'';
    return `<figure class="g-slide"><img src="${esc(im.url)}" ${srcset} alt="${esc(current.name)} — ${i+1}" width="${im.width}" height="${im.height}" ${i?'loading="lazy"':'fetchpriority="high"'}></figure>`;
  }).join('');
  $('gThumbs').innerHTML=current.images.map((im,i)=>`<button type="button" aria-label="Şəkil ${i+1}" data-image="${i}"><img src="${esc(im.thumbnail_url)}" alt="" width="66" height="66" loading="lazy"></button>`).join('');
  document.querySelectorAll('[data-image]').forEach(b=>b.onclick=()=>$('gTrack').scrollTo({left:Number(b.dataset.image)*$('gTrack').clientWidth,behavior:'smooth'}));
  $('gTrack').scrollLeft=0;
  syncGallery();
  document.querySelectorAll('img[data-c]').forEach(im=>{const image=current.images[Math.min(Number(im.dataset.c),current.images.length-1)]; if(image) im.src=image.url;});
}
function syncGallery() {
  const i=Math.round($('gTrack').scrollLeft/($('gTrack').clientWidth||1));
  $('gCount').textContent=current?.images.length?`${i+1} / ${current.images.length}`:'0 / 0';
  document.querySelectorAll('[data-image]').forEach((b,n)=>b.classList.toggle('on',i===n));
}
function selectProduct(id, scroll=false) {
  current=products.find(p=>p.id===id) || products[0];
  if (!current) return;
  variant=current.variants.find(v=>canBuy(current,v)) || current.variants[0];
  quantity=1;
  $('productHero').hidden=false;
  $('sticky').hidden=preview;
  $('productName').textContent=current.name;
  $('productDescription').textContent=current.description;
  $('productCategory').textContent=categories.find(c=>c.id===current.category_id)?.name || 'Mikrofiber.shop';
  document.querySelectorAll('.towel-only').forEach(e=>e.hidden=!current.legacy_towel);
  gallery(); renderChoices(); update(); renderCatalog();
  if(!preview) {
    const url=new URL(location.href);url.searchParams.set('product',current.id);history.replaceState(null,'',url);
  }
  if(scroll) $('productHero').scrollIntoView({behavior:'smooth',block:'start'});
}
function renderChoices() {
  $('sizes').innerHTML=current.variants.map(v=>`<label class="sz ${v.id===variant?.id?'on':''}"><input class="rin" type="radio" name="size" value="${esc(v.id)}" ${v.id===variant?.id?'checked':''}><b>${esc(variantLabel(v))}</b><span>${fmt(v.effective_price)} · ${v.stock} ədəd</span></label>`).join('');
  document.querySelectorAll('[name=size]').forEach(e=>e.onchange=()=>{variant=current.variants.find(v=>v.id===e.value);renderChoices();update();});
  $('bund').innerHTML=[1,2,3].map(q=>{
    const l=line(current,variant,q), available=canBuy(current,variant,q);
    return `<label class="bd ${q===quantity?'on':''}"><input class="rin" type="radio" name="bundle" value="${q}" ${q===quantity?'checked':''}><span class="rad"></span><span><span class="bt">${q} ədəd ${l.discount?`<span class="chip">Əlavə -${q===2?10:15}%</span>`:''}</span><span class="bn">${available?'':'Hazırda bu sayda mövcud deyil'}</span></span><span class="bp"><b>${fmt(l.total)}</b>${l.discount?`<s>${fmt(l.subtotal)}</s>`:''}<small>${q>1?'hər biri '+fmt(Math.round(l.total/q)):''}</small></span></label>`;
  }).join('');
  document.querySelectorAll('[name=bundle]').forEach(e=>e.onchange=()=>{quantity=Number(e.value);renderChoices();update();});
}
function update() {
  if(!current || !variant) return;
  const now=variant.effective_price, old=variant.effective_compare_at, onSale=old>now;
  $('pNow').textContent=fmt(now);
  $('pOld').textContent=old?fmt(old):'';
  $('pOld').hidden=!onSale;
  const discount=onSale?'-'+Math.round((1-now/old)*100)+'%':'';
  for(const id of ['pOff','gBadge']) { $(id).textContent=discount;$(id).hidden=!onSale; }
  $('availability').textContent=canBuy(current,variant)?`Stokda ${variant.stock} ədəd · ${variantLabel(variant)}`:'Bu variant hazırda sifariş üçün mövcud deyil.';
  const t=totals();
  $('sum').innerHTML=t.lines.map(l=>`<div class="sr"><span>${esc(l.p.name)} — ${esc(variantLabel(l.v))} × ${l.q}</span><span>${fmt(l.subtotal)}</span></div>`).join('')+`${t.discount?`<div class="sr d"><span>Paket endirimi</span><span>−${fmt(t.discount)}</span></div>`:''}<div class="sr d"><span>${delivery==='metro'?'🚇 28 May metrosu':'📍 Ünvana kuryer'}</span><span>${fmt(t.fee)}</span></div><div class="sr t"><span>Cəmi</span><span>${fmt(t.total)}</span></div>`;
  const ready=t.lines.length>0 && t.lines.every(l=>canBuy(l.p,l.v,l.q));
  $('submitBtn').disabled=preview||!ready||busy||submitted;
  $('addCart').disabled=preview||!canBuy(current,variant,quantity)||busy||submitted;
  $('sd').textContent=cart.length?`Səbətdə ${t.lines.reduce((s,l)=>s+l.q,0)} ədəd`:`${quantity} ədəd, ${variantLabel(variant)}`;
  $('stt').textContent=fmt(t.total);
  $('cartPanel').hidden=!cart.length;
  $('cartItems').innerHTML=t.lines.filter(()=>cart.length).map(l=>`<div class="cart-row"><span>${esc(l.p.name)} — ${esc(variantLabel(l.v))} × ${l.q}<br>${fmt(l.total)}</span><button type="button" data-remove="${esc(l.v.id)}" aria-label="Səbətdən sil">Sil</button></div>`).join('');
  document.querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{cart=cart.filter(i=>i.variant_id!==b.dataset.remove);update();});
}
function setDelivery(metro) {
  delivery=metro?'metro':'courier';
  $('dMetro').classList.toggle('on',metro);$('dAddr').classList.toggle('on',!metro);
  $('addrLabel').textContent=metro?'Təhvil nöqtəsi / Metro çıxışı 🚇':'Dəqiq çatdırılma ünvanı 📍';
  $('inAddr').placeholder=metro?'28 May metrosu çıxışı (məs: Cəfər Cabbarlı heykəli yanı)':'Şəhər, küçə, bina/ev/mənzil';
  update();
}
$('dMetro').onclick=()=>setDelivery(true);$('dAddr').onclick=()=>setDelivery(false);
$('gTrack').addEventListener('scroll',syncGallery,{passive:true});
$('catalogSearch').oninput=renderCatalog;$('catalogCategory').onchange=renderCatalog;
$('clearCart').onclick=()=>{cart=[];update();};
$('addCart').onclick=()=>{
  const prior=cart.find(i=>i.variant_id===variant.id), q=(prior?.quantity||0)+quantity;
  if(q>99 || !canBuy(current,variant,q)) {showError('Səbətdəki ümumi say üçün kifayət qədər stok yoxdur.');return;}
  if(prior) prior.quantity=q; else cart.push({product_id:current.id,variant_id:variant.id,quantity});
  $('ferr').hidden=true; update(); toast('Məhsul səbətə əlavə edildi. Sifariş səbətdəki məhsulları əhatə edəcək.');
};

async function checkReferral() {
  const code=$('inReferral').value.trim().toUpperCase();
  if(!code){$('referralStatus').textContent='';try{localStorage.removeItem('mf_referral');}catch{}return;}
  try {
    const r=await api('/api/referrals/'+encodeURIComponent(code));
    if($('inReferral').value.trim().toUpperCase()!==code)return;
    $('referralStatus').textContent=r.verified?'Referal kodu yoxlanılıb.':'Kod təsdiqlənməyib; komissiya hesablanmayacaq.';
    try{if(r.verified)localStorage.setItem('mf_referral',JSON.stringify({code:r.code,expires:Date.now()+30*86400000}));else localStorage.removeItem('mf_referral');}catch{}
  } catch { $('referralStatus').textContent='Kod yoxlanılmadı. Server sifariş zamanı yenidən yoxlayacaq.'; }
}
$('inReferral').oninput=()=>{clearTimeout(referralTimer);referralTimer=setTimeout(checkReferral,400);};
function initReferral() {
  let code=search.get('ref')||'';
  if(!code)try {const saved=JSON.parse(localStorage.getItem('mf_referral')||'null');if(saved?.expires>Date.now())code=saved.code;}catch{}
  $('inReferral').value=code.slice(0,40);checkReferral();
}

function validate() {
  const checks={fName:$('inName').value.trim().length>=3,
    fPhone:/^(?:994|0)?(10|50|51|55|60|70|77|99)\d{7}$/.test($('inPhone').value.replace(/[\s()+-]/g,'')),fAddr:$('inAddr').value.trim().length>=3};
  for(const [id,ok] of Object.entries(checks)) $(id).classList.toggle('bad',!ok);
  const bad=Object.keys(checks).find(k=>!checks[k]);
  if(bad) {showError('Adı, mobil nömrəni və təhvil yerini düzgün daxil edin.');$(bad).querySelector('input').focus();}
  return !bad;
}
$('sifaris').addEventListener('submit',async e=>{
  e.preventDefault();
  if(preview||busy||submitted||!validate())return;
  const t=totals();
  if(!t.lines.length || !t.lines.every(l=>canBuy(l.p,l.v,l.q)))return;
  const data={customer:{name:$('inName').value.trim(),phone:$('inPhone').value.trim(),address:$('inAddr').value.trim(),note:$('inNote').value.trim()},
    items:t.lines.map(l=>({product_id:l.p.id,variant_id:l.v.id,quantity:l.q})),delivery,expected_total:t.total,referral_code:$('inReferral').value.trim().toUpperCase()};
  const signature=JSON.stringify(data);
  busy=true;$('ferr').hidden=true;update();$('submitBtn').textContent='Sorğu saxlanılır…';
  try {
    if(!pending || pending.signature!==signature) {
      const digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(signature)))].map(b=>b.toString(16).padStart(2,'0')).join('');
      let key=crypto.randomUUID();
      try{const prior=JSON.parse(sessionStorage.getItem('mf_order_retry')||'null');if(prior?.digest===digest)key=prior.key;sessionStorage.setItem('mf_order_retry',JSON.stringify({digest,key}));}catch{}
      pending={signature,payload:{...data,idempotency_key:key}};
    }
    const r=await api('/api/orders',{method:'POST',body:pending.payload});
    submitted=true;
    $('orderRef').textContent=r.reference;
    $('waLink').href=r.whatsapp_url;$('waLink').textContent='WhatsApp-da açın';$('done').hidden=false;
    $('copyMsg').onclick=async ev=>{ev.preventDefault();try{await navigator.clipboard.writeText(r.message);toast('Mesaj kopyalandı.');}catch{toast('Kopyalamaq alınmadı. WhatsApp keçidindən istifadə edin.');}};
    if(!document.getElementById('newRequest')) {
      const b=document.createElement('button');b.type='button';b.id='newRequest';b.className='minor';b.textContent='Yeni sifariş sorğusu';
      b.onclick=()=>{submitted=false;pending=null;try{sessionStorage.removeItem('mf_order_retry');}catch{}$('done').hidden=true;b.remove();update();};$('done').after(b);
    }
    // Only open the external service after the backend has committed the request.
    // If the browser blocks this asynchronous popup, the saved-request link remains usable.
    try{window.open(r.whatsapp_url,'_blank','noopener,noreferrer');}catch{}
  } catch(error) {
    showError(error.message+(error.status===409?' Məbləğ və mövcudluğu yeniləmək üçün səhifəni yeniləyin.':''));
  } finally {busy=false;$('submitBtn').textContent=submitted?'Sorğu saxlanıldı':'📲 WhatsApp ilə sifariş et';update();}
});

new IntersectionObserver(([x])=>$('sticky').classList.toggle('hide',x.isIntersecting),{threshold:.15}).observe($('sifaris'));
$('sbtn').onclick=e=>{e.preventDefault();$('sifaris').scrollIntoView({behavior:'smooth',block:'start'});};
$('rvg').innerHTML=REVIEWS.map(r=>`<article class="rv"><div class="rt"><span class="av">${esc(r[0][0])}</span><div><span class="rn">${esc(r[0])}</span><span class="rc">${esc(r[1])}</span></div></div><span class="st">★★★★★</span><p>${esc(r[3])}</p><span class="rm">Aldığı: ${esc(r[2])}</span></article>`).join('');
$('promoText').textContent='💵 Ödəniş qapıda · 🚇 28 May metrosunda pulsuz təhvil';
async function load() {
  try {
    const data=await api('/api/catalog');products=data.products;categories=data.categories;settings=data.settings;
    const previewId=search.get('preview');
    if(previewId){const p=await api('/api/admin/products/'+encodeURIComponent(previewId)+'/preview');products=[p];preview=true;$('previewBanner').hidden=false;$('catalog').hidden=true;}
    $('catalogCategory').innerHTML='<option value="">Bütün kateqoriyalar</option>'+categories.map(c=>`<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('');
    $('courierPrice').textContent='+'+fmt(settings.delivery_fee);
    $('deliveryInfo').textContent=`28 May metrosunda təhvil ödənişsizdir, ünvana çatdırılma +${fmt(settings.delivery_fee)}-dir. Ödənişi məhsulu təhvil alanda, qapıda edirsiniz.`;
    document.querySelectorAll('a.call, a[href^="https://wa.me/"]').forEach(a=>a.href='https://wa.me/'+settings.whatsapp_number);
    selectProduct(search.get('product'));renderCatalog();setDelivery(true);initReferral();
    if(!products.length){$('catalogStatus').textContent='Hazırda yayımlanmış məhsul yoxdur. WhatsApp-da bizə yazın.';$('productHero').hidden=true;document.querySelectorAll('.towel-only').forEach(e=>e.hidden=true);}
  }catch(error){$('catalogStatus').textContent='Kataloq yüklənmədi: '+error.message;$('productHero').hidden=true;$('sticky').hidden=true;}
}
load();
