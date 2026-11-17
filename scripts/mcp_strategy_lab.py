#!/usr/bin/env python3
"""Multi-agent strategy research loop for the local stitched ASX:CDA data.

The MCP agents suggest hypotheses and review evidence. All performance numbers
are produced locally by the deterministic backtester, never by the model.
"""
from __future__ import annotations

import argparse, concurrent.futures, json, os, random, sqlite3, subprocess, sys, time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from strategy_57pct import BASELINE, required_warmup_candles, run, stats
from custom_indicator_engine import run_custom
from australian_super_fees import australian_super_member_direct_fee
from scan_codan_intervals import aggregate, load as load_view


# Immutable seed captured from reports/cda_1h_leader_immutable.md. It is
# evaluated on the active interval and offered as a mutation parent; the
# 1-hour report itself is never changed.
ONE_HOUR_WINNER = {
    "lookback": 8, "fast": 29, "slow": 88,
    "tp": 0.3654, "stop": 0.2120,
    "break_even_trigger": 0.0100, "break_even_lock": 0.0085,
    "profit_lock_trigger": 0.1935, "profit_lock": 0.0024,
    "trail_trigger": 0.0300, "trail_pct": 0.0204,
}

# Parameters used by the Android imitation.  The lab may mutate candidates,
# but it must retain enough history to compare them with this frozen rule.
APP_IMITATION = {"lookback": 10, "fast": 30, "slow": 137, "regime_ema": 89}


class MCPClient:
    def __init__(self, server: Path, gateway: str):
        env = os.environ.copy(); env["MULTI_MODEL_GATEWAY_URL"] = gateway
        self.proc = subprocess.Popen([sys.executable, str(server)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True, env=env)
        self.n = 0
        self.last_meta = {}
        self.call("initialize", {"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"strategy-lab","version":"1.0"}})
        self.notify("notifications/initialized", {})

    def notify(self, method, params):
        self.proc.stdin.write(json.dumps({"jsonrpc":"2.0","method":method,"params":params})+"\n"); self.proc.stdin.flush()

    def call(self, method, params):
        self.n += 1; self.proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":self.n,"method":method,"params":params})+"\n"); self.proc.stdin.flush()
        while True:
            row = self.proc.stdout.readline()
            if not row: raise RuntimeError("MCP server exited")
            response=json.loads(row)
            if response.get("id") == self.n:
                if "error" in response: raise RuntimeError(response["error"].get("message","MCP error"))
                return response.get("result",{})

    def ask(self, prompt, provider="local", max_tokens=700, model=None):
        arguments={"prompt":prompt,"provider":provider,"max_tokens":max_tokens}
        if model:
            arguments["model"] = model
        result=self.call("tools/call", {"name":"gateway_chat","arguments":arguments})
        self.last_meta = result.get("structuredContent", {}).get("routing", {}) or {}
        self.last_meta["model"] = result.get("structuredContent", {}).get("model")
        text = result.get("structuredContent",{}).get("text","") or result.get("content",[{}])[0].get("text","")
        # The gateway MCP bridge may return the complete OpenAI-compatible
        # envelope when a backend produces an empty message. Unwrap it here so
        # callers can distinguish an empty model response from useful text;
        # otherwise the MLX controller incorrectly skips its bounded retry and
        # records a misleading "unusable brief" fallback.
        if isinstance(text, str) and text.lstrip().startswith("{"):
            try:
                envelope = json.loads(text)
                choices = envelope.get("choices") if isinstance(envelope, dict) else None
                if isinstance(choices, list) and choices:
                    message = choices[0].get("message", {}) or {}
                    text = message.get("content") or message.get("reasoning_content") or ""
            except (TypeError, ValueError, AttributeError):
                pass
        return text

    def close(self):
        self.proc.terminate()


def candidate(rng: random.Random, parent: dict[str, Any] | None = None) -> dict[str, Any]:
    if parent:
        # Model proposals may contain only a subset of the optional exit
        # parameters. Inherit the deterministic baseline before mutation so
        # continuous research cannot crash on a missing key.
        p={**BASELINE, **parent}
        p["lookback"]=max(5,min(120,int(round(p["lookback"]+rng.gauss(0,8)))))
        p["fast"]=max(2,min(30,int(round(p["fast"]+rng.gauss(0,3)))))
        p["slow"]=max(p["fast"]+2,min(200,int(round(p["slow"]+rng.gauss(0,15)))))
        for key,lo,hi,sd in [("tp",.01,.50,.04),("stop",.01,.25,.025),("break_even_trigger",.01,.08,.01),("break_even_lock",0,.01,.002),("profit_lock_trigger",.04,.20,.02),("profit_lock",0,.04,.006),("trail_trigger",.03,.20,.02),("trail_pct",.005,.08,.01)]:
            p[key]=round(max(lo,min(hi,p[key]+rng.gauss(0,sd))),4)
        return p
    fast=rng.randint(2,30); slow=rng.randint(max(fast+2,10),200)
    return {"lookback":rng.randint(5,120),"fast":fast,"slow":slow,
            "tp":round(rng.uniform(.01,.50),4),"stop":round(rng.uniform(.01,.25),4),
            "break_even_trigger":round(rng.uniform(.01,.08),4),
            "break_even_lock":round(rng.uniform(0,.01),4),
            "profit_lock_trigger":round(rng.uniform(.04,.20),4),
            "profit_lock":round(rng.uniform(0,.04),4),
            "trail_trigger":round(rng.uniform(.03,.20),4),
            "trail_pct":round(rng.uniform(.005,.08),4)}


def evaluate(frame, params):
    """Score one run only when the imitation has enough causal warm-up history."""
    required = required_warmup_candles(params)
    _, trades, data=run(frame,params,200000,.95,2,0,fee_model=australian_super_member_direct_fee)
    result=stats(trades,data,200000)
    result["status"] = "FULL_WARMUP" if len(frame) >= required else "LIMITED_CACHE_WARMUP"
    result["available_warmup_candles"] = len(frame)
    result["required_warmup_candles"] = required
    score=result["total_return_pct"]-0.35*abs(result["max_drawdown_pct"])
    return {"params":params,"backtest":result,"score":round(score,4),"trade_reasons":{reason:sum(t.reason==reason for t in trades) for reason in sorted({t.reason for t in trades})}}


def agent_search(frame, seed, count, parents=None):
    rng=random.Random(seed); found=[]; parents=parents or []
    for _ in range(count):
        parent=rng.choice(parents) if parents and rng.random()<.75 else None
        p=candidate(rng,parent); found.append(evaluate(frame,p))
    return sorted(found,key=lambda x:x["score"],reverse=True)


def data_profile(frame):
    returns=frame.close.pct_change().dropna()
    return {"rows":len(frame),"start":str(frame.index.min()),"end":str(frame.index.max()),"unique_timestamps":int(frame.index.nunique()),"close_min":float(frame.close.min()),"close_max":float(frame.close.max()),"return_mean":float(returns.mean()),"return_std":float(returns.std()),"positive_bar_pct":float((returns>0).mean()),"median_abs_return":float(returns.abs().median())}


def load_cda_frame(source_db: Path, view: str, bars: int) -> pd.DataFrame:
    """Load only CDA's reconstructed 1h bars, optionally grouped upward."""
    frame = load_view(source_db, view)
    if frame.empty:
        raise ValueError(f"no candles found in {view}")
    if frame.index.duplicated().any():
        raise ValueError("duplicate candle timestamps are not allowed")
    frame = frame.sort_index()
    # The source database is CDA-only; this guard prevents accidentally
    # pointing the lab at a multi-symbol view in the future.
    if view == "stitched_backtest_candles":
        with sqlite3.connect(source_db) as db:
            symbols = {row[0] for row in db.execute("select distinct symbol from stitched_backtest_candles")}
        if symbols != {"CDA"}:
            raise ValueError(f"expected CDA-only source, found symbols: {sorted(symbols)}")
    if bars < 1:
        raise ValueError("--bars must be at least 1; the lab accepts 1h or higher aggregations only")
    return aggregate(frame, bars)


def extract_indicator_spec(text: str):
    """Extract only JSON matching the safe custom-indicator schema."""
    decoder=json.JSONDecoder()
    for start,ch in enumerate(text):
        if ch != '{': continue
        try: value,_=decoder.raw_decode(text[start:])
        except json.JSONDecodeError: continue
        if isinstance(value,dict) and isinstance(value.get('features'),list) and isinstance(value.get('entry'),dict) and isinstance(value.get('exit'),dict):
            return value
    return None


def safe_agent_review(text: str) -> dict[str, Any]:
    """Persist only the structured review, never model scratch reasoning."""
    decoder = json.JSONDecoder()
    for start, ch in enumerate(text):
        if ch != '{':
            continue
        try:
            value, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and any(k in value for k in ('hypothesis', 'evidence', 'failure_risks', 'next_data_grounded_improvement')):
            return {k: value.get(k) for k in ('hypothesis', 'evidence', 'failure_risks', 'next_data_grounded_improvement') if k in value}
    return {'status': 'UNSTRUCTURED_REVIEW', 'message': 'The provider did not return the required structured review.'}


def evaluate_custom(frame, spec):
    _,trades,data=run_custom(frame,spec,capital=200000,allocation=.95,slippage_bps=2)
    return {'spec':spec,'backtest':stats(trades,data,200000),
            'trade_reasons':{reason:sum(t.reason==reason for t in trades) for reason in sorted({t.reason for t in trades})}}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--source-db',type=Path,default=ROOT/'data/codan_screen_capture.sqlite3'); ap.add_argument('--view',default='stitched_candles'); ap.add_argument('--bars',type=int,default=1,choices=range(1,8),help='base CDA 1h bars grouped into 1h, 2h, 3h... session bars; never a lower interval'); ap.add_argument('--rounds',type=int,default=20); ap.add_argument('--continuous',action='store_true',help='run until Ctrl-C or the stop file exists'); ap.add_argument('--stop-file',type=Path); ap.add_argument('--agents',type=int,default=2); ap.add_argument('--candidates',type=int,default=1000); ap.add_argument('--gateway',default=os.environ.get('MULTI_MODEL_GATEWAY_URL','http://127.0.0.1:8788')); ap.add_argument('--mcp-server',type=Path,default=ROOT.parent/'multi-model-ai-gateway/ai/mcp_server.py'); ap.add_argument('--providers',default='local,nvidia',help='comma-separated MCP providers; both are used by default'); ap.add_argument('--run-dir',type=Path,default=ROOT/'strategy_lab_runs'); args=ap.parse_args()
    if (not args.continuous and args.rounds<1) or args.agents<1: ap.error('rounds and agents must be positive')
    providers=[x.strip() for x in args.providers.split(',') if x.strip()]
    if not providers or any(x not in {'local','nvidia','auto'} for x in providers): ap.error('--providers must contain local, nvidia, or auto')
    frame=load_cda_frame(args.source_db,args.view,args.bars); profile=data_profile(frame)
    baseline_warmup = max(required_warmup_candles(BASELINE), required_warmup_candles(APP_IMITATION))
    args.run_dir.mkdir(parents=True,exist_ok=True); run_dir=args.run_dir/time.strftime('%Y%m%d-%H%M%S'); run_dir.mkdir(); stop_file=args.stop_file or (run_dir/'STOP')
    run_meta={'source_db':str(args.source_db),'source_view':args.view,'symbol':'CDA','strategy_type':'local imitation of the frozen research rule','base_interval':'1h','aggregation_bars':args.bars,'effective_interval':f'{args.bars}h','seed_strategies':['BASELINE','ONE_HOUR_WINNER','APP_IMITATION'],'providers':providers,'agents':args.agents,'candidates':args.candidates,'continuous':args.continuous,'data_profile':profile,'available_warmup_candles':len(frame),'baseline_required_warmup_candles':baseline_warmup,'app_imitation_params':APP_IMITATION,'warmup_policy':'minimum maximum-lookback warm-up; no under-warmed candidate may be ranked'}
    (run_dir/'run.json').write_text(json.dumps(run_meta,indent=2))
    run_meta['warmup_status'] = 'FULL' if len(frame) >= baseline_warmup else 'LIMITED_CACHE'
    run_meta['effective_warmup_candles'] = min(len(frame), baseline_warmup)
    (run_dir/'run.json').write_text(json.dumps(run_meta,indent=2))
    db=sqlite3.connect(run_dir/'lab.sqlite3'); db.execute('create table experiments(id integer primary key, round integer, agent integer, score real, accepted integer, result_json text)'); db.commit()
    client=None
    try:
        client=MCPClient(args.mcp_server,args.gateway)
    except Exception as exc:
        print(f'MCP unavailable; continuing with deterministic local agents: {exc}',file=sys.stderr)
    best=None; parents=[dict(BASELINE),dict(ONE_HOUR_WINNER)]; rnd=0
    roles = [
        ("breakout_trend", "Test buying strength with breakout and medium-term trend confirmation."),
        ("regime_filter", "Test avoiding broad downtrends and range-bound conditions."),
        ("risk_exit", "Test mechanical stops, trailing stops, profit locks, and conservative sizing."),
        ("interval_selector", "Test nearby candle intervals and robust cross-interval behavior."),
        ("novel_indicator", "Design one causal composite indicator from the observed data profile and return it as safe JSON for local testing."),
    ]
    while args.continuous or rnd < args.rounds:
        rnd += 1
        if stop_file.exists(): break
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.agents) as pool:
            jobs=[pool.submit(agent_search,frame,100000+rnd*1000+i,args.candidates,parents) for i in range(args.agents)]
            results=[x for job in jobs for x in job.result()]
        # Permanent control: the untouched base strategy is evaluated every
        # round and competes with mutations, but is never modified.
        results.append(evaluate(frame,dict(BASELINE)))
        # Cross-interval seed: the immutable 1h leader competes on the active
        # interval and can be selected as a parent for 5h mutations.
        results.append(evaluate(frame,dict(ONE_HOUR_WINNER)))
        results.sort(key=lambda x:x['score'],reverse=True); top=results[:10]; parents=[x['params'] for x in top[:max(2,args.agents)]]
        for i,x in enumerate(results): db.execute('insert into experiments(round,agent,score,accepted,result_json) values(?,?,?,?,?)',(rnd,i//args.candidates,x['score'],1,json.dumps(x)))
        db.commit(); best=top[0] if best is None or top[0]['score']>best['score'] else best
        reviews=[]; custom_results=[]
        if client:
            for role, direction in roles:
                provider=providers[(rnd+len(reviews)) % len(providers)]
                prompt=("You are an independent quantitative research agent using only the supplied data profile and locally computed results. "
                        "Public Motion Trader-inspired principles are only hypotheses: trend following, buying strength through breakouts, medium-term rules, "
                        "mechanical trailing/profit protection, regime awareness, and disciplined risk. "
                        f"Your role is {role}: {direction} Do not invent results. Review these locally computed candidates and return concise JSON with "
                        "hypothesis, evidence, failure_risks, and the next data-grounded improvement. "
                        "You may propose a custom indicator specification, but it must use the safe indicator vocabulary and be tested locally before acceptance.\n"
                        "WARM-UP RULE: this is a local imitation, not a proprietary strategy. The app is confined to its cached candles; use all available candles as the seed when the theoretical warm-up is longer, label the result LIMITED_CACHE_WARMUP, and do not present it as fully warmed validation. Do not treat fee-only zero-trade results as performance.\n"
                        "DATA PROFILE (CDA, 1h base; effective interval "+str(args.bars)+"h):\n"+json.dumps(profile)+"\nTRAINING-ONLY CANDIDATES:\n"+
                        json.dumps(top[:3]))
                if role == "novel_indicator":
                    prompt += ("\nMANDATORY: design one data-grounded causal composite indicator. "
                               "End your response with one raw JSON object only (no markdown fence) containing name, features, entry, exit, stop, and take_profit. "
                               "Features may use only sma, ema, atr, roc, volatility, efficiency_ratio, slope, range_position, volume_ratio. "
                               "Use completed-bar values and execution at that candle close; do not claim it is profitable until the local evaluator tests it.")
                try:
                    text=client.ask(prompt,provider); reviews.append({'role':role,'provider':provider,'review':safe_agent_review(text)})
                    spec=extract_indicator_spec(text)
                    if spec:
                        try: custom_results.append({'role':role,'provider':provider,'evaluation':evaluate_custom(frame,spec)})
                        except Exception as exc: custom_results.append({'role':role,'provider':provider,'error':str(exc),'spec':spec})
                except Exception as exc: reviews.append({'role':role,'provider':provider,'text':f'MCP review failed: {exc}'})
        (run_dir/f'round-{rnd:03d}.json').write_text(json.dumps({'round':rnd,'symbol':'CDA','base_interval':'1h','aggregation_bars':args.bars,'effective_interval':f'{args.bars}h','top':top,'agent_reviews':reviews,'custom_indicator_evaluations':custom_results},indent=2,default=str))
        print(json.dumps({'round':rnd,'best_score':best['score'],'best_return':best['backtest']['total_return_pct'],'best_drawdown':best['backtest']['max_drawdown_pct']}))
    (run_dir/'summary.json').write_text(json.dumps({'best':best,'status':'stopped' if stop_file.exists() else 'completed','source_view':args.view,'symbol':'CDA','base_interval':'1h','aggregation_bars':args.bars,'effective_interval':f'{args.bars}h','data_profile':profile,'rows':len(frame),'providers':providers},indent=2,default=str))
    db.close()
    if client: client.close()
    print(json.dumps({'run_dir':str(run_dir),'status':'stopped' if stop_file.exists() else 'completed','best_score':best['score'] if best else None,'stop_file':str(stop_file)}))

if __name__=='__main__': main()
