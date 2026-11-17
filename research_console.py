#!/usr/bin/env python3
"""Local web console for the continuous MCP strategy lab."""
from __future__ import annotations

import json, os, signal, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT=Path(__file__).resolve().parent
RUNS=ROOT/'strategy_lab_runs'
PORT=int(os.environ.get('STRATEGY_CONSOLE_PORT','8790'))
STATE={'process':None,'started_at':None,'config':None}
LOCK=threading.Lock()
DAILY_SYMBOLS='CDA BHP CBA CSL WES RIO FMG GMG WOW ALL AMC ANZ NAB WBC MQG TCL CPU REA WTC XRO CAR SEK RMD MIN NXT STO S32 QAN COL TWE'

HTML=r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MCP Strategy Lab</title><style>
:root{color-scheme:dark;--bg:#080b12;--panel:#111827;--line:#273449;--muted:#93a4ba;--green:#47e0a1;--orange:#ffb86b;--red:#ff7188}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 80% 0,#1c2941 0,#080b12 42%);font:14px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;color:#eef4ff}main{max-width:1380px;margin:auto;padding:28px 22px}.eyebrow{color:var(--green);font-weight:700;letter-spacing:.12em;text-transform:uppercase;font-size:11px}h1{font-size:32px;margin:8px 0 4px}h2{font-size:16px;margin:0 0 14px}.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:330px 1fr;gap:16px;margin-top:24px}.panel{background:rgba(17,24,39,.88);border:1px solid var(--line);border-radius:14px;padding:18px;box-shadow:0 16px 50px #0004;margin-bottom:16px}.controls label{display:block;color:var(--muted);font-size:12px;margin:12px 0 6px}.controls input{width:100%;background:#0b1220;border:1px solid var(--line);color:#fff;padding:10px;border-radius:8px}.checks{display:flex;gap:10px;color:#fff!important}.checks label{margin:4px 0}.btn{border:0;border-radius:8px;padding:10px 14px;font-weight:700;cursor:pointer}.start{background:var(--green);color:#06110d}.stop{background:var(--red);color:#19070b}.ghost{background:#223047;color:#fff}.buttons{display:flex;gap:8px;margin-top:16px}.pill{display:inline-block;border-radius:999px;padding:5px 9px;font-size:11px;font-weight:700}.on{background:#113d32;color:var(--green)}.off{background:#3b1720;color:var(--red)}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.card{background:#0b1220;border:1px solid var(--line);border-radius:10px;padding:12px}.card span{display:block;color:var(--muted);font-size:11px}.card strong{font-size:20px;display:block;margin-top:6px}.tablewrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:12px}th,td{text-align:left;border-bottom:1px solid var(--line);padding:9px 7px;white-space:nowrap}th{color:var(--muted);font-weight:600}.good{color:var(--green)}.bad{color:var(--red)}pre{white-space:pre-wrap;color:#cbd5e1;font-size:11px;max-height:220px;overflow:auto}@media(max-width:850px){.grid{grid-template-columns:1fr}.cards{grid-template-columns:repeat(2,1fr)}}
</style></head><body><main><div class="eyebrow">Local-only · MCP clients · NVIDIA + MLX</div><h1>Strategy Research Lab</h1><p class="muted">Continuous, fee-inclusive search. Models propose; the local evaluator decides.</p><div class="grid"><aside><section class="panel controls"><h2>Research controls</h2><label>Run mode</label><select id="mode"><option value="continuous">Continuous CDA interval lab</option><option value="sweep">App-cache 1H–6H swarm sweep</option></select><label>Agents</label><input id="agents" type="number" value="2" min="1" max="12"><label>Candidates per worker / round</label><input id="candidates" type="number" value="1000" min="1" max="10000"><label>NVIDIA workers</label><input id="nvidiaAgents" type="number" value="9" min="0" max="9"><label>Data view</label><input id="view" value="stitched_candles"><div class="checks"><label><input id="local" type="checkbox" checked> Local MLX</label><label><input id="nvidia" type="checkbox" checked> NVIDIA</label></div><div class="buttons"><button class="btn start" onclick="startLab()">Start run</button><button class="btn stop" onclick="stopLab()">Stop</button></div><p id="action" class="muted"></p></section><section class="panel"><h2>Safety gates</h2><p class="muted">A$200,000 starting balance · AustralianSuper brokerage · 2 bps slippage · one position · no look-ahead.</p><p class="muted">The app-cache sweep keeps the equivalent of 42 five-hour candles: 210 hourly bars.</p></section></aside><section><section class="panel"><h2>Run status <span id="status" class="pill off">STOPPED</span></h2><div class="cards"><div class="card"><span>Round</span><strong id="round">—</strong></div><div class="card"><span>Best score</span><strong id="score">—</strong></div><div class="card"><span>Validation</span><strong id="validation">—</strong></div><div class="card"><span>Final test</span><strong id="test">—</strong></div></div><p id="meta" class="muted"></p></section><section class="panel"><h2>Interval sweep results</h2><pre id="sweep">No sweep yet.</pre></section><section class="panel"><h2>Best candidates</h2><div class="tablewrap"><table><thead><tr><th>Score</th><th>Train</th><th>Validation</th><th>Test</th><th>Trades</th><th>Parameters</th></tr></thead><tbody id="candidates"><tr><td colspan="6" class="muted">No run yet.</td></tr></tbody></table></div></section><section class="panel"><h2>Agent reviews / custom indicators</h2><pre id="reviews">Waiting for the lab…</pre></section><section class="panel"><h2>Gateway status</h2><pre id="gateway">Checking…</pre></section></section></div></main><script>
const $=id=>document.getElementById(id);const pct=x=>x==null?'—':Number(x).toFixed(2)+'%';
async function startLab(){let providers=[];if($('local').checked)providers.push('local');if($('nvidia').checked)providers.push('nvidia');if($('antigravity').checked)providers.push('antigravity');if(!providers.length)return $('action').textContent='Select at least one provider.';let r=await fetch('/api/start',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({mode:$('mode').value,agents:+$('agents').value,candidates:+$('candidates').value,agents_per_model:+$('nvidiaAgents').value,antigravity_agents:+$('nvidiaAgents').value,view:$('view').value,bars:5,source_db:'data/codan_app_59d.sqlite3',providers:providers.join(',')})});let d=await r.json();$('action').textContent=d.message||d.error||'';refresh()}
async function stopLab(){let r=await fetch('/api/stop',{method:'POST'});let d=await r.json();$('action').textContent=d.message||d.error||'';refresh()}
async function refresh(){let d=await (await fetch('/api/state')).json();$('status').textContent=d.running?'RUNNING':'STOPPED';$('status').className='pill '+(d.running?'on':'off');let b=d.best||{};$('round').textContent=d.round||'—';$('score').textContent=b.score??'—';$('validation').textContent=pct(b.validation&&b.validation.total_return_pct);$('test').textContent=pct(b.test&&b.test.total_return_pct);$('meta').textContent=d.run_dir?d.run_dir+' · providers: '+(d.providers||[]).join(', '):'';$('sweep').textContent=JSON.stringify(d.interval_results||{},null,2);let rows=(d.top||[]).map(x=>'<tr><td>'+x.score+'</td><td>'+pct(x.train.total_return_pct)+'</td><td>'+pct(x.validation.total_return_pct)+'</td><td>'+pct(x.test.total_return_pct)+'</td><td>'+x.test.trades+'</td><td><code>'+JSON.stringify(x.params)+'</code></td></tr>').join('');$('candidates').innerHTML=rows||'<tr><td colspan="6" class="muted">No candidates yet.</td></tr>';$('reviews').textContent=JSON.stringify({reviews:d.reviews||[],custom_indicators:d.custom_indicators||[]},null,2);$('gateway').textContent=JSON.stringify(d.gateway||{},null,2)}
refresh=async function(){let d=await (await fetch('/api/state')).json();let r=d.interval_results||[];$('status').textContent=d.running?'RUNNING':'STOPPED';$('status').className='pill '+(d.running?'on':'off');$('round').textContent=r.length?(r[r.length-1].cycle||'—'):'—';$('score').textContent=r.length?`${r.length} completed`:'—';$('validation').textContent=r.filter(x=>x.eligible).length+' eligible';$('test').textContent=r.length&&r[r.length-1].final_test?.total_return_pct!=null?pct(r[r.length-1].final_test.total_return_pct):'—';$('meta').textContent=d.run_dir?d.run_dir+' · '+(d.config?.mode||'sweep'):'';if(d.config?.mode==='sweep'||r.length)$('mode').value='sweep';$('sweep').textContent=r.length?r.map(x=>{let f=x.final_test||{};return `${x.cycle} · ${x.symbol} · ${x.interval} · ${x.rows} candles · ${x.nvidia_proposals} NVIDIA proposals · ${x.eligible?'ELIGIBLE':'REJECTED'} · return ${pct(f.total_return_pct)} · DD ${pct(f.max_drawdown_pct)} · trades ${f.trades??'—'}`}).join('\n'):'No sweep yet.';};setInterval(refresh,2500);refresh();</script></body></html>'''

HTML=HTML.replace('Validation</span>','Return</span>').replace('Final test</span>','Drawdown</span>')
HTML=HTML.replace('<option value="continuous">Continuous CDA interval lab</option><option value="sweep">App-cache 1H–6H swarm sweep</option>', '<option value="app" selected>US.APP paper strategy · 10-minute Moomoo</option>')
HTML=HTML.replace('<label><input id="nvidia" type="checkbox" checked> NVIDIA</label>', '<label><input id="nvidia" type="checkbox" checked> NVIDIA</label><label><input id="antigravity" type="checkbox" checked> Antigravity optimizer</label>')
HTML=HTML.replace('value="stitched_candles"', 'value="daily_candles (yfinance)" readonly')
HTML=HTML.replace('x.train.total_return_pct','x.backtest.total_return_pct').replace('x.validation.total_return_pct','x.backtest.total_return_pct').replace('x.test.total_return_pct','x.backtest.max_drawdown_pct').replace('x.test.trades','x.backtest.trades').replace("pct(b.validation&&b.validation.total_return_pct)","pct(b.backtest&&b.backtest.total_return_pct)").replace("pct(b.test&&b.test.total_return_pct)","pct(b.backtest&&b.backtest.max_drawdown_pct)")
HTML=HTML.replace("let rows=(d.top||[]).map(x=>'<tr><td>'+x.score+'</td><td>'+pct(x.backtest.total_return_pct)+'</td><td>'+pct(x.backtest.total_return_pct)+'</td><td>'+pct(x.backtest.max_drawdown_pct)+'</td><td>'+x.backtest.trades+'</td><td><code>'+JSON.stringify(x.params)+'</code></td></tr>').join('');", "let rows=(d.top||[]).map(x=>'<tr><td>'+x.score+'</td><td>'+pct(x.backtest.total_return_pct)+'</td><td>'+pct(x.backtest.max_drawdown_pct)+'</td><td>'+x.backtest.trades+'</td><td><code>'+JSON.stringify(x.params)+'</code></td></tr>').join('');")
HTML=HTML.replace('<th>Train</th><th>Validation</th><th>Test</th>','<th>Return</th><th>Drawdown</th>')
HTML=HTML.replace('value="4" min="1" max="12"','value="2" min="1" max="12"').replace('value="100" min="1" max="1000"','value="1000" min="1" max="10000"')
HTML=HTML.replace('<section class="panel"><h2>Best candidates', '<section class="panel"><h2>Daily research</h2><pre id="daily">Not running.</pre></section><section class="panel"><h2>Five-step decomposition</h2><pre id="decomposition">Waiting for the MLX controller…</pre></section><section class="panel"><h2>Best candidates')
HTML=HTML.replace('</body></html>', '<script>async function refreshDaily(){let d=await (await fetch("/api/state")).json();let el=$("daily");if(!el)return;let s=d.daily_status;let r=s&&s.last_result_details;let mh=s?.nvidia_model_health||{};let ah=s?.antigravity_health||{};let health=Object.entries(mh).map(([m,x])=>`${m}: ${x.successes||0} ok / ${x.failures||0} fail / ${x.local_fallbacks||0} fallback · ${x.last_route||"—"}`).join("\\n");let ag=ah.requests!=null?`\\nAntigravity optimizer: ${ah.requests||0} requests · ${ah.successes||0} ok · ${ah.failures||0} fail · ${ah.invalid_responses||0} invalid · ${ah.last_latency_ms??"—"} ms`:"";el.textContent=s?`${s.state} · ${s.completed}/${s.total} symbols · ${s.years} year · ${s.database}\\nPhase: ${s.phase||"—"} · current: ${s.current_symbol||"—"} · generation: ${s.generation??"—"}/${s.generations??"—"}\\nPID ${s.pid}\\n${s.last_result||"Waiting for first completed symbol…"}${r?`\\nLatest: ${r.symbol} · ${r.status||"RESULT"} · ${r.metric_source||"—"} · return ${r.return_pct??"—"}% · DD ${r.drawdown_pct??"—"}% · trades ${r.trades??"—"} · baseline ${r.baseline_return_pct??"—"}%`:""}${s.nvidia_requests!=null?`\\nNVIDIA gateway: ${s.nvidia_requests} requests · ${s.nvidia_failures} failures · ${s.nvidia_inflight} active`:""}${ag}${health?`\\n\\nObserved model health:\\n${health}`:""}`:"Not running.";let dec=$("decomposition");if(dec){let f=s?.decomposition_framework||{};dec.textContent=f.step_1_understand_objective?`01 Understand objective\\n${f.step_1_understand_objective.objective}\\n\\n02 Identify independent subtasks\\n${(f.step_2_identify_independent_subtasks||[]).map(x=>x.id+": "+x.question).join("\\n")}\\n\\n03 Assign specialization\\n${Object.entries(f.step_3_assign_specialization||{}).map(([k,v])=>k+": "+v).join("\\n")}\\n\\n04 Define expected outputs\\n${Object.entries(f.step_4_define_expected_outputs||{}).map(([k,v])=>k+": "+v).join("\\n")}\\n\\n05 Plan aggregation\\n${(f.step_5_plan_aggregation||[]).map((x,i)=>(i+1)+". "+x).join("\\n")}`:"Waiting for the MLX controller…";}let g=$("gateway");let gs=d.gateway?.stats||{};let nb=d.gateway?.backends?.nvidia||{};if(g)g.textContent=`Gateway\\nNVIDIA route: ${nb.configured?"configured":"unavailable"} · active: ${nb.inflight??"—"}\\nRequests: ${gs.nvidia_requests??"—"} · failures: ${gs.nvidia_failures??"—"} · timeouts: ${gs.nvidia_timeouts??"—"}\\nLast NVIDIA error: ${gs.nvidia_last_error||"none"}\\nLatency: ${gs.nvidia_latency_ms??"—"} ms\\nLocal requests: ${gs.local_requests??"—"} · local failures: ${gs.local_failures??"—"}\\nLast local error: ${gs.local_last_error||"none"}\\nModels: ${(nb.free_models||[]).join(", ")}`;}setInterval(refreshDaily,2500);refreshDaily();</script></body></html>')
HTML=HTML.replace('</body></html>', '<script>async function refreshControllerHealth(){try{let d=await (await fetch("/api/state")).json();let s=d.daily_status||{};let h=s.local_controller_health||{};let el=document.getElementById("daily");if(el&&h.requests!=null)el.textContent+="\\nMLX controller telemetry: "+(h.requests||0)+" requests · "+(h.successes||0)+" ok · "+(h.failures||0)+" fail · "+(h.fallbacks||0)+" fallback · "+(h.last_latency_ms??"—")+" ms"}catch(e){}}setInterval(refreshControllerHealth,2500);refreshControllerHealth();</script></body></html>')
HTML=HTML.replace('<section class="panel"><h2>Gateway status</h2>', '<section class="panel"><h2>Supervisor status</h2><pre id="supervisor">Checking…</pre></section><section class="panel"><h2>Gateway status</h2>')
HTML=HTML.replace('</body></html>', '<script>async function refreshSupervisor(){try{let d=await (await fetch("/api/state")).json();let s=d.supervisor_status||{};let g=s.gateway||{};let el=document.getElementById("supervisor");if(el)el.textContent=`${s.state||"—"} · cycle ${s.cycle??"—"} · child ${s.child_pid??"—"}\nRestarts: ${s.restart_count??0} · consecutive failures: ${s.consecutive_failures??0}\nRuntime age: ${s.runtime_age_seconds==null?"—":Number(s.runtime_age_seconds).toFixed(1)+"s"}\nGateway: ${g.reachable==null?"—":g.reachable?"reachable":"unreachable"} · NVIDIA failures: ${g.nvidia_failures??"—"}\nLast error: ${s.last_error||g.error||"none"}`} }catch(e){}}setInterval(refreshSupervisor,2500);refreshSupervisor();</script></body></html>')

def latest_run():
    dirs=sorted([p for p in RUNS.glob('*') if p.is_dir()])
    return dirs[-1] if dirs else None


def dashboard_review(item):
    """Never send provider scratch reasoning to the browser."""
    safe = {'role': item.get('role'), 'provider': item.get('provider')}
    review = item.get('review')
    if isinstance(review, dict):
        safe['review'] = review
    elif item.get('text'):
        safe['review'] = {'status': 'LEGACY_RAW_REVIEW_HIDDEN', 'message': 'Raw provider reasoning is hidden. New runs store structured reviews only.'}
    else:
        safe['review'] = {'status': 'NO_REVIEW'}
    return safe

def external_lab_pid():
    """Find a sweep launched by a previous console process."""
    try:
        output = subprocess.check_output(['pgrep', '-f', str(ROOT / 'scripts/sweep_app_intervals.py')], text=True)
        for line in output.splitlines():
            pid = int(line.strip())
            if pid != os.getpid():
                return pid
    except (OSError, ValueError, subprocess.CalledProcessError):
        pass
    return None


def external_daily_pid():
    """Find a daily-candle lab launched outside this console process."""
    try:
        output = subprocess.check_output(['pgrep', '-f', 'multi_symbol_strategy_lab.py'], text=True)
        for line in output.splitlines():
            pid = int(line.strip())
            if pid != os.getpid():
                return pid
    except (OSError, ValueError, subprocess.CalledProcessError):
        pass
    return None


def external_daily_wrapper_pid():
    """Find the parent that restarts daily mutation cycles."""
    try:
        output = subprocess.check_output(['pgrep', '-f', 'continuous_daily_research.py'], text=True)
        for line in output.splitlines():
            pid = int(line.strip())
            if pid != os.getpid():
                return pid
    except (OSError, ValueError, subprocess.CalledProcessError):
        pass
    return None


def external_app_pid():
    try:
        output = subprocess.check_output(['pgrep', '-f', str(ROOT / 'scripts/app_strategy_lab.py')], text=True)
        for line in output.splitlines():
            pid = int(line.strip())
            if pid != os.getpid():
                return pid
    except (OSError, ValueError, subprocess.CalledProcessError):
        pass
    return None


def daily_status(pid):
    if pid is None:
        return None
    try:
        command = subprocess.check_output(['ps', '-p', str(pid), '-o', 'command='], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    if 'multi_symbol_strategy_lab.py' not in command:
        return None
    import shlex
    parts = shlex.split(command)
    try:
        start = parts.index('--symbols') + 1
        end = parts.index('--years') if '--years' in parts else len(parts)
        symbols = [item.replace(',', ' ').upper() for item in parts[start:end] if item.strip()]
    except (ValueError, IndexError):
        symbols = []
    run = latest_run()
    completed = []
    if run:
        # A symbol's final result is written as ``SYMBOL.json``.  Generation
        # snapshots are evidence files, not completed symbols and must not
        # inflate progress or become the displayed latest result.
        completed = [
            p for p in run.glob('*.json')
            if p.stem not in {'run', 'summary', 'runtime_status'}
            and '-generation-' not in p.stem
        ]
        completed.sort(key=lambda p: p.stat().st_mtime)
    last_result = completed[-1].stem if completed else None
    last_result_details = None
    if completed:
        try:
            item = json.loads(completed[-1].read_text())
            final_stats = item.get('final_test', {}).get('stats', {}) if isinstance(item.get('final_test'), dict) else {}
            train_stats = item.get('best_train', {}).get('stats', {}) if isinstance(item.get('best_train'), dict) else {}
            stats = final_stats or train_stats
            last_result_details = {
                'symbol': item.get('symbol'),
                'status': item.get('status') or ('COMPLETED' if final_stats else 'INCOMPLETE'),
                'metric_source': 'final_test' if final_stats else ('best_train' if train_stats else None),
                'return_pct': stats.get('total_return_pct'),
                'drawdown_pct': stats.get('max_drawdown_pct'),
                'trades': stats.get('trades'),
                'baseline_return_pct': (item.get('baseline_test', {}).get('stats', {}).get('total_return_pct')
                                       if isinstance(item.get('baseline_test'), dict) else None),
            }
        except (OSError, json.JSONDecodeError):
            pass
    runtime = {}
    if run and (run / 'runtime_status.json').exists():
        try:
            runtime = json.loads((run / 'runtime_status.json').read_text())
        except (OSError, json.JSONDecodeError):
            pass
    # The runtime record is authoritative for the active symbol/generation;
    # completed-symbol progress is derived only from final SYMBOL.json files.
    return {
        'state': 'RUNNING', 'pid': pid, 'completed': len(completed),
        'total': len(symbols), 'years': parts[parts.index('--years') + 1] if '--years' in parts else '?',
        'database': parts[parts.index('--db') + 1] if '--db' in parts else '?',
        'run_dir': str(run) if run else None, 'last_result': last_result,
        'last_result_details': last_result_details,
        'phase': runtime.get('phase'), 'current_symbol': runtime.get('symbol'),
        'symbol_index': runtime.get('symbol_index'), 'generation': runtime.get('generation'),
        'generations': runtime.get('generations'),
        'controller': runtime.get('controller'),
        'agentic_loop': runtime.get('agentic_loop'),
        'decomposition_framework': runtime.get('decomposition_framework', {}),
        'memory_file': runtime.get('memory_file'), 'memory_symbols': runtime.get('memory_symbols', 0),
        'nvidia_model_health': runtime.get('nvidia_model_health', {}),
        'local_controller_health': runtime.get('local_controller_health', {}),
        'antigravity_health': runtime.get('antigravity_health', {}),
    }

def read_state():
    run=latest_run(); attached_pid=external_lab_pid(); daily_pid=external_daily_pid(); wrapper_pid=external_daily_wrapper_pid(); app_pid=external_app_pid(); process_running=STATE['process'] is not None and STATE['process'].poll() is None
    app_status_file=RUNS/'app_runtime_status.json'
    app_status={}
    if app_status_file.exists():
        try: app_status=json.loads(app_status_file.read_text())
        except (OSError, json.JSONDecodeError): pass
    out={'running':process_running or attached_pid is not None or daily_pid is not None or wrapper_pid is not None or app_pid is not None,'lab_pid':attached_pid,'app_pid':app_pid,'daily_status':daily_status(daily_pid or wrapper_pid),'app_status':app_status,'run_dir':str(run) if run else None}
    out['config']=STATE.get('config') or {}
    supervisor_file=RUNS/'supervisor_status.json'
    if supervisor_file.exists():
        try:
            out['supervisor_status']=json.loads(supervisor_file.read_text())
        except (OSError, json.JSONDecodeError):
            out['supervisor_status']={'state':'UNREADABLE'}
    if not run:return out
    meta=run/'run.json'
    if meta.exists():
        try: out.update(json.loads(meta.read_text()))
        except json.JSONDecodeError: pass
    summary=run/'summary.json'
    if summary.exists():
        try: out.update(json.loads(summary.read_text()))
        except json.JSONDecodeError: pass
    progress=run/'progress.json'
    if progress.exists():
        try: out.update(json.loads(progress.read_text()))
        except json.JSONDecodeError: pass
    if isinstance(out.get('results'), list):
        out['interval_results'] = [
            {'symbol': item.get('symbol'), 'interval': item.get('interval'), 'rows': item.get('rows'),
             'nvidia_proposals': item.get('nvidia_proposals'),
             'final_test': item.get('final_test', {}).get('stats') if isinstance(item.get('final_test'), dict) else None,
             'eligible': bool(item.get('selected_validation'))}
            for item in out['results']
        ]
    rounds=sorted(run.glob('round-*.json'))
    for candidate in reversed(rounds):
        try:
            item=json.loads(candidate.read_text())
            out.update({'round':item.get('round'),'top':item.get('top',[]),'reviews':[dashboard_review(r) for r in item.get('agent_reviews',[])],'custom_indicators':item.get('custom_indicator_evaluations',[])})
            if item.get('top'): out['best']=item['top'][0]
            if not out.get('providers'):
                out['providers']=sorted({r.get('provider') for r in item.get('agent_reviews',[]) if r.get('provider')})
            break
        except (json.JSONDecodeError,OSError):
            continue
    out['running']=(STATE['process'] is not None and STATE['process'].poll() is None) or external_lab_pid() is not None or external_daily_pid() is not None or external_daily_wrapper_pid() is not None or external_app_pid() is not None
    return out

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send_json(self,value,code=200):
        raw=json.dumps(value,default=str).encode(); self.send_response(code); self.send_header('content-type','application/json'); self.send_header('cache-control','no-store, max-age=0'); self.send_header('content-length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        if urlparse(self.path).path=='/api/state':
            state=read_state()
            try:
                import urllib.request
                with urllib.request.urlopen(os.environ.get('MULTI_MODEL_GATEWAY_URL','http://127.0.0.1:8788')+'/api/status',timeout=8) as r: state['gateway']=json.loads(r.read())
            except Exception as e: state['gateway']={'error':str(e)}
            if state.get('daily_status') and isinstance(state.get('gateway'), dict):
                stats = state['gateway'].get('stats', {})
                backend = state['gateway'].get('backends', {}).get('nvidia', {})
                state['daily_status'].update({
                    'nvidia_requests': stats.get('nvidia_requests'),
                    'nvidia_failures': stats.get('nvidia_failures'),
                    'nvidia_inflight': backend.get('inflight'),
                    'supervisor_status': state.get('supervisor_status', {}),
                })
            return self.send_json(state)
        raw=HTML.encode(); self.send_response(200); self.send_header('content-type','text/html; charset=utf-8'); self.send_header('cache-control','no-store, max-age=0'); self.send_header('content-length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_POST(self):
        global STATE
        path=urlparse(self.path).path
        if path=='/api/start':
            with LOCK:
                if (STATE['process'] is not None and STATE['process'].poll() is None) or external_lab_pid() is not None or external_daily_pid() is not None or external_daily_wrapper_pid() is not None or external_app_pid() is not None:return self.send_json({'error':'lab already running'},409)
                length=int(self.headers.get('content-length','0')); body=json.loads(self.rfile.read(length) or '{}'); providers='nvidia,antigravity'
                bars=max(1,min(7,int(body.get('bars',5))))
                source_db=Path(str(body.get('source_db','data/codan_app_59d.sqlite3')))
                if not source_db.is_absolute(): source_db=ROOT/source_db
                if source_db != ROOT/'data/codan_app_59d.sqlite3':
                    return self.send_json({'error':'console is restricted to the app cache data source'},400)
                mode=str(body.get('mode','app'))
                if mode != 'app':
                    return self.send_json({'error':'the mutation console is now restricted to the US.APP 10-minute paper strategy'},400)
                cmd=[sys.executable,str(ROOT/'scripts/app_strategy_lab.py'),'--db',str(ROOT.parent/'quant_dashboard.sqlite3'),'--agents',str(max(1,min(4,int(body.get('agents',2))))),'--candidates',str(max(1,min(1000,int(body.get('candidates',100))))),'--providers',providers,'--continuous']
                RUNS.mkdir(exist_ok=True); STATE['process']=subprocess.Popen(cmd,cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); STATE['started_at']=time.time(); STATE['config']=body
                return self.send_json({'message':'continuous lab started','pid':STATE['process'].pid,'command':cmd})
        if path=='/api/stop':
            with LOCK:
                p=STATE.get('process')
                external_pid=external_lab_pid()
                daily_pid=external_daily_pid()
                daily_wrapper_pid=external_daily_wrapper_pid()
                app_pid=external_app_pid()
                run=latest_run()
                if run:
                    (run/'STOP').touch()
                (RUNS/'STOP_DAILY').touch()
                if p is not None and p.poll() is None:
                    p.send_signal(signal.SIGINT)
                    return self.send_json({'message':'stop requested','run_dir':str(run) if run else None})
                if external_pid is not None:
                    os.kill(external_pid, signal.SIGINT)
                    return self.send_json({'message':'stop requested','pid':external_pid,'run_dir':str(run) if run else None})
                if daily_pid is not None:
                    os.kill(daily_pid, signal.SIGINT)
                    return self.send_json({'message':'stop requested','pid':daily_pid,'run_dir':str(run) if run else None})
                if daily_wrapper_pid is not None:
                    os.kill(daily_wrapper_pid, signal.SIGINT)
                    return self.send_json({'message':'stop requested','pid':daily_wrapper_pid,'run_dir':str(run) if run else None})
                if app_pid is not None:
                    os.kill(app_pid, signal.SIGINT)
                    return self.send_json({'message':'stop requested','pid':app_pid,'run_dir':str(run) if run else None})
                return self.send_json({'message':'lab is not running'})
        self.send_json({'error':'not found'},404)

if __name__=='__main__':
    print(f'Strategy console: http://127.0.0.1:{PORT}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
