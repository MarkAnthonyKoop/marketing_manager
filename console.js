// Console logic — served at /console.js so the page carries NO inline script and
// the CSP can be script-src 'self' (inline handlers/attributes are gone; all
// wiring is addEventListener / element properties, see wire() at the bottom).
const TABS = [["compose","Compose"],["campaigns","Campaigns"],["schedule","Schedule"],["monitor","Monitor"],["chat","Chat"],["guide","Guide"]];
let TOKEN = localStorage.getItem("mc_token") || "";
let SESSION = null, PLATFORMS = [];
const $ = s => document.querySelector(s);
const el = (t,c,h) => { const e=document.createElement(t); if(c)e.className=c; if(h!=null)e.innerHTML=h; return e; };
// Escape EVERY dynamic value before it touches innerHTML — campaign names, chat
// replies, scrape results etc. are attacker-influenceable (stored XSS otherwise).
const esc = s => String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
const note = (sel,msg,cls) => { const b=$(sel); b.prepend(el("div","card "+(cls||""),msg)); };
const fail = e => `<span class="res"><span class="bad">error: ${esc(e.message||e)}</span></span>`;

async function call(method, path, body){
  const r = await fetch(path, {method, headers:{"X-Console-Token":TOKEN,
    ...(body?{"Content-Type":"application/json"}:{})}, body: body?JSON.stringify(body):undefined});
  if(r.status===401){ throw new Error("unauthorized"); }
  return r.json();
}
async function login(){
  TOKEN = $("#tok").value.trim();
  try{ await call("GET","/api/platforms"); localStorage.setItem("mc_token",TOKEN);
       $("#gate").classList.add("hide"); init(); }
  catch(e){ $("#gateErr").textContent = "Invalid token."; }
}
const NAVBTN = {};
function switchTab(id){
  document.querySelectorAll("nav button").forEach(x=>x.classList.remove("on"));
  document.querySelectorAll(".tab").forEach(x=>x.classList.remove("on"));
  NAVBTN[id].classList.add("on"); $("#t-"+id).classList.add("on");
  if(id==="campaigns")loadCampaigns(); if(id==="schedule")loadSchedule(); if(id==="monitor")loadHistory();
}
function buildNav(){
  const nav=$("#nav");
  TABS.forEach(([id,name],i)=>{ const b=el("button",i===0?"on":"",name);
    b.onclick=()=>switchTab(id); NAVBTN[id]=b; nav.appendChild(b); });
}
function chips(container, selected){
  const c=$(container); c.innerHTML="";
  PLATFORMS.forEach(p=>{ const on = selected.includes(p.key);
    const e=el("div","chip"+(on?" on":""), `${esc(p.label)} <span class="g">${esc(p.status)}</span>`);
    e.dataset.key=p.key; e.onclick=()=>e.classList.toggle("on"); c.appendChild(e); });
}
function picked(container){ return [...document.querySelectorAll(container+" .chip.on")].map(e=>e.dataset.key); }

async function init(){
  const d = await call("GET","/api/platforms"); PLATFORMS=d.platforms;
  chips("#c-plats", d.working); chips("#cm-plats", d.working); chips("#s-plats", d.working);
  loadGuide();
}

// ---- onboarding: welcome dialog, guided tours, the guide tab ----
let GUIDE=null;
const TOURS=[
 ["🚀","Start a drip campaign","I want to start a drip campaign (a series of posts that go out automatically over days)."],
 ["✍️","Write a post & preview it","I want to write one post and preview how it would look on every platform — without actually posting anything."],
 ["📅","Schedule a post for later","I want to schedule a post to go out at a specific date and time."],
 ["👀","See what people are saying","I want to search social platforms for what people are saying about a topic I care about."],
 ["🎓","Teach me to talk to AI","Teach me how to talk to an AI assistant like you so I get great results — short lesson, real examples I can copy, then quiz me gently."],
 ["✨","Surprise me","Show me the most useful thing you can do for someone launching a new venture."]];
async function loadGuide(){
  try{ GUIDE = await call("GET","/api/guide"); }catch(e){ GUIDE=null; }
  if(GUIDE&&GUIDE.brand){ $("#brand").textContent=GUIDE.brand; document.title=GUIDE.brand; }
  $("#g-body").innerHTML = (GUIDE&&GUIDE.markdown) ? md2html(GUIDE.markdown)
    : "<p class='muted'>No guide installed.</p>";
  if(!localStorage.getItem("mc_onboarded")) showWelcome();
}
function skipLink(){
  const p=el("p","muted mt ctr"); const a=el("a","linkmut","skip for now"); a.href="#";
  a.onclick=e=>{ e.preventDefault(); closeWelcome(); }; p.appendChild(a); return p;
}
function showWelcome(){
  const g=GUIDE||{}; const box=$("#welBox"); box.innerHTML="";
  box.appendChild(el("b","big",esc(g.greeting||"Hey — welcome.")));
  box.appendChild(el("p","muted","I'm an AI marketing manager you talk to in plain English. Nothing ever posts publicly unless you clearly say so — everything starts as a safe preview."));
  const know=el("button","act","📖 Get to know me"); know.onclick=openGuide; box.appendChild(know);
  const go=el("button","act alt","Continue →"); go.onclick=tourMenu; box.appendChild(go);
  box.appendChild(skipLink());
  $("#wel").classList.remove("hide");
}
function tourMenu(){
  const box=$("#welBox"); box.innerHTML="";
  box.appendChild(el("b","","What should we do first?"));
  box.appendChild(el("p","muted","Pick one — I'll walk you through it, one small step at a time. You can't break anything; it's all preview until you say go."));
  TOURS.forEach((t,i)=>{ const b=el("button","act mt8",`${t[0]} ${t[1]}`);
    b.onclick=()=>startTour(i); box.appendChild(b); });
  box.appendChild(skipLink());
}
function closeWelcome(){ localStorage.setItem("mc_onboarded","1"); $("#wel").classList.add("hide"); }
function openGuide(){ closeWelcome(); switchTab("guide"); }
function startTour(i){
  closeWelcome(); switchTab("chat");
  $("#ch-msg").value = "TUTORIAL: I'm brand new to this console and to AI. "+TOURS[i][2]+
   " Walk me through it one small step at a time — tell me exactly what to tap or type here"+
   " (my tabs are Compose, Campaigns, Schedule, Monitor, Chat, Guide), ask me one question at a"+
   " time, keep everything in preview/dry-run unless I clearly say to post for real, and explain"+
   " any jargon in plain words.";
  chat();
}
function md2html(md){
  const e=s=>s.replace(/&/g,"&amp;").replace(/</g,"&lt;");
  const inline=s=>s.replace(/\*\*([^*]+)\*\*/g,"<b>$1</b>").replace(/`([^`]+)`/g,"<code>$1</code>");
  let out="", list=false, para=[];
  const flush=()=>{ if(para.length){ out+="<p>"+inline(para.join("<br>"))+"</p>"; para=[]; } };
  const endList=()=>{ if(list){ out+="</ul>"; list=false; } };
  e(md).split("\n").forEach(ln=>{
    const t=ln.trim();
    if(!t){ flush(); endList(); return; }
    const h=t.match(/^(#{1,4}) (.*)/);
    if(h){ flush(); endList(); out+=`<h${h[1].length+1}>${inline(h[2])}</h${h[1].length+1}>`; return; }
    if(/^[-•*] /.test(t)){ flush(); if(!list){ out+="<ul>"; list=true; } out+="<li>"+inline(t.slice(2))+"</li>"; return; }
    para.push(t); });
  flush(); endList(); return out;
}

async function broadcast(){
  const dry=$("#c-dry").checked;
  if(!dry && !confirm("Post this for real to the selected platforms?")) return;
  const out=$("#c-out"); out.innerHTML="<p class='muted'>working…</p>";
  try{
    const d = await call("POST","/api/broadcast",{ text:$("#c-text").value, link:$("#c-link").value,
      platforms:picked("#c-plats"), dry_run:dry });
    out.innerHTML = `<div class="card"><b>${d.dry_run?"Preview (not posted)":"Posted"}</b> · `+
      `${d.summary.posted} sent / ${d.summary.skipped} skipped / ${d.summary.failed} failed`+
      `<div class="res mt">`+ d.results.map(r=>{
        const cls = r.skipped?"skip":(r.ok?"ok":"bad"); const tag=r.skipped?"skip":(r.ok?"ok":"FAIL");
        return `<div class="${cls}">[${tag}] ${esc(r.platform)} — ${esc(r.url||r.error||"")}</div>`;}).join("")+`</div></div>`;
  }catch(e){ out.innerHTML=`<div class="card">${fail(e)}</div>`; }
}
async function createCampaign(){
  const steps=$("#cm-steps").value.split("\n").map(l=>l.trim()).filter(Boolean).map(l=>{
    const i=l.indexOf(":"); return {offset_days:parseFloat(l.slice(0,i))||0, text:l.slice(i+1).trim()};});
  try{
    const d=await call("POST","/api/campaigns",{name:$("#cm-name").value, platforms:picked("#cm-plats"), steps});
    await loadCampaigns();
    note("#cm-list", d.created?`✅ Campaign created (${esc(d.created)}) — ${steps.length} steps queued`
                             :fail({message:d.error||"unexpected reply"}));
  }catch(e){ note("#cm-list", fail(e)); }
}
async function loadCampaigns(){
  const d=await call("GET","/api/campaigns").catch(e=>({campaigns:[],_err:e}));
  const box=$("#cm-list"); box.innerHTML=""; if(d._err) return note("#cm-list", fail(d._err));
  (d.campaigns||[]).forEach(c=>{ const card=el("div","card",
    `<b>${esc(c.name)}</b> <span class="muted">(${esc(c.status)})</span><br>${c.sent}/${c.total} sent · ${esc(c.platforms.join(", "))}`);
    const row=el("div","row");
    ["pause","resume"].forEach(a=>{ const b=el("button","ghost f1",a);
      b.onclick=async()=>{ await call("POST",`/api/campaigns/${c.id}/${a}`).catch(()=>{}); loadCampaigns(); }; row.appendChild(b);});
    card.appendChild(row); box.appendChild(card); });
}
async function addSchedule(){
  try{
    const d=await call("POST","/api/schedule",{at:$("#s-at").value, text:$("#s-text").value, platforms:picked("#s-plats")});
    await loadSchedule();
    note("#s-list", d.added?`✅ Scheduled for ${esc(d.at)}`:fail({message:d.error||"unexpected reply"}));
  }catch(e){ note("#s-list", fail(e)); }
}
async function loadSchedule(){
  const d=await call("GET","/api/schedule").catch(e=>({schedule:[],_err:e}));
  const box=$("#s-list"); box.innerHTML=""; if(d._err) return note("#s-list", fail(d._err));
  (d.schedule||[]).forEach(i=>box.appendChild(el("div","card",
    `<b>${esc(i.status)}</b> · ${esc(i.at)}<br>${esc(i.text)} <span class="muted">→ ${esc(i.platforms.join(", "))}</span>`)));
}
async function tick(kind, dry){
  // param is DRY (true = preview). The original signature read it as `send`,
  // silently inverting the two buttons — the E2E asserts these semantics now.
  const sel = kind==="campaigns" ? "#cm-list" : "#s-list";
  if(!dry && !confirm("Really release due posts to the real platforms?")) return;
  try{
    const d=await call("POST",`/api/${kind}/tick`,{dry_run:dry});
    if(kind==="campaigns"){ await loadCampaigns();
      const n=Object.values(d.released||{}).reduce((a,b)=>a+b,0);
      note(sel, `${d.dry_run?"🔍 Preview tick":"▶️ Tick"} — ${n} due step${n===1?"":"s"}${d.dry_run?" (nothing sent)":" released"}`);
    } else { await loadSchedule();
      const n=(d.sent||[]).length;
      note(sel, `${d.dry_run?"🔍 Preview tick":"▶️ Tick"} — ${n} due post${n===1?"":"s"}${d.dry_run?" (nothing sent)":" sent"}`); }
  }catch(e){ note(sel, fail(e)); }
}
async function monitor(){
  const out=$("#m-out"); out.innerHTML="<p class='muted'>scanning…</p>";
  try{
    const d=await call("POST","/api/monitor",{query:$("#m-q").value});
    out.innerHTML = Object.entries(d.results).map(([p,rows])=>{
      const body = Array.isArray(rows) ? (rows.length?rows.slice(0,8).map(r=>`• ${esc(r.text||r.title||"")}`).join("<br>"):"—")
        : `<span class="muted">${esc(rows.error||"n/a")}</span>`;
      return `<div class="card"><b>${esc(p)}</b><pre>${body}</pre></div>`;}).join("");
  }catch(e){ out.innerHTML=`<div class="card">${fail(e)}</div>`; }
}
async function loadHistory(){
  const d=await call("GET","/api/history?tail=15").catch(e=>({history:[],_err:e}));
  const box=$("#m-hist"); box.innerHTML=""; if(d._err) return note("#m-hist", fail(d._err));
  (d.history||[]).slice().reverse().forEach(h=>box.appendChild(el("div","card",
    `<span class="muted">${esc(h.ts)}</span> · ${esc(h.source)}<br>${esc((h.text||"").slice(0,80))}`)));
}
async function chat(){
  const msg=$("#ch-msg").value.trim(); if(!msg)return; const log=$("#ch-log");
  log.appendChild(el("div","card","<b>you</b><br>"+esc(msg))); $("#ch-msg").value="";
  const wait=el("div","card","<span class='muted'>thinking…</span>"); log.appendChild(wait);
  wait.scrollIntoView({block:"end"});
  try{ const d=await call("POST","/api/chat",{message:msg, session_id:SESSION});
    SESSION=d.session_id; wait.innerHTML="<b>manager</b><br>"+esc(d.reply||"(no reply)").replace(/\n/g,"<br>");
    wait.scrollIntoView({block:"end"}); }
  catch(e){ wait.innerHTML=fail(e); }
}

function wire(){
  $("#tok").addEventListener("keydown",e=>{ if(e.key==="Enter") login(); });
  $("#tok-go").onclick=login;
  $("#who").onclick=()=>showWelcome(true);
  $("#c-go").onclick=broadcast;
  $("#cm-create").onclick=createCampaign;
  $("#cm-tickdry").onclick=()=>tick("campaigns",true);
  $("#cm-ticksend").onclick=()=>tick("campaigns",false);
  $("#s-add").onclick=addSchedule;
  $("#s-tickdry").onclick=()=>tick("schedule",true);
  $("#s-ticksend").onclick=()=>tick("schedule",false);
  $("#m-go").onclick=monitor;
  $("#ch-go").onclick=chat;
}
wire(); buildNav();
if(TOKEN){ call("GET","/api/platforms").then(()=>{ $("#gate").classList.add("hide"); init(); }).catch(()=>{}); }
