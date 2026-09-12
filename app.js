const $ = s => document.querySelector(s);
const state = {
  sessionId: localStorage.getItem('waterpulse_v5_session') || '',
  file: null,
  busy: false
};
const els = {
  welcome: $('#welcome'), messages: $('#messages'), input: $('#messageInput'), file: $('#fileInput'),
  send: $('#sendBtn'), toast: $('#toast'), attach: $('#attachBtn')
};

function esc(s=''){return String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
function toast(t){els.toast.textContent=t;els.toast.classList.add('show');setTimeout(()=>els.toast.classList.remove('show'),2200)}
function fmt(v,n=4){const x=Number(v);return Number.isFinite(x)?x.toFixed(n):'—'}
function pct(v){const x=Number(v);return Number.isFinite(x)?(x*100).toFixed(1)+'%':'—'}
function md(text=''){
  let s=esc(text);
  s=s.replace(/^###\s+(.+)$/gm,'<h3>$1</h3>');
  s=s.replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>');
  s=s.replace(/^[-•]\s+(.+)$/gm,'<li>$1</li>');
  s=s.replace(/(<li>.*<\/li>\n?)+/g,m=>'<ul>'+m+'</ul>');
  s=s.replace(/\n{2,}/g,'</p><p>').replace(/\n/g,'<br>');
  return '<p>'+s+'</p>';
}
function showMessages(){els.welcome.style.display='none';document.body.classList.add('chatting')}
function scrollBottom(){setTimeout(()=>window.scrollTo({top:document.body.scrollHeight,behavior:'smooth'}),40)}
function resize(){els.input.style.height='auto';els.input.style.height=Math.min(150,els.input.scrollHeight)+'px'}
function setFile(f){
  state.file=f||null;
  if(els.attach){
    els.attach.classList.toggle('has-file',!!f);
    els.attach.title=f?('已选择：'+f.name+'（再次点击可更换文件）'):'上传 PDF / Word / Excel / CSV';
  }
  if(f){toast('已添加文件：'+f.name)}
  else if(els.file){els.file.value=''}
}

function addUser(text,file){
  showMessages();
  const el=document.createElement('div'); el.className='msg user';
  el.innerHTML=`<div class="content"><div class="bubble">${text?esc(text):'请分析这个文件'}${file?`<div style="margin-top:8px;font-size:10px;opacity:.78">📎 ${esc(file.name)}</div>`:''}</div></div><div class="avatar">你</div>`;
  els.messages.appendChild(el); scrollBottom();
}
function traceHtml(trace=[]){
  if(!trace.length)return'';
  return `<details class="trace-box"><summary>查看分析过程 · ${trace.length} 项</summary><div class="trace-list">${trace.map(x=>`<div class="trace-item ${esc(x.status||'done')}"><i class="trace-dot"></i><div><div class="trace-title">${esc(x.step)}</div>${x.detail?`<div class="trace-detail">${esc(x.detail)}</div>`:''}</div></div>`).join('')}</div></details>`;
}
function actionHtml(actions=[]){
  if(!actions.length)return'';
  return `<div class="actions">${actions.map((a,i)=>`<button class="action-btn ${i===0?'primary':''}" data-action="${encodeURIComponent(JSON.stringify(a))}">${esc(a.label)}</button>`).join('')}</div>`;
}
function baselineCard(b){
  const rows=b?.data?.summary; if(!Array.isArray(rows)||!rows.length)return'';
  const r=rows[0];
  return `<div class="result-card"><div class="result-title">当前水风险结果</div><div class="metrics">
    <div class="metric"><span>综合风险指数</span><b>${fmt(r.PRWI)}</b></div>
    <div class="metric"><span>采购覆盖率</span><b>${pct(r.Coverage)}</b></div>
    <div class="metric"><span>有效数据覆盖</span><b>${pct(r.scored_coverage ?? r.Coverage)}</b></div>
    <div class="metric"><span>未识别采购份额</span><b>${pct(r.unknown_share_U)}</b></div>
  </div></div>`;
}
function scenarioCard(s){
  const d=s?.data; if(!d||typeof d!=='object')return'';
  const t=d.scenario_type||'';
  const names={NodeFailure:'主要供应节点中断',AqueductFuture:'未来水环境变化',PeakSeason:'关键用水期压力升高',ExtremeDrought:'严重干旱重现'};
  let metrics=[];
  if(t==='NodeFailure') metrics=[['预计供应损失',fmt(d.gross_loss)],['未满足需求',fmt(d.unmet_demand)],['剩余供应综合风险',fmt(d.conditional_PRWI)],['采购集中度',fmt(d.procurement_hhi)]];
  else if(t==='AqueductFuture') metrics=[['当前综合风险',fmt(d.PRWI_baseline)],['变化后综合风险',fmt(d.PRWI_future)],['变化值',fmt(d.PRWI_delta)],['假设路径',d.path||'—']];
  else metrics=[['当前综合风险',fmt(d.PRWI_baseline)],['变化后综合风险',fmt(d.PRWI_scenario)],['变化值',fmt(d.PRWI_delta)],['情况',names[t]||t||'压力测试']];
  return `<div class="result-card"><div class="result-title">${esc(names[t]||'压力情况下的变化')}</div><div class="metrics">${metrics.map(([k,v])=>`<div class="metric"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join('')}</div></div>`;
}
function addAI(data){
  showMessages();
  const el=document.createElement('div');el.className='msg ai';
  const provider=data.ai?.provider==='DeepSeek'?`DeepSeek · ${esc(data.ai.model||'')}`:'本地安全模板';
  const result=(data.result_summary?.baseline?baselineCard(data.result_summary.baseline):'')+(data.result_summary?.scenario?scenarioCard(data.result_summary.scenario):'');
  el.innerHTML=`<div class="avatar">AI</div><div class="content"><div class="bubble">${md(data.message||'')}${result}${actionHtml(data.actions||[])}${traceHtml(data.trace||[])}</div><div class="meta">WaterPulse AI · ${provider}</div></div>`;
  els.messages.appendChild(el); bindActions(el); scrollBottom();
}
function addTyping(){showMessages();const el=document.createElement('div');el.id='typingMsg';el.className='msg ai';el.innerHTML='<div class="avatar">AI</div><div class="content"><div class="bubble"><div class="typing"><i></i><i></i><i></i></div></div></div>';els.messages.appendChild(el);scrollBottom()}
function removeTyping(){$('#typingMsg')?.remove()}

async function callAgent({message='',action='',scenario_type='',material='',year='',path='',failure_fraction='',inventory='',file=null}={}){
  if(state.busy)return; state.busy=true; els.send.disabled=true; addTyping();
  try{
    const fd=new FormData();
    fd.append('session_id',state.sessionId);fd.append('message',message);fd.append('action',action);fd.append('scenario_type',scenario_type);fd.append('material',material);
    fd.append('year',year);fd.append('path',path);fd.append('failure_fraction',failure_fraction);fd.append('inventory',inventory);if(file)fd.append('file',file);
    const r=await fetch('/api/agent/message',{method:'POST',body:fd});
    const data=await r.json(); if(!r.ok)throw new Error(data.detail||'请求失败');
    if(data.session_id){state.sessionId=data.session_id;localStorage.setItem('waterpulse_v5_session',state.sessionId)}
    removeTyping();addAI(data);return data;
  }catch(e){removeTyping();addAI({message:'这次请求没有完成。请检查网络或后端服务后重试。',trace:[{step:'请求失败',status:'error',detail:String(e)}]})}
  finally{state.busy=false;els.send.disabled=false}
}
async function send(){
  const text=els.input.value.trim();const f=state.file;if(!text&&!f)return;
  addUser(text,f);els.input.value='';resize();setFile(null);await callAgent({message:text,file:f});
}
function bindActions(root=document){
  root.querySelectorAll('.action-btn').forEach(btn=>btn.onclick=async()=>{
    let a={};try{a=JSON.parse(decodeURIComponent(btn.dataset.action))}catch{}
    if(a.action==='download_template'){location.href='/api/template';return}
    if(a.action==='focus_upload'){els.file.click();return}
    if(a.action==='download_report'){if(!state.sessionId){toast('当前没有分析会话');return}location.href='/api/agent/report/'+encodeURIComponent(state.sessionId);return}
    if(a.action==='download_run_record'){if(!state.sessionId){toast('当前没有分析会话');return}location.href='/api/agent/run-record/'+encodeURIComponent(state.sessionId);return}
    addUser(a.label);
    await callAgent({action:a.action||'',scenario_type:a.scenario_type||'',material:a.material||'',year:a.year||'',path:a.path||'',failure_fraction:a.failure_fraction??'',inventory:a.inventory??'',message:a.label});
  })
}
function reset(){
  state.sessionId='';localStorage.removeItem('waterpulse_v5_session');state.file=null;els.messages.innerHTML='';els.welcome.style.display='block';document.body.classList.remove('chatting');setFile(null);els.input.value='';resize();
}

$('#attachBtn').onclick=()=>els.file.click();els.file.onchange=()=>setFile(els.file.files?.[0]);els.send.onclick=send;
els.input.addEventListener('input',resize);els.input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});$('#newChatBtn').onclick=reset;

async function fetchJsonWithTimeout(url, options={}, timeoutMs=8000){
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),timeoutMs);
  try{
    const r=await fetch(url,{...options,signal:controller.signal,cache:'no-store'});
    const d=await r.json();
    return {response:r,data:d};
  }finally{clearTimeout(timer)}
}

async function init(){
  const badge=$('#aiStatus');
  try{
    const {response:r,data:d}=await fetchJsonWithTimeout('/api/agent/status',{},5000);
    if(!r.ok) throw new Error('status '+r.status);
    if(!d.deepseek_configured){
      badge.classList.remove('online');
      badge.classList.add('offline');
      badge.innerHTML='<i></i><span>DeepSeek 待配置</span>';
    }else{
      // The Railway variable is already visible to the service.
      badge.classList.remove('offline');
      badge.classList.add('online');
      badge.innerHTML='<i></i><span>DeepSeek 已配置</span>';
      try{
        const {response:tr,data:td}=await fetchJsonWithTimeout('/api/deepseek/test',{},10000);
        if(tr.ok && td.ok){
          badge.classList.remove('offline');
          badge.classList.add('online');
          badge.innerHTML='<i></i><span>DeepSeek 已连接</span>';
        }else{
          badge.classList.remove('online');
          badge.classList.add('offline');
          badge.innerHTML='<i></i><span>DeepSeek 已配置 · 连接待确认</span>';
          console.warn('DeepSeek connection test:',td);
        }
      }catch(e){
        badge.classList.remove('online');
        badge.classList.add('offline');
        badge.innerHTML='<i></i><span>DeepSeek 已配置 · 连接待确认</span>';
        console.warn('DeepSeek connection test failed:',e);
      }
    }
  }catch(e){
    badge.classList.remove('online');
    badge.classList.add('offline');
    badge.innerHTML='<i></i><span>AI 服务暂未连接</span>';
    console.warn('AI status check failed:',e);
  }
  if(state.sessionId){
    showMessages();
    addAI({message:'欢迎回来。你可以继续提问或上传新的资料；如果想重新开始，点右上角“新对话”即可。',actions:[]});
  }
}

// Optional browser speech-to-text. It only fills the composer; no audio is uploaded.
(function setupSpeech(){
  const btn=document.querySelector('#micBtn');
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!btn)return;
  if(!SR){btn.style.display='none';return;}
  const rec=new SR();rec.lang='zh-CN';rec.interimResults=true;rec.continuous=false;
  let base='';
  btn.onclick=()=>{try{base=els.input.value.trim();btn.classList.add('listening');toast('正在听…');rec.start()}catch{}};
  rec.onresult=e=>{let text='';for(let i=e.resultIndex;i<e.results.length;i++)text+=e.results[i][0].transcript;els.input.value=(base?base+' ':'')+text;resize()};
  rec.onend=()=>btn.classList.remove('listening');
  rec.onerror=()=>{btn.classList.remove('listening');toast('语音输入暂不可用')};
})();

init();
