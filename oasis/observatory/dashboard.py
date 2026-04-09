"""Observatory dashboard — self-contained HTML page with inline CSS + JS."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Dashboard"])

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OASIS Observatory</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}
.header{background:#161b22;border-bottom:1px solid #30363d;padding:12px 24px;display:flex;align-items:center;justify-content:space-between}
.header h1{font-size:18px;color:#58a6ff}
.status{font-size:12px;padding:4px 10px;border-radius:12px;background:#238636;color:#fff}
.status.disconnected{background:#da3633}
.grid{display:grid;grid-template-columns:repeat(4,1fr);grid-template-rows:auto;gap:12px;padding:16px;max-width:1600px;margin:0 auto}
.panel{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;min-height:200px}
.panel h2{font-size:13px;color:#8b949e;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;border-bottom:1px solid #21262d;padding-bottom:6px}
.panel.wide{grid-column:span 2}
.panel.full{grid-column:span 4}
.metric{font-size:28px;font-weight:700;color:#58a6ff}
.metric-label{font-size:11px;color:#8b949e;margin-top:2px}
.metric-row{display:flex;gap:20px;flex-wrap:wrap}
.metric-card{flex:1;min-width:80px}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;color:#8b949e;padding:6px 8px;border-bottom:1px solid #21262d}
td{padding:6px 8px;border-bottom:1px solid #21262d}
tr:hover{background:#1c2128}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600}
.badge-green{background:#23863633;color:#3fb950}
.badge-yellow{background:#e3b34133;color:#e3b341}
.badge-red{background:#da363333;color:#f85149}
.log-entry{font-size:11px;font-family:monospace;padding:4px 0;border-bottom:1px solid #21262d;display:flex;gap:8px}
.log-type{color:#58a6ff;min-width:160px}
.log-time{color:#8b949e;min-width:80px}
.log-detail{color:#c9d1d9;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.alert-item{padding:8px;margin-bottom:6px;border-radius:4px;border-left:3px solid #da3633;background:#da363310;font-size:12px}
.alert-item.warning{border-left-color:#e3b341;background:#e3b34110}
#eventLog{max-height:300px;overflow-y:auto}
canvas{max-height:200px}
@media(max-width:1200px){.grid{grid-template-columns:repeat(2,1fr)}.panel.wide{grid-column:span 2}.panel.full{grid-column:span 2}}
@media(max-width:768px){.grid{grid-template-columns:1fr}.panel.wide,.panel.full{grid-column:span 1}}
</style>
</head>
<body>
<div class="header">
  <h1>OASIS Observatory</h1>
  <span class="status disconnected" id="wsStatus">Connecting...</span>
</div>
<div class="grid">
  <!-- Summary -->
  <div class="panel wide" id="summaryPanel">
    <h2>Platform Summary</h2>
    <div class="metric-row" id="summaryMetrics">
      <div class="metric-card"><div class="metric" id="mSessions">-</div><div class="metric-label">Sessions</div></div>
      <div class="metric-card"><div class="metric" id="mAgents">-</div><div class="metric-label">Agents</div></div>
      <div class="metric-card"><div class="metric" id="mTasks">-</div><div class="metric-label">Active Tasks</div></div>
      <div class="metric-card"><div class="metric" id="mTreasury">-</div><div class="metric-label">Treasury</div></div>
      <div class="metric-card"><div class="metric" id="mAlerts">-</div><div class="metric-label">Alerts</div></div>
    </div>
  </div>

  <!-- Session Timeline -->
  <div class="panel wide" id="timelinePanel">
    <h2>Session Timeline</h2>
    <canvas id="timelineChart"></canvas>
  </div>

  <!-- Agent Leaderboard -->
  <div class="panel wide" id="leaderboardPanel">
    <h2>Agent Leaderboard</h2>
    <table><thead><tr><th>#</th><th>Agent</th><th>Type</th><th>Reputation</th><th>Balance</th></tr></thead>
    <tbody id="leaderboardBody"></tbody></table>
  </div>

  <!-- Reputation Chart -->
  <div class="panel" id="reputationPanel">
    <h2>Reputation Trend</h2>
    <canvas id="reputationChart"></canvas>
  </div>

  <!-- Treasury Gauge -->
  <div class="panel" id="treasuryPanel">
    <h2>Treasury Balance</h2>
    <canvas id="treasuryChart"></canvas>
  </div>

  <!-- Fairness Monitor -->
  <div class="panel" id="fairnessPanel">
    <h2>Fairness Monitor</h2>
    <div id="fairnessContent"><p style="color:#8b949e;font-size:12px">Coordination flags and fairness data will appear here.</p></div>
  </div>

  <!-- Execution Heatmap -->
  <div class="panel" id="heatmapPanel">
    <h2>Execution Heatmap</h2>
    <div id="heatmapContent" style="font-size:12px;overflow-x:auto"><p style="color:#8b949e">Task assignments will appear here.</p></div>
  </div>

  <!-- Event Log -->
  <div class="panel full" id="eventLogPanel">
    <h2>Live Event Log</h2>
    <div id="eventLog"></div>
  </div>

  <!-- Alert Panel -->
  <div class="panel wide" id="alertPanel">
    <h2>Guardian Alerts</h2>
    <div id="alertContent"><p style="color:#8b949e;font-size:12px">No alerts.</p></div>
  </div>
</div>

<script>
(function(){
  const API = window.location.origin;
  const WS_URL = (location.protocol==='https:'?'wss://':'ws://') + location.host + '/ws/events';
  let ws = null;
  let reconnectTimer = null;
  const statusEl = document.getElementById('wsStatus');

  // --- WebSocket ---
  function connectWS(){
    if(ws && ws.readyState < 2) return;
    ws = new WebSocket(WS_URL);
    ws.onopen = ()=>{ statusEl.textContent='Connected'; statusEl.className='status'; };
    ws.onclose = ()=>{ statusEl.textContent='Disconnected'; statusEl.className='status disconnected'; scheduleReconnect(); };
    ws.onerror = ()=>{ ws.close(); };
    ws.onmessage = (e)=>{
      try{
        const evt = JSON.parse(e.data);
        if(evt.ping) return;
        addLogEntry(evt);
      }catch(err){}
    };
  }
  function scheduleReconnect(){ if(!reconnectTimer) reconnectTimer = setTimeout(()=>{ reconnectTimer=null; connectWS(); }, 3000); }

  function addLogEntry(evt){
    const el = document.getElementById('eventLog');
    const div = document.createElement('div');
    div.className = 'log-entry';
    const ts = new Date(evt.timestamp*1000).toLocaleTimeString();
    div.innerHTML = '<span class="log-time">'+ts+'</span><span class="log-type">'+evt.event_type+'</span><span class="log-detail">'+(evt.session_id||'')+' '+(evt.agent_did||'')+' '+JSON.stringify(evt.payload||{}).slice(0,120)+'</span>';
    el.prepend(div);
    while(el.children.length > 200) el.removeChild(el.lastChild);
  }

  // --- REST polling ---
  async function fetchJSON(path){ try{ const r=await fetch(API+path); return await r.json(); }catch(e){ return null; } }

  async function refreshSummary(){
    const d = await fetchJSON('/api/observatory/summary');
    if(!d) return;
    const ss = d.sessions_by_state||{};
    document.getElementById('mSessions').textContent = Object.values(ss).reduce((a,b)=>a+b,0);
    const aa = d.agents_by_type||{};
    document.getElementById('mAgents').textContent = Object.values(aa).reduce((a,b)=>a+b,0);
    document.getElementById('mTasks').textContent = d.tasks_in_progress||0;
    document.getElementById('mTreasury').textContent = (d.treasury_balance||0).toFixed(2);
    document.getElementById('mAlerts').textContent = d.active_alerts||0;
  }

  let lbChart=null, repChart=null, trsChart=null;

  async function refreshLeaderboard(){
    const d = await fetchJSON('/api/observatory/agents/leaderboard?limit=10');
    if(!d) return;
    const tbody = document.getElementById('leaderboardBody');
    tbody.innerHTML = d.map(a=>'<tr><td>'+a.rank+'</td><td>'+a.display_name+'</td><td><span class="badge badge-green">'+a.agent_type+'</span></td><td>'+a.reputation_score.toFixed(3)+'</td><td>'+a.total_balance.toFixed(1)+'</td></tr>').join('');
  }

  async function refreshReputation(){
    const d = await fetchJSON('/api/observatory/reputation/timeseries');
    if(!d||!d.length) return;
    const labels = d.map((_,i)=>i);
    const data = d.map(r=>r.new_score);
    const ctx = document.getElementById('reputationChart').getContext('2d');
    if(repChart) repChart.destroy();
    repChart = new Chart(ctx,{type:'line',data:{labels,datasets:[{label:'Reputation',data,borderColor:'#58a6ff',backgroundColor:'#58a6ff22',fill:true,tension:0.3}]},options:{responsive:true,plugins:{legend:{display:false}},scales:{x:{display:false},y:{ticks:{color:'#8b949e'},grid:{color:'#21262d'}}}}});
  }

  async function refreshTreasury(){
    const d = await fetchJSON('/api/observatory/treasury/timeseries');
    if(!d||!d.length) return;
    const labels = d.map((_,i)=>i);
    const data = d.map(r=>r.balance_after);
    const ctx = document.getElementById('treasuryChart').getContext('2d');
    if(trsChart) trsChart.destroy();
    trsChart = new Chart(ctx,{type:'line',data:{labels,datasets:[{label:'Balance',data,borderColor:'#3fb950',backgroundColor:'#3fb95022',fill:true,tension:0.3}]},options:{responsive:true,plugins:{legend:{display:false}},scales:{x:{display:false},y:{ticks:{color:'#8b949e'},grid:{color:'#21262d'}}}}});
  }

  async function refreshHeatmap(){
    const d = await fetchJSON('/api/observatory/execution/heatmap');
    if(!d||!d.rows||!d.rows.length){return;}
    const allTasks = new Set();
    d.rows.forEach(r=>Object.keys(r.tasks).forEach(t=>allTasks.add(t)));
    const tasks = [...allTasks].sort();
    let html='<table><thead><tr><th>Agent</th>'+tasks.map(t=>'<th>'+t.slice(-6)+'</th>').join('')+'</tr></thead><tbody>';
    d.rows.forEach(r=>{
      html+='<tr><td>'+r.agent_did.slice(-8)+'</td>';
      tasks.forEach(t=>{
        const s=r.tasks[t]||'-';
        const cls=s==='settled'?'badge-green':s==='failed'?'badge-red':'badge-yellow';
        html+='<td><span class="badge '+cls+'">'+s+'</span></td>';
      });
      html+='</tr>';
    });
    html+='</tbody></table>';
    document.getElementById('heatmapContent').innerHTML=html;
  }

  async function refreshTimeline(){
    const d = await fetchJSON('/api/observatory/sessions/timeline');
    if(!d||!d.length) return;
    const states=[...new Set(d.map(s=>s.state))];
    const colors=['#58a6ff','#3fb950','#e3b341','#f85149','#bc8cff','#79c0ff','#d2a8ff','#ff7b72','#ffa657'];
    const ctx = document.getElementById('timelineChart').getContext('2d');
    const datasets = states.map((st,i)=>({label:st,data:d.filter(s=>s.state===st).map(s=>({x:s.session_id,y:1})),backgroundColor:colors[i%colors.length]}));
    new Chart(ctx,{type:'bar',data:{labels:d.map(s=>s.session_id),datasets},options:{responsive:true,plugins:{legend:{labels:{color:'#8b949e'}}},scales:{x:{ticks:{color:'#8b949e'},grid:{color:'#21262d'}},y:{display:false}}}});
  }

  function refreshAll(){
    refreshSummary();
    refreshLeaderboard();
    refreshReputation();
    refreshTreasury();
    refreshHeatmap();
    refreshTimeline();
  }

  connectWS();
  refreshAll();
  setInterval(refreshAll, 15000);
})();
</script>
</body>
</html>"""


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve the self-contained Observatory dashboard."""
    return HTMLResponse(content=DASHBOARD_HTML)
