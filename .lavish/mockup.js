/* Isolated visual prototype. All state is in memory; no API or credential calls. */
const paths = {
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  play: '<path d="m8 5 11 7-11 7Z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M15 8V4H4v11h4"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  clock: '<circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/>',
  shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z"/><path d="m8 12 3 3 5-6"/>',
  lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
  globe: '<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/>',
  users: '<circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2M16 5a3 3 0 0 1 0 6m2 3a5 5 0 0 1 3 5"/>',
  refresh: '<path d="M20 10a8 8 0 1 0-2 8M20 4v6h-6"/>',
  settings: '<path d="M4 7h16M4 17h16"/><circle cx="8" cy="7" r="2.5" fill="currentColor"/><circle cx="16" cy="17" r="2.5" fill="currentColor"/>',
  box: '<path d="m12 3 9 5-9 5-9-5 9-5Zm-9 5v10l9 5 9-5V8M12 13v10M7 5.8l9 5"/>',
  leaf: '<path d="M20 3C7 3 3 8 5 15s14 7 15-12ZM5 20 16 9"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  mountain: '<path d="m2 20 7-14 5 9 3-6 5 11ZM7 10l2 2 2-2"/>',
  logout: '<path d="M9 4H4v16h5m5-13 5 5-5 5m-5-5h10"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 6 9 7 9-7"/>',
};
const icon = (name) => `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.box}</svg>`;
const escapeHTML = (text) => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const brand = () => `<span class="brand"><svg class="brand-mark" viewBox="0 0 30 34" fill="none" aria-hidden="true"><path d="m15 1 14 8v16l-14 8L1 25V9Z" fill="#283b20"/><path d="m15 1 14 8-14 8L1 9Z" fill="#b4e88b"/><path d="m1 9 14 8v16L1 25Z" fill="#729955"/><path d="m15 17 14-8v16l-14 8Z" fill="#425d32"/><path d="m8 5 14 8M8 13v16" stroke="#172210" stroke-opacity=".4"/></svg><span data-lavish-revision="r1">MC<span class="brand-word">WorldControl</span></span></span>`;
const statusText = (s) => ({stopped:'Stopped', ready:'Ready to join', starting:'Starting server', minecraft:'Starting Minecraft', stopping:'Stopping'})[s.state];
const statusClass = s => s.state === 'ready' ? 'ready' : s.state === 'stopped' ? 'stopped' : 'starting';
let currentView = 'landing';
let signedIn = false;
let filter = 'all';
let selectedServer = null;
let settingsTab = 'general';
let toastTimer;
let servers = [
  { id:'sunday', name:'Sunday survival', role:'owner', state:'stopped', players:0, max:20, version:'1.21.4', address:'203.0.113.24:25565', access:'whitelist', names:'Steve\nAlex', admins:['alex@example.com'], draftNames:null },
  { id:'weekend', name:'The long weekend', role:'admin', state:'ready', players:2, max:20, version:'1.21.4', address:'203.0.113.42:25565', access:'whitelist', names:'Steve\nAlex\nSam', admins:[], draftNames:null },
];
const app = document.querySelector('#app');
const announce = (message) => {
  const el = document.querySelector('#toast');
  el.textContent = message;
  el.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('visible'), 3500);
};
function hydrateIcons() {
  document.querySelectorAll('[data-icon]').forEach(el => { el.innerHTML = icon(el.dataset.icon); });
}

// Reusable, locally drawn illustrations. There are no external image requests.
function buildIllustrations() {
  let island = '';
  const colors = ['#7e9a51','#91a85c','#80974e','#a2b96a','#8ba357'];
  const tile = (i,j,h) => ({ x:310+(i-j)*24, y:66+(i+j)*12-h*14 });
  const cube = (x,y,w,h,top='#92aa5e',left='#596340',right='#414d32') => `<polygon points="${x},${y} ${x+w},${y+w/2} ${x},${y+w} ${x-w},${y+w/2}" fill="${top}"/><polygon points="${x-w},${y+w/2} ${x},${y+w} ${x},${y+w+h} ${x-w},${y+w/2+h}" fill="${left}"/><polygon points="${x},${y+w} ${x+w},${y+w/2} ${x+w},${y+w/2+h} ${x},${y+w+h}" fill="${right}"/>`;
  for(let sum=0;sum<=18;sum++) for(let i=0;i<10;i++) {
    const j=sum-i;
    if(j<0||j>9) continue;
    if((i<2&&j<2)||(i>7&&j>7)||(i===0&&j>7)||(j===0&&i>7)||(i===9&&j<2)||(j===9&&i<2)) continue;
    const h = 1 + ((i<3&&j<5)?1:0) + ((i>6&&j<4)?1:0);
    const {x,y}=tile(i,j,h);
    island+=cube(x,y,24,31+(i*3+j*7)%28,colors[(i*7+j*3)%5],'#53543b','#363f2d');
    if((i+j)%4===0) island+=`<path d="m${x-8} ${y+18} 4 2m4-8 3 1" stroke="#b3c582" stroke-width="2" opacity=".5"/>`;
  }
  const tree=(i,j,scale=1)=>{ const p=tile(i,j,2); return `<g transform="translate(${p.x} ${p.y-55*scale}) scale(${scale})"><path d="M-4 46v38l8 4V46Z" fill="#645943"/><path d="M4 46v42l5-3V44Z" fill="#433f30"/>${cube(0,10,26,25,'#6e8f49','#3e6036','#2a4b2e')}${cube(0,-5,20,20,'#829f54','#527a3f','#385f34')}</g>`; };
  const trees = tree(1,3,.9)+tree(3,1,1.05)+tree(7,2,.9)+tree(8,3,.8)+tree(2,6,.85)+tree(6,7,.65);
  const house = `<g id="island-cabin"><title>A cabin waiting for the next game night</title><polygon points="295,128 355,158 355,210 295,180" fill="#9e8d66"/><polygon points="355,158 395,138 395,190 355,210" fill="#706e50"/><path d="m284 131 49-50 74 50-49 33Z" fill="#4c5b40"/><path d="m333 81 25 83 49-33Z" fill="#334732"/><path d="m284 131 74 33-25-83Z" fill="#788364"/><path d="m298 128 40 18m-29-29 35 17m-25-28 20 11" stroke="#98a081" stroke-width="3" opacity=".5"/><polygon points="311,150 328,158 328,177 311,169" fill="#e0bf77"/><path d="m319 154 0 19m-8-14 17 8" stroke="#7b6b43" stroke-width="2"/><polygon points="370,164 384,157 384,176 370,183" fill="#d7af64"/><polygon points="337,173 348,178 348,205 337,199" fill="#514c35"/><path d="m341 185 2 1" stroke="#d7b976" stroke-width="2"/></g>`;
  let panorama='';
  for(let i=0;i<23;i++) {
    const x=i*32, h=24+((i*17+5)%6)*10, base=118-h;
    panorama+=`<rect x="${x}" y="${base}" width="33" height="${h+20}" fill="${i%3===0?'#3d4c31':'#34442d'}"/><rect x="${x}" y="${base}" width="33" height="6" fill="#667b46"/>`;
    if(i%3===1) panorama+=`<rect x="${x+13}" y="${base-34}" width="5" height="37" fill="#6c6445"/><rect x="${x+2}" y="${base-55}" width="27" height="25" fill="#4c6637"/><rect x="${x+6}" y="${base-64}" width="20" height="18" fill="#5e7941"/>`;
  }
  document.querySelector('#svg-library').innerHTML=`<svg xmlns="http://www.w3.org/2000/svg"><defs>
    <radialGradient id="island-glow"><stop stop-color="#51623c" stop-opacity=".35"/><stop offset="1" stop-color="#101310" stop-opacity="0"/></radialGradient>
    <linearGradient id="sky" x2="0" y2="1"><stop stop-color="#263427"/><stop offset="1" stop-color="#3e4f34"/></linearGradient>
    <symbol id="world-art" viewBox="0 0 620 390"><g id="night-sky"><title>A quiet evening above your Minecraft world</title><ellipse cx="310" cy="205" rx="285" ry="175" fill="url(#island-glow)"/><circle cx="435" cy="62" r="18" fill="#c3ce9a"/><path d="M444 46a18 18 0 0 0 0 32 18 18 0 1 1 0-32Z" fill="#a9b784"/><g fill="#9eae81"><rect x="174" y="65" width="2" height="2"/><rect x="395" y="27" width="2" height="2"/><rect x="490" y="137" width="2" height="2"/><rect x="221" y="30" width="2" height="2"/><rect x="115" y="140" width="2" height="2"/><rect x="509" y="87" width="3" height="3"/></g></g><ellipse cx="310" cy="337" rx="145" ry="17" fill="#070d07" opacity=".6"/><g id="floating-world"><title>A persistent world, ready for your next session</title>${island}${trees}${house}</g></symbol>
    <symbol id="landscape" viewBox="0 0 720 120"><rect width="720" height="120" fill="url(#sky)"/><circle cx="575" cy="27" r="16" fill="#a8b785" opacity=".7"/><path d="M0 80V53h40V40h32V22h42v18h30v18h68V39h45V16h42v23h40v28h80V45h40V29h65v25h45v20h70V48h40V35h42v31h80v54H0Z" fill="#516147" opacity=".6"/>${panorama}<path d="M0 114h720v6H0Z" fill="#1c2b1b"/></symbol>
  </defs></svg>`;
}
const landscape = () => '<svg viewBox="0 0 720 120" preserveAspectRatio="xMidYMid slice" aria-hidden="true"><use href="#landscape"/></svg>';

function header(isApp=false) {
  return `<div class="${isApp?'app-header':''}"><header class="site-header container">
    <div class="app-nav"><a href="#landing" data-view="landing" aria-label="MCWorldControl home">${brand()}</a>${isApp?`<span class="nav-item">${icon('grid')} Your servers</span>`:''}</div>
    ${isApp?`<div class="account"><span class="avatar" aria-hidden="true">AL</span><span class="account-name">alif@example.com</span><button class="button ghost small" data-logout>Log out ${icon('logout')}</button></div>`:`<nav class="header-links" aria-label="Main navigation"><a href="#how-it-works" data-anchor="how-it-works">How it works</a><a href="#faq" data-anchor="faq">FAQ</a><button class="button secondary small" data-entry>${signedIn?'Open dashboard':'Log in'} ${icon('arrow')}</button></nav>`}
  </header></div>`;
}
const footer = () => `<footer class="footer container"><a href="#landing" data-view="landing">${brand()}</a><span>Your world. On your schedule.</span><span class="footer-right">${icon('leaf')} Built for the next time you play.</span></footer>`;

function card(s,preview=false) {
  const ready=s.state==='ready';
  const stopped=s.state==='stopped';
  const action=preview?'data-entry':`data-action="${stopped?'start':'stop'}" data-server="${s.id}"`;
  const manage=preview?'data-entry':`data-manage="${s.id}"`;
  return `<article class="server-card" aria-label="${escapeHTML(s.name)}">
    <div class="card-scenery ${ready?'dusk':''}">${landscape()}<span class="server-role">${s.role==='owner'?'YOUR SERVER':'SHARED WITH YOU'}</span></div>
    <div class="card-body"><div class="server-card-head"><${preview?'h3':'h2'}>${escapeHTML(s.name)}</${preview?'h3':'h2'}><span class="status ${statusClass(s)}">${statusText(s)}</span></div>
    <div class="server-meta"><span>${ready?`${s.players} / ${s.max} players`:'No players online'}</span><span class="dot"></span><span>Java ${s.version}</span><span class="dot"></span><span>${s.role==='owner'?'Owner':'Admin'}</span></div>
    <div class="address-box"><div><div class="eyebrow">CONNECTION ADDRESS</div><div class="address-text ${ready?'mono':'unavailable'}">${ready?s.address:stopped?'Start your server to get an address.':s.state==='minecraft'?'Minecraft is getting ready.':'Available when your server is ready.'}</div></div><button class="icon-button" data-copy="${s.id}" aria-label="Copy address for ${escapeHTML(s.name)}" ${ready?'':'disabled'}>${icon('copy')}</button></div>
    <div class="card-actions"><button class="button ${stopped?'primary':'secondary'}" ${action} ${stopped||ready?'':'disabled'}>${icon(stopped?'play':ready?'stop':'clock')} ${stopped?'Start server':ready?'Stop server':statusText(s)}</button><button class="button ghost" ${manage}>${icon('settings')} Manage</button><button class="icon-button" ${preview?'data-entry':`data-refresh="${s.id}"`} aria-label="Refresh ${escapeHTML(s.name)}">${icon('refresh')}</button></div>
    <p class="card-footnote">${icon(stopped?'shield':ready&&s.players?'users':'clock')}${stopped?'Your world is saved for next time.':ready&&s.players?'Idle shutdown waits until everyone leaves.':ready?'Stops in 28 min if nobody joins.':s.state==='stopping'?'Saving your world and shutting down.':'Startup takes a few minutes.'}</p></div>
  </article>`;
}

function landing() {
  const previewServers=[{...servers[0],state:'stopped'}, {...servers[1],state:'ready'}].filter(s=>s.id);
  if(previewServers.length<2) previewServers.push({id:'sample',name:'The long weekend',role:'admin',state:'ready',players:2,max:20,version:'1.21.4',address:'203.0.113.42:25565'});
  return `${header()}<main id="main-content" tabindex="-1" class="container">
    <section class="hero" aria-labelledby="hero-title"><div class="hero-copy"><div class="hero-kicker">FOR THE OCCASIONAL ADVENTURERS</div><h1 id="hero-title">Your world.<br>On your<br><em>schedule.</em></h1><p class="hero-description">A Minecraft server for when the group chat<br class="desktop-break"> finally says, “tonight?”<br>Start it when you play. Keep your world between sessions. Let idle shutdown handle the rest.</p><div class="hero-actions"><button class="button primary" data-entry>${signedIn?'Open dashboard':'Log in'} ${icon('arrow')}</button><a class="text-button" href="#how-it-works" data-anchor="how-it-works">See how it works ${icon('chevron')}</a></div><p class="hero-note">${icon('clock')} Start a few minutes before game night.</p></div>
    <div class="hero-art"><span class="world-caption">A LITTLE WORLD WORTH COMING BACK TO</span><span class="scene-dot">✧</span><svg class="world-illustration" viewBox="0 0 620 390" role="img" aria-label="An illustrated floating Minecraft island with trees and a warmly lit cabin under the moon"><use href="#world-art"/></svg><div class="hero-server"><div class="hero-server-head"><div class="hero-server-name"><span class="mini-server-icon">${icon('box')}</span><div><strong>Sunday survival</strong><small>Ready for the next adventure.</small></div></div><span class="status stopped">Stopped</span></div><div class="hero-server-foot"><p>${icon('shield')} World saved. Pick up where you left off.</p><button class="button primary small" data-entry>${icon('play')} Start</button></div></div></div></section>
    <div class="principles"><div>${icon('clock')} Stops when nobody's playing</div><div>${icon('box')} Your world stays between sessions</div><div>${icon('users')} Share control with friends</div><div>${icon('lock')} Choose who can join</div></div>
    <section class="section" aria-labelledby="preview-title"><div class="section-head"><div><div class="eyebrow">LESS SETUP. MORE PLAYING.</div><h2 id="preview-title">Game night starts here.</h2></div><p>Your servers, their status, and the address your friends need. All in one quiet little dashboard.</p></div><div class="dashboard-preview"><div class="preview-chrome"><div class="window-dots"><i></i><i></i><i></i></div><span>MCWorldControl / YOUR SERVERS</span><span>PRODUCT PREVIEW</span></div><div class="preview-content"><div class="preview-heading"><div><h3>Your servers</h3><p>A home for every adventure.</p></div><button class="button secondary small" data-entry>${icon('plus')} Create server</button></div><div class="preview-card-grid">${previewServers.slice(0,2).map(s=>card(s,true)).join('')}</div><div class="preview-bottom"><span>Start. Copy the address. See you in there.</span><button class="text-button" data-entry>${signedIn?'Open your servers':'Log in to your servers'} ${icon('arrow')}</button></div></div></div></section>
    <section id="how-it-works" class="section steps-section" aria-labelledby="steps-title"><div class="section-head"><div><div class="eyebrow">FITS AROUND REAL LIFE</div><h2 id="steps-title">Whenever everyone’s free.</h2></div><p>A weekend, a spare evening, or the occasional spontaneous session.</p></div><div class="steps-grid"><div><div class="step-number">01 / GET READY</div><h3>Start your server.</h3><p>Log in and hit Start. Give Minecraft a few minutes to get ready while you round up your friends.</p></div><div><div class="step-number">02 / GET TOGETHER</div><h3>Pick up your adventure.</h3><p>Copy the current address into Minecraft and carry on with the world you’ve been building together.</p></div><div><div class="step-number">03 / CALL IT A NIGHT</div><h3>Leave the world waiting.</h3><p>Stop the server when you’re done. Forget? Idle shutdown stops it after everyone has left. Your world stays.</p></div></div><div class="feature-strip"><div><div class="feature-icon">${icon('leaf')}</div><h3>Made for the in-between.</h3><p>You might play every Sunday. You might skip a month. Stop your server between sessions and come back when life lines up.</p></div><div><div class="feature-icon">${icon('users')}</div><h3>Pass around the controls.</h3><p>Add a trusted friend as an admin. They can start the server and manage player access even when you’re away.</p></div><div><div class="feature-icon">${icon('lock')}</div><h3>Your kind of company.</h3><p>Keep an allowlist of Minecraft usernames, or open the server to anyone with the address. You decide who joins.</p></div></div></section>
    <section id="faq" class="section faq-section" aria-labelledby="faq-title"><div><div class="eyebrow">BEFORE YOU HOP IN</div><h2 id="faq-title">A few good questions.</h2><p class="muted">The things you’ll want to know before the next “anyone on?”</p></div><div class="faq-list">
    <details><summary>Will our world still be there next time?</summary><p>Yes. Stopping your server keeps its world, so you can start it again for another session. Deleting the server permanently deletes its world. World backups are not currently available.</p></details>
    <details><summary>Does the server start when someone joins?</summary><p>Someone needs to log in and start the server first. Startup takes a few minutes. Once it says Ready to join, copy the current address into Minecraft.</p></details>
    <details><summary>What if we forget to stop it?</summary><p>Idle shutdown stops your server after it has had no players for a period of time. The dashboard shows a countdown when one is available. Stopping retains your world.</p></details>
    <details><summary>Can my friends start the server too?</summary><p>Yes. The owner can add friends with confirmed MCWorldControl accounts as admins. Admins can start, stop, rename, and manage player access. Only the owner can manage admins or delete the server.</p></details>
    <details><summary>How do we choose who can join?</summary><p>Use Player access to choose public access or an allowlist of Minecraft usernames. Being allowed to play does not grant permission to control the server.</p></details></div></section>
    <section class="closing"><div><h2>Same world. Next adventure.</h2><p>We’ll be here when the group chat gets going.</p></div><button class="button primary" data-entry>${signedIn?'Open dashboard':'Log in'} ${icon('arrow')}</button></section>
    </main>${footer()}`;
}

function dashboard() {
  const shown=servers.filter(s=>filter==='all'||(filter==='owned'?s.role==='owner':s.role==='admin'));
  return `${header(true)}<main id="main-content" tabindex="-1" class="app-content container"><div class="breadcrumb">Workspace ${icon('chevron')} <span>Your servers</span></div><div class="dashboard-heading"><div><h1>Your servers</h1><p>Good worlds are worth coming back to.</p></div><button class="button primary" data-create>${icon('plus')} Create server</button></div><div class="dashboard-toolbar"><nav class="server-filters" aria-label="Filter servers"><button data-filter="all" ${filter==='all'?'aria-current="page"':''}>All servers <span class="count">${servers.length}</span></button><button data-filter="owned" ${filter==='owned'?'aria-current="page"':''}>Owned <span class="count">${servers.filter(s=>s.role==='owner').length}</span></button><button data-filter="shared" ${filter==='shared'?'aria-current="page"':''}>Shared <span class="count">${servers.filter(s=>s.role==='admin').length}</span></button></nav><span class="sync"><span class="review-dot"></span> Sample workspace</span></div><div class="server-grid">${shown.length?shown.map(s=>card(s)).join(''):'<p class="empty">No servers yet.</p>'}</div><div class="dashboard-tip">${icon('leaf')}<div><strong>Your world stays while your server rests.</strong><br>Start a few minutes before you play. Idle shutdown handles the empty hours.</div></div></main>${footer()}`;
}

function login(mode='login') {
  const signup=mode==='signup',reset=mode==='reset';
  return `<div class="login-page"><header class="login-header container"><a href="#landing" data-view="landing">${brand()}</a><button class="button subtle small" data-view="landing">← Back</button></header><main id="main-content" tabindex="-1" class="login-main"><div class="login-brand">${brand()}</div><section class="login-box"><h1>${signup?'Create your account':reset?'Reset your password':'Welcome back.'}</h1><p>${signup?'Your next adventure starts here.':reset?'We’ll send a code to your email.':'Your next session is a few clicks away.'}</p><form id="auth-form" data-mode="${mode}"><label class="field">Email<input type="email" name="email" placeholder="you@example.com" autocomplete="off" ${reset?'required':''}></label>${reset?'':`<label class="field"><span class="password-label">Password ${signup?'':'<button type="button" class="text-button" data-auth="reset">Forgot password?</button>'}</span><input type="password" name="password" placeholder="${signup?'Choose a password':'Enter your password'}" autocomplete="off">${signup?'<small>At least 12 characters, including uppercase, lowercase, and a number.</small>':''}</label>`}<button class="button primary wide" type="submit">${signup?'Sign up':reset?'Send reset code':'Log in'}</button></form><div class="login-signup">${signup||reset?'Already have an account?':'New around here?'} <button class="text-button" data-auth="${signup||reset?'login':'signup'}">${signup||reset?'Log in':'Sign up'}</button></div></section><p class="login-note">${icon('lock')} ${reset?'Password recovery':'Account access'} through Amazon Cognito</p></main><div class="provider-caption">Cognito styling reference · Provider controls the final layout.<br>This prototype does not submit or store credentials. Log in opens the sample dashboard.</div></div>`;
}

function showView(view,scroll=true) {
  currentView=['landing','dashboard','login'].includes(view)?view:'landing';
  history.replaceState(null,'',`#${currentView}`);
  app.innerHTML=currentView==='dashboard'?dashboard():currentView==='login'?login():landing();
  document.querySelectorAll('.view-switcher button').forEach(b=>{ if(b.dataset.view===currentView)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current'); });
  hydrateIcons();
  if(scroll) { window.scrollTo(0,0); document.querySelector('#main-content').focus({preventScroll:true}); }
}
function refreshDashboard() { if(currentView==='dashboard') { app.innerHTML=dashboard(); hydrateIcons(); } }
function manage(id) {
  selectedServer=servers.find(s=>s.id===id);
  if(!selectedServer)return;
  settingsTab='general';
  renderSettings();
  document.querySelector('#manage-dialog').showModal();
}
function renderSettings() {
  const s=selectedServer;
  document.querySelector('#manage-title').textContent=s.name;
  document.querySelector('#manage-role').textContent=`${s.role==='owner'?'You own this server.':'You’re an admin on this server.'} · Java ${s.version}`;
  document.querySelector('[data-setting="admins"]').hidden=s.role!=='owner';
  document.querySelectorAll('[data-setting]').forEach(b=>{if(b.dataset.setting===settingsTab)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  let content='';
  if(settingsTab==='general') content=`<h3>A familiar name.</h3><p>Make it easy for your group to find its world.</p><form id="rename-form"><label class="field">Server name<input name="name" value="${escapeHTML(s.name)}" maxlength="80" required></label><button class="button secondary" type="submit">Save name</button></form><div style="margin-top:28px"><div class="detail-row"><span>Server status</span><span class="status ${statusClass(s)}">${statusText(s)}</span></div><div class="detail-row"><span>Minecraft</span><span>Java ${s.version}</span></div><div class="detail-row"><span>Your role</span><span>${s.role==='owner'?'Owner':'Admin'}</span></div></div><div class="danger-zone"><h3>${s.role==='owner'?'Delete server':'Leave this server'}</h3><p>${s.role==='owner'?'Permanently delete this server and its world. This cannot be undone.':'Remove yourself as an admin. You’ll lose access to this server’s controls.'}</p><button class="button danger" data-destructive="${s.role==='owner'?'delete':'leave'}">${s.role==='owner'?'Delete server':'Leave server'}</button></div>`;
  if(settingsTab==='access') content=`<h3>Choose your company.</h3><p>Player access controls who joins in Minecraft. It does not give anyone permission to manage this server.</p><form id="access-form"><fieldset><legend>Who can join?</legend><label class="radio-card"><input type="radio" name="access" value="whitelist" ${s.access==='whitelist'?'checked':''}><span><strong>Selected players</strong><small>Only the usernames on your allowlist.</small></span>${icon('lock')}</label><label class="radio-card"><input type="radio" name="access" value="public" ${s.access==='public'?'checked':''}><span><strong>Anyone with the address</strong><small>Public access to your server.</small></span>${icon('globe')}</label></fieldset><label class="field" id="access-players" ${s.access==='public'?'hidden':''}>Minecraft usernames<textarea name="players" rows="5">${escapeHTML(s.draftNames??s.names)}</textarea><small>One username per line, or separated by commas. An empty list lets nobody join.</small></label><p class="info-box">${icon('clock')}${s.state==='stopped'?'Changes apply the next time this server starts.':'Changes are applied to the running server.'}</p><button class="button primary" type="submit" style="margin-top:20px">Save player access</button><p id="access-notice" class="form-notice" role="status"></p></form>`;
  if(settingsTab==='admins') content=`<h3>Share the controls.</h3><p>Admins can start, stop, rename, and manage player access. Only you can manage admins or delete this server.</p><div>${s.admins.length?s.admins.map(email=>`<div class="admin-row"><span class="avatar">${escapeHTML(email.slice(0,2).toUpperCase())}</span><span>${escapeHTML(email)}<small>Admin</small></span><button class="text-button" data-remove-admin="${escapeHTML(email)}">Remove</button></div>`).join(''):'<p class="muted" style="font-size:11px">No admins yet.</p>'}</div><form id="admin-form" style="margin-top:26px"><label class="field">Add by email<input type="email" name="email" placeholder="friend@example.com" required><small>They need a confirmed MCWorldControl account. In this preview, use alex@example.com or sam@example.com.</small></label><button class="button secondary" type="submit">${icon('plus')} Add admin</button><p id="admin-notice" class="form-notice" role="status"></p></form>`;
  document.querySelector('#settings-content').innerHTML=content;
  hydrateIcons();
}

function startServer(s) {
  if(s.state!=='stopped')return;
  s.state='starting';refreshDashboard();announce('Sample server is starting.');
  setTimeout(()=>{if(!servers.includes(s))return;s.state='minecraft';refreshDashboard();},1800);
  setTimeout(()=>{if(!servers.includes(s))return;s.state='ready';s.players=0;refreshDashboard();announce(`${s.name} is ready to join.`);},4200);
}
function stopServer(s) {
  if(s.state!=='ready')return;
  if(s.players>0) {
    showConfirm('Stop this session?',`There are ${s.players} players online. Stopping the server will disconnect them. Their world will remain saved.`, 'Stop server',()=>finishStop(s));
  } else finishStop(s);
}
function finishStop(s) {
  s.state='stopping';refreshDashboard();
  setTimeout(()=>{if(!servers.includes(s))return;s.state='stopped';s.players=0;refreshDashboard();announce('Server stopped. Your world is saved.');},1700);
}
function showConfirm(title,message,action,onConfirm,requireName=false) {
  const dialog=document.querySelector('#confirm-dialog');
  document.querySelector('#confirm-content').innerHTML=`<div class="modal-header"><h2 id="confirm-title">${escapeHTML(title)}</h2><button class="icon-button" data-close="confirm-dialog" aria-label="Close confirmation">${icon('close')}</button></div><p>${escapeHTML(message)}</p>${requireName?`<label class="field" style="margin-top:20px">Type ${escapeHTML(selectedServer.name)} to confirm<input id="confirm-name" autocomplete="off"></label>`:''}<div class="modal-actions"><button class="button secondary" data-close="confirm-dialog">Cancel</button><button class="button danger" id="confirm-submit" ${requireName?'disabled':''}>${escapeHTML(action)}</button></div>`;
  if(requireName)document.querySelector('#confirm-name').addEventListener('input',e=>{document.querySelector('#confirm-submit').disabled=e.target.value!==selectedServer.name;});
  document.querySelector('#confirm-submit').onclick=()=>{dialog.close();onConfirm();};
  dialog.showModal();
}

document.addEventListener('click',async e=>{
  const entry=e.target.closest('[data-entry]');
  if(entry){e.preventDefault();showView(signedIn?'dashboard':'login');return;}
  const logout=e.target.closest('[data-logout]');
  if(logout){signedIn=false;showView('landing');return;}
  const view=e.target.closest('[data-view]');
  if(view){e.preventDefault();showView(view.dataset.view);return;}
  const close=e.target.closest('[data-close]');
  if(close){document.getElementById(close.dataset.close).close();return;}
  const anchor=e.target.closest('[data-anchor]');
  if(anchor){e.preventDefault();document.getElementById(anchor.dataset.anchor)?.scrollIntoView({behavior:'smooth'});return;}
  const filterButton=e.target.closest('[data-filter]');
  if(filterButton){filter=filterButton.dataset.filter;refreshDashboard();document.querySelector(`[data-filter="${filter}"]`).focus();return;}
  const create=e.target.closest('[data-create]');
  if(create){document.querySelector('#create-dialog').showModal();return;}
  const manageButton=e.target.closest('[data-manage]');
  if(manageButton){manage(manageButton.dataset.manage);return;}
  const setting=e.target.closest('[data-setting]');
  if(setting){settingsTab=setting.dataset.setting;renderSettings();return;}
  const action=e.target.closest('[data-action]');
  if(action){const s=servers.find(s=>s.id===action.dataset.server);if(s)action.dataset.action==='start'?startServer(s):stopServer(s);return;}
  const copy=e.target.closest('[data-copy]');
  if(copy){const s=servers.find(s=>s.id===copy.dataset.copy);if(!s||s.state!=='ready')return;try {await navigator.clipboard.writeText(s.address);copy.innerHTML=icon('check');announce('Address copied. See you in there.');setTimeout(()=>{if(copy.isConnected)copy.innerHTML=icon('copy');},1800);}catch{announce(`Copy this sample address: ${s.address}`);}return;}
  const refresh=e.target.closest('[data-refresh]');
  if(refresh){announce('Sample server status is up to date.');return;}
  const auth=e.target.closest('[data-auth]');
  if(auth){app.innerHTML=login(auth.dataset.auth);document.querySelector('#main-content').focus({preventScroll:true});return;}
  const destructive=e.target.closest('[data-destructive]');
  if(destructive){const s=selectedServer,del=destructive.dataset.destructive==='delete';showConfirm(del?'Delete this world?':'Leave this server?',del?`Deleting ${s.name} permanently removes the server and its world. There are no backups. ${s.players?`${s.players} players are online.`:''}`:`You’ll lose admin access to ${s.name}.`,del?'Delete forever':'Leave server',()=>{document.querySelector('#manage-dialog').close();servers=servers.filter(x=>x!==s);refreshDashboard();announce(del?'Sample server and world deleted.':'You left the sample server.');},del);return;}
  const remove=e.target.closest('[data-remove-admin]');
  if(remove){selectedServer.admins=selectedServer.admins.filter(x=>x!==remove.dataset.removeAdmin);renderSettings();announce('Admin removed from this sample server.');}
});
document.addEventListener('change',e=>{
  if(e.target.matches('input[name="access"]')) {
    const form=e.target.closest('form');
    const target=form.id==='create-form'?'#create-players':'#access-players';
    document.querySelector(target).hidden=e.target.value==='public';
  }
});
document.addEventListener('input',e=>{if(e.target.closest('#access-form')&&e.target.name==='players')selectedServer.draftNames=e.target.value;});
document.addEventListener('submit',e=>{
  e.preventDefault();
  const form=e.target;
  const values=new FormData(form);
  if(form.id==='auth-form') {
    form.reset();
    if(form.dataset.mode!=='login'){announce('Preview only. Registration and recovery stay in Cognito.');return;}
    signedIn=true;showView('dashboard');announce('Sample workspace opened. No credentials were submitted.');
  }
  if(form.id==='rename-form') {
    const name=String(values.get('name')||'').trim();
    if(!name){form.querySelector('input').setCustomValidity('Enter a name.');form.reportValidity();return;}
    selectedServer.name=name;renderSettings();refreshDashboard();announce('Server name saved in this preview.');
  }
  if(form.id==='access-form') {
    const names=String(values.get('players')||'').split(/[\s,;]+/).filter(Boolean);
    const invalid=names.filter(n=>!/^\w{3,16}$/.test(n));
    if(values.get('access')==='whitelist'&&invalid.length){document.querySelector('#access-notice').textContent=`Check these Minecraft usernames: ${invalid.join(', ')}`;return;}
    selectedServer.access=String(values.get('access'));selectedServer.names=[...new Map(names.map(n=>[n.toLowerCase(),n])).values()].join('\n');selectedServer.draftNames=null;
    document.querySelector('#access-notice').textContent=selectedServer.state==='stopped'?'Saved. Applies the next time this server starts.':'Saved. The server is updating now.';
  }
  if(form.id==='admin-form') {
    const email=String(values.get('email')||'').trim().toLowerCase();
    if(!['alex@example.com','sam@example.com'].includes(email)){document.querySelector('#admin-notice').textContent='No confirmed sample account found. Try alex@example.com or sam@example.com.';return;}
    if(selectedServer.admins.includes(email)){document.querySelector('#admin-notice').textContent='They’re already an admin.';return;}
    selectedServer.admins.push(email);renderSettings();announce('Admin added to this sample server.');
  }
  if(form.id==='create-form') {
    if(servers.some(s=>s.role==='owner')){announce('Sample server limit reached. You already own a server.');return;}
    const s={id:`sample-${Date.now()}`,name:String(values.get('serverName')||'').trim()||'New server',role:'owner',state:'stopped',players:0,max:20,version:'1.21.4',address:'203.0.113.64:25565',access:String(values.get('access')),names:String(values.get('players')||''),admins:[],draftNames:null};
    servers.push(s);document.querySelector('#create-dialog').close();form.reset();filter='all';showView('dashboard');startServer(s);
  }
});
document.querySelectorAll('dialog').forEach(dialog=>{
  dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}});
});
buildIllustrations();
showView(location.hash.slice(1)||'landing',false);
