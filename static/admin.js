import {$,esc,fmt,api} from './common.js';

let csrf='', categories=[], products=[], partners=[], orders=[], editing=null, editingPartner=null, auditBefore=null;
let productTimer, orderTimer, saving=false;
const statusNames={draft:'Qaralama',published:'Yayımlanıb',hidden:'Gizli',archived:'Arxiv',submitted:'Sorğu',confirmed:'Təsdiqlənib',cancelled:'Ləğv edilib',pending:'Gözləyir',delivered:'Çatdırılıb',returned:'Geri qaytarılıb',unpaid:'Ödənilməyib',paid:'Ödənilib',refunded:'Pul qaytarılıb'};
const amount=cents=>cents==null?'':(cents/100).toFixed(2);
const call=(path,method='GET',body,form)=>api(path,{method,body,form,csrf});
function notify(message,error=false){$('notice').textContent=message;$('notice').classList.toggle('error',error);$('notice').hidden=false;}
function error(err){notify(err.message,true);if(err.status===401){$('dashboard').hidden=true;$('loginPanel').hidden=false;$('logout').hidden=true;}}
async function guard(fn){try{return await fn();}catch(err){error(err);}}
function clearNotice(){$('notice').hidden=true;}
async function showDashboard(){
  $('loginPanel').hidden=true;$('dashboard').hidden=false;$('logout').hidden=false;
  await loadCategories();await loadProducts();
}
$('loginForm').onsubmit=async e=>{
  e.preventDefault();$('loginButton').disabled=true;
  await guard(async()=>{csrf=(await call('/api/admin/session')).csrf;const r=await call('/api/admin/login','POST',{username:$('username').value,password:$('password').value});csrf=r.csrf;$('password').value='';clearNotice();await showDashboard();});
  $('loginButton').disabled=false;
};
$('logout').onclick=()=>guard(async()=>{await call('/api/admin/logout','POST',{});location.reload();});
document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>guard(async()=>{
  const tab=button.dataset.tab;
  document.querySelectorAll('[id^="tab-"]').forEach(section=>section.hidden=section.id!=='tab-'+tab);
  document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b===button));
  clearNotice();
  if(tab==='products')await loadProducts();
  if(tab==='categories')await loadCategories();
  if(tab==='orders')await loadOrders();
  if(tab==='partners')await loadPartners();
  if(tab==='audit')await loadAudit(true);
}));

async function loadCategories(){
  categories=(await call('/api/admin/categories')).categories;
  for(const id of ['pCategory','productCategory']){
    const prior=$(id).value;
    $(id).innerHTML=`<option value="">${id==='pCategory'?'Kateqoriyasız':'Bütün kateqoriyalar'}</option>`+categories.map(c=>`<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('');
    $(id).value=prior;
  }
  $('categoryList').innerHTML=categories.map(c=>`<form class="card inline" data-category="${esc(c.id)}"><label>Kateqoriya adı<input name="name" value="${esc(c.name)}" required maxlength="100"></label><button>Saxla</button><button type="button" class="danger" data-delete-category="${esc(c.id)}">Sil</button></form>`).join('')||'<p>Hələ kateqoriya yoxdur.</p>';
  document.querySelectorAll('[data-category]').forEach(form=>form.onsubmit=e=>{e.preventDefault();guard(async()=>{await call('/api/admin/categories/'+form.dataset.category,'PUT',{name:form.elements.name.value});await loadCategories();notify('Kateqoriya yeniləndi.');});});
  document.querySelectorAll('[data-delete-category]').forEach(button=>button.onclick=()=>guard(async()=>{await call('/api/admin/categories/'+button.dataset.deleteCategory,'DELETE',{});await loadCategories();notify('İstifadə olunmayan kateqoriya silindi.');}));
}
$('categoryForm').onsubmit=e=>{e.preventDefault();guard(async()=>{await call('/api/admin/categories','POST',{name:$('categoryName').value});$('categoryName').value='';await loadCategories();notify('Kateqoriya əlavə edildi.');});};

async function loadProducts(){
  const params=new URLSearchParams({q:$('productSearch').value,status:$('productStatus').value,category_id:$('productCategory').value});
  products=(await call('/api/admin/products?'+params)).products;
  const available=$('productAvailability').value;
  const list=products.filter(p=>!available || ((p.available && p.variants.some(v=>v.available && v.stock>0)) === (available==='available')));
  $('productList').innerHTML=list.map(p=>`<article class="product-tile">${p.images[0]?`<img src="${esc(p.images[0].thumbnail_url)}" alt="" width="70" height="70" loading="lazy">`:''}<span class="badge">${statusNames[p.status]}</span><h3>${esc(p.name)}</h3><p>${fmt(p.price)} · ${p.variants.reduce((s,v)=>s+v.stock,0)} ədəd</p><p>${p.available?'Sifariş üçün aktiv':'Sifariş üçün bağlı'} · ${esc(categories.find(c=>c.id===p.category_id)?.name||'Kateqoriyasız')}</p><div class="actions"><button data-edit="${esc(p.id)}">Redaktə et</button><button data-status-id="${esc(p.id)}" data-status="${p.status==='published'?'hidden':'published'}">${p.status==='published'?'Gizlət':'Yayımla'}</button>${p.status!=='archived'?`<button data-status-id="${esc(p.id)}" data-status="archived">Arxivlə</button>`:''}</div></article>`).join('')||'<p>Məhsul tapılmadı.</p>';
  document.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>guard(()=>openProduct(b.dataset.edit)));
  document.querySelectorAll('[data-status-id]').forEach(b=>b.onclick=()=>guard(async()=>{
    const p=await call('/api/admin/products/'+b.dataset.statusId), data=productToInput(p);data.status=b.dataset.status;
    await call('/api/admin/products/'+p.id,'PUT',data);
    await loadProducts();if(editing?.id===p.id)await openProduct(p.id,false);
    notify('Məhsul statusu yeniləndi.');
  }));
}
function productToInput(p){
  const data={...p};for(const k of ['price','cost','compare_at'])data[k]=amount(p[k]);
  data.variants=p.variants.map(v=>{const data={...v};for(const k of ['price','cost','compare_at'])data[k]=amount(v[k]);return data;});
  return data;
}
$('productSearch').oninput=()=>{clearTimeout(productTimer);productTimer=setTimeout(()=>guard(loadProducts),250);};
$('importOriginal').onclick=async()=>{
  $('importOriginal').disabled=true;
  await guard(async()=>{const r=await call('/api/admin/import-original','POST',{});await loadCategories();await loadProducts();notify(r.imported?'Orijinal dəsmal və 3 şəkil idxal edildi. Real stok və maya dəyərini yazıb sifarişi aktiv edin.':'Orijinal dəsmal artıq mövcuddur; məlumat dəyişməyib.');});
  $('importOriginal').disabled=false;
};
for(const id of ['productStatus','productCategory','productAvailability'])$(id).onchange=()=>guard(loadProducts);
function variantRow(v={size:'',colour:'',price:'',cost:'',compare_at:'',stock:0,available:true}){
  const row=document.createElement('div');row.className='variant';if(v.id)row.dataset.id=v.id;
  row.innerHTML=`<div class="form-grid"><label>Ölçü<input name="size" value="${esc(v.size)}" maxlength="80" placeholder="Standart və ya 50×60 sm"></label><label>Rəng<input name="colour" value="${esc(v.colour)}" maxlength="80" placeholder="Boz"></label><label>Stok (ədəd)<input name="stock" type="number" value="${v.stock}" min="0" max="1000000" step="1" required></label><label>Variant qiyməti (AZN)<input name="price" type="number" value="${esc(v.price)}" min="0.01" max="1000000" step="0.01" placeholder="Əsas qiymət"></label><label>Variant maya dəyəri (AZN)<input name="cost" type="number" value="${esc(v.cost)}" min="0" max="1000000" step="0.01" placeholder="Əsas maya dəyəri"></label><label>Variant əvvəlki qiyməti (AZN)<input name="compare_at" type="number" value="${esc(v.compare_at)}" min="0.01" max="1000000" step="0.01" placeholder="Əsas əvvəlki qiymət"></label><label class="check"><input name="available" type="checkbox" ${v.available?'checked':''}>Variant aktivdir</label></div><button type="button" class="danger">Variantı sil</button>`;
  row.querySelector('button').onclick=()=>{if($('variantList').children.length<=1){notify('Ən azı bir variant saxlayın.',true);return;}row.remove();};
  $('variantList').append(row);
}
function fillEditor(p){
  editing=p;const data=p?productToInput(p):null;
  $('productEditor').hidden=false;$('editorTitle').textContent=p?'Məhsulu redaktə et':'Yeni məhsul';
  $('pName').value=data?.name||'';$('pDescription').value=data?.description||'';
  $('pPrice').value=data?.price||'';$('pCost').value=data?.cost||'';$('pCompare').value=data?.compare_at||'';
  $('pCategory').value=data?.category_id||'';$('pStatus').value=data?.status||'draft';$('pAvailable').checked=data?data.available:true;
  $('variantList').innerHTML='';(data?.variants||[{}]).forEach(v=>variantRow({...{size:'',colour:'',stock:0,available:true},...v}));
  $('photosPanel').hidden=!p;$('duplicateProduct').hidden=!p;$('bundleHelp').hidden=!p?.legacy_towel;
  if(p)renderPhotos();
}
async function openProduct(id,scroll=true){const p=await call('/api/admin/products/'+id);fillEditor(p);if(scroll)$('productEditor').scrollIntoView({behavior:'smooth',block:'start'});}
$('newProduct').onclick=()=>{fillEditor(null);clearNotice();$('productEditor').scrollIntoView({behavior:'smooth'});$('pName').focus();};
$('closeEditor').onclick=()=>{$('productEditor').hidden=true;editing=null;};
$('addVariant').onclick=()=>variantRow();
function readEditor(){
  return {version:editing?.version,name:$('pName').value,description:$('pDescription').value,price:$('pPrice').value,cost:$('pCost').value,compare_at:$('pCompare').value,
    category_id:$('pCategory').value||null,status:$('pStatus').value,available:$('pAvailable').checked,
    variants:[...$('variantList').children].map(row=>{const value=name=>row.querySelector(`[name="${name}"]`).value;return {...(row.dataset.id?{id:row.dataset.id}:{}),size:value('size'),colour:value('colour'),price:value('price'),cost:value('cost'),compare_at:value('compare_at'),stock:Number(value('stock')),available:row.querySelector('[name=available]').checked};})};
}
async function saveEditor(){
  if(!$('productForm').reportValidity()||saving)return null;
  saving=true;$('saveProduct').disabled=true;$('previewProduct').disabled=true;
  try{
    const p=await call('/api/admin/products'+(editing?'/'+editing.id:''),editing?'PUT':'POST',readEditor());
    fillEditor(p);await loadProducts();notify('Məhsul saxlanıldı. Şəkilləri aşağıda yükləyə bilərsiniz.');return p;
  }finally{saving=false;$('saveProduct').disabled=false;$('previewProduct').disabled=false;}
}
$('productForm').onsubmit=e=>{e.preventDefault();guard(saveEditor);};
$('previewProduct').onclick=()=>guard(async()=>{const p=await saveEditor();if(p){const a=document.createElement('a');a.href='/?preview='+encodeURIComponent(p.id);a.target='_blank';a.rel='noopener';a.click();}});
$('duplicateProduct').onclick=()=>guard(async()=>{if(!editing)return;const p=await call('/api/admin/products/'+editing.id+'/duplicate','POST',{version:editing.version});fillEditor(p);await loadProducts();notify('Qaralama surət yaradıldı. Fiziki stok təkrarlanmaması üçün say sıfırdır.');});
function renderPhotos(){
  $('photoList').innerHTML=editing.images.map((im,i)=>`<div class="photo"><img src="${esc(im.thumbnail_url)}" alt="Şəkil ${i+1}" width="100" height="100"><small>${i===0?'Üz qabığı':'Şəkil '+(i+1)}</small><button type="button" class="danger" data-remove-image="${esc(im.id)}">Sil</button></div>`).join('')||'<p>Hələ şəkil yoxdur.</p>';
  document.querySelectorAll('[data-remove-image]').forEach(b=>b.onclick=()=>guard(async()=>{await call('/api/admin/products/'+editing.id+'/images/'+b.dataset.removeImage,'DELETE',{version:editing.version});await openProduct(editing.id,false);await loadProducts();notify('Şəkil məhsuldan çıxarıldı.');}));
}
async function uploadFile(file){
  if(!['image/jpeg','image/png','image/webp'].includes(file.type))throw new Error('JPG, PNG və ya WebP şəkli seçin.');
  if(file.size>20*1024*1024)throw new Error('Şəkil çox böyükdür (ən çox 20 MB).');
  // Vercel functions have a small request limit. Resize locally, then the
  // backend independently decodes, validates, and re-encodes the uploaded bytes.
  const bitmap=await createImageBitmap(file);
  try{
    if(bitmap.width*bitmap.height>24000000)throw new Error('Şəkil ən çox 24 MP ola bilər.');
    const scale=Math.min(1,1600/Math.max(bitmap.width,bitmap.height));
    const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(bitmap.width*scale));canvas.height=Math.max(1,Math.round(bitmap.height*scale));
    const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(bitmap,0,0,canvas.width,canvas.height);
    const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/webp',.84));
    if(!blob||blob.size>3.5*1024*1024)throw new Error('Şəkli kiçildib yenidən seçin.');
    return new File([blob],'product.webp',{type:'image/webp'});
  }finally{bitmap.close();}
}
$('photoForm').onsubmit=async e=>{
  e.preventDefault();if(!editing)return;$('uploadPhotos').disabled=true;
  await guard(async()=>{
    const files=[...$('photoFiles').files];
    if(editing.images.length+files.length>10)throw new Error('Məhsulda ən çox 10 şəkil ola bilər.');
    for(let i=0;i<files.length;i++){
      $('uploadPhotos').textContent=`Yüklənir ${i+1} / ${files.length}…`;
      const form=new FormData();form.append('images',await uploadFile(files[i]));form.append('version',editing.version);
      editing=await call('/api/admin/products/'+editing.id+'/images','POST',undefined,form);renderPhotos();
    }
    fillEditor(editing);$('photoFiles').value='';await loadProducts();notify('Şəkillər yükləndi və optimallaşdırıldı.');
  });
  $('uploadPhotos').textContent='Şəkilləri yüklə';
  $('uploadPhotos').disabled=false;
};

async function loadOrders(){
  const query=new URLSearchParams({q:$('orderSearch').value,status:$('orderStatus').value});
  orders=(await call('/api/admin/orders?'+query)).orders;
  $('orderList').innerHTML=orders.map(o=>{
    const earned=o.ledger.filter(l=>l.kind!=='payout').reduce((s,l)=>s+l.amount,0), paid=-o.ledger.filter(l=>l.kind==='payout').reduce((s,l)=>s+l.amount,0);
    const actions=[];
    if(o.sale_status==='submitted')actions.push(['confirm','Satışı təsdiqlə (stok çıxılır)']);
    if(['submitted','confirmed'].includes(o.sale_status)&&o.fulfillment==='pending'&&o.payment!=='paid')actions.push(['cancel','Ləğv et']);
    if(o.sale_status==='confirmed'&&o.fulfillment==='pending')actions.push(['deliver','Çatdırıldı']);
    if(o.sale_status==='confirmed'&&o.payment==='unpaid')actions.push(['mark_paid','Ödəniş alındı']);
    if(o.payment==='paid')actions.push(['refund','Pul geri qaytarıldı']);
    if(o.fulfillment==='delivered')actions.push(['return','Məhsul geri alındı (stok artır)']);
    if(o.partner_id && earned>paid)actions.push(['pay_commission','Komissiya ödənişini qeydə al']);
    if(o.partner_id)actions.push(['eligibility',o.eligible?'Komissiyaya uyğunluğu ləğv et':'Komissiyaya uyğun say']);
    return `<details class="card order" id="order-${esc(o.id)}"><summary><span>${esc(o.reference)} · ${esc(o.customer_name)}</span><span class="badge">${statusNames[o.sale_status]} · ${statusNames[o.fulfillment]} · ${statusNames[o.payment]}</span><span>${fmt(o.total)}</span></summary><div class="order-body"><div class="facts"><p><b>Telefon</b>${esc(o.phone)}</p><p><b>Ünvan / təhvil nöqtəsi</b>${esc(o.address)}</p><p><b>Qeyd</b>${esc(o.note||'—')}</p><p><b>Yaradılıb (UTC)</b>${esc(o.created_at)}</p><p><b>Referal</b>${esc(o.referral_submitted||'Yoxdur')} · ${o.partner_id?'Yoxlanılıb: '+esc(o.partner_name):'Təsdiqlənməyib / yoxdur'}</p><p><b>Uyğunluq</b>${o.eligible?'Uyğundur (digər şərtlər də ödənməlidir)':'Uyğun deyil'}</p></div><ul class="order-items">${o.items.map(i=>`<li>${esc(i.product_name)} / ${esc(i.variant_name)} × ${i.quantity} — ${fmt(i.unit_price)} / ədəd · endirim ${fmt(i.discount)} · yekun ${fmt(i.line_total)}</li>`).join('')}</ul><p>Məhsullar ${fmt(o.subtotal)} − endirim ${fmt(o.discount)} + çatdırılma ${fmt(o.delivery_fee)} = <b>${fmt(o.total)}</b></p><p>Sabit komissiya (sorğu anında): ${fmt(o.commission_snapshot)} · Qazanılıb: ${fmt(earned)} · Ödənilib: ${fmt(paid)} · Qalıq: ${fmt(earned-paid)}</p>${earned-paid<0?'<p class="danger">Geri qaytarma sonrası mənfi qalıq var. Partnyorla hesablaşma tələb olunur.</p>':''}<label class="reason">Əməliyyatın səbəbi / qəbz istinadı<input data-reason="${esc(o.id)}" minlength="3" maxlength="500" placeholder="Məs: Müştəri WhatsApp-da təsdiqlədi"></label><div class="order-actions">${actions.map(([action,label])=>`<button type="button" data-order="${esc(o.id)}" data-action="${action}">${label}</button>`).join('')}</div><details><summary>Komissiya jurnalı</summary><pre>${esc(JSON.stringify(o.ledger,null,2))}</pre></details></div></details>`;
  }).join('')||'<p>Sifariş sorğusu tapılmadı.</p>';
  document.querySelectorAll('[data-order]').forEach(b=>b.onclick=()=>guard(async()=>{
    const o=orders.find(o=>o.id===b.dataset.order), reason=document.querySelector(`[data-reason="${o.id}"]`).value;
    if(reason.trim().length<3){notify('Əməliyyat üçün səbəb və ya qəbz istinadı yazın.',true);return;}
    b.disabled=true;
    try{await call('/api/admin/orders/'+o.id+'/events','POST',{action:b.dataset.action,reason,version:o.version,...(b.dataset.action==='eligibility'?{eligible:!o.eligible}:{})});await loadOrders();const detail=$('order-'+o.id);if(detail)detail.open=true;notify('Əməliyyat qeydə alındı.');}finally{b.disabled=false;}
  }));
}
$('refreshOrders').onclick=()=>guard(loadOrders);$('orderStatus').onchange=()=>guard(loadOrders);
$('orderSearch').oninput=()=>{clearTimeout(orderTimer);orderTimer=setTimeout(()=>guard(loadOrders),250);};

function resetPartner(){editingPartner=null;$('partnerTitle').textContent='Yeni partnyor';$('partnerForm').reset();$('partnerActive').checked=true;}
$('resetPartner').onclick=resetPartner;
async function loadPartners(){
  partners=(await call('/api/admin/partners')).partners;
  $('partnerList').innerHTML=partners.map(p=>`<article class="card partner"><span class="badge">${p.active?'Aktiv':'Bağlı'}</span><h3>${esc(p.name)}</h3><p><b>${esc(p.code)}</b> · ${fmt(p.commission)} / uyğun sifariş<br>Komissiya qalığı: ${fmt(p.balance)}</p><a href="${esc(p.referral_url)}" target="_blank" rel="noopener">${esc(p.referral_url)}</a><img src="/api/admin/partners/${esc(p.id)}/qr.svg" alt="${esc(p.code)} üçün referal QR" width="170" height="170"><div class="actions"><a href="/api/admin/partners/${esc(p.id)}/qr.svg" download="${esc(p.code)}.svg">QR yüklə</a><button data-edit-partner="${esc(p.id)}">Redaktə et</button></div></article>`).join('')||'<p>Hələ partnyor yoxdur.</p>';
  document.querySelectorAll('[data-edit-partner]').forEach(b=>b.onclick=()=>{editingPartner=partners.find(p=>p.id===b.dataset.editPartner);const p=editingPartner;$('partnerTitle').textContent='Partnyoru redaktə et';$('partnerName').value=p.name;$('partnerCode').value=p.code;$('partnerCommission').value=amount(p.commission);$('partnerActive').checked=p.active;$('partnerForm').scrollIntoView({behavior:'smooth'});});
}
$('partnerForm').onsubmit=e=>{e.preventDefault();guard(async()=>{await call('/api/admin/partners'+(editingPartner?'/'+editingPartner.id:''),editingPartner?'PUT':'POST',{name:$('partnerName').value,code:$('partnerCode').value,commission:$('partnerCommission').value,active:$('partnerActive').checked,version:editingPartner?.version});resetPartner();await loadPartners();notify('Partnyor saxlanıldı. Mövcud sifarişlərin komissiyası dəyişməyib.');});};

async function loadAudit(reset=false){
  if(reset){auditBefore=null;$('auditList').innerHTML='';}
  const r=await call('/api/admin/audit'+(auditBefore?'?before='+auditBefore:''));
  for(const e of r.events){const node=document.createElement('details');node.className='card';node.innerHTML=`<summary>#${e.sequence} · ${esc(e.created_at)} · ${esc(e.actor)} · ${esc(e.entity_type)} / ${esc(e.action)}</summary><pre>${esc(JSON.stringify({...e,detail:JSON.parse(e.detail)},null,2))}</pre>`;$('auditList').append(node);}
  if(r.events.length)auditBefore=r.events[r.events.length-1].sequence;
  $('moreAudit').hidden=r.events.length<100;
}
$('refreshAudit').onclick=()=>guard(()=>loadAudit(true));$('moreAudit').onclick=()=>guard(()=>loadAudit());
guard(async()=>{const r=await call('/api/admin/session');csrf=r.csrf;if(r.authenticated)await showDashboard();else $('loginPanel').hidden=false;});
