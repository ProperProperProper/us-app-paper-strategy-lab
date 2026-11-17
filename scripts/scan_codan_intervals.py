#!/usr/bin/env python3
"""Compare strategy performance after aggregating stitched ASX:CDA bars."""
from __future__ import annotations
import argparse, json, sqlite3, sys
from pathlib import Path
from datetime import time
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from strategy_57pct import BASELINE, optimize, run, stats

def load(db_path, view):
    with sqlite3.connect(db_path) as db:
        frame = pd.read_sql_query(f"select timestamp_local,open,high,low,close from {view} order by timestamp_local",db,parse_dates=['timestamp_local'])
    if frame['timestamp_local'].duplicated().any():
        raise ValueError('duplicate candle timestamps are not allowed')
    return frame.set_index('timestamp_local')

def aggregate(frame, bars):
    x=frame.copy()
    if bars == 1: return x
    parts=[]
    for day, g in x.groupby(x.index.date):
        g=g.sort_index()
        if bars == 0:
            row=pd.DataFrame({'open':[g.open.iloc[0]],'high':[g.high.max()],'low':[g.low.min()],'close':[g.close.iloc[-1]]},index=[pd.Timestamp(day)])
            parts.append(row); continue
        # Accept both Sydney-local labels seen in the source data: 09:00-15:00
        # outside daylight saving and 10:00-16:00 during daylight saving.
        hours = {t.hour for t in g.index}
        session_start = 9 if set(range(9, 15)).issubset(hours) else 10 if set(range(10, 16)).issubset(hours) else None
        if session_start is None:
            continue
        g=g[g.index.hour.isin(range(session_start, session_start + 6))].sort_index().iloc[:6]
        for start in range(0,len(g)-bars+1,bars):
            q=g.iloc[start:start+bars]
            # q's final hourly bar closes one hour after its timestamp. Use
            # that completion time for causal signal timing.
            completed_at = q.index[-1] + pd.Timedelta(hours=1)
            parts.append(pd.DataFrame({'open':[q.open.iloc[0]],'high':[q.high.max()],'low':[q.low.min()],'close':[q.close.iloc[-1]]},index=[completed_at]))
    return pd.concat(parts).sort_index() if parts else pd.DataFrame(columns=frame.columns)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--db',type=Path,default=ROOT/'data/codan_screen_capture.sqlite3'); ap.add_argument('--view',default='stitched_candles'); ap.add_argument('--trials',type=int,default=300); ap.add_argument('--out',type=Path,default=ROOT/'reports/codan_interval_scan.json'); a=ap.parse_args()
    raw=load(a.db,a.view); results=[]
    for bars,name in [(1,'1h'),(2,'2h'),(3,'3h'),(4,'4h'),(5,'5h'),(0,'1d')]:
        candles=aggregate(raw,bars)
        if len(candles)<40: continue
        _,tr,data=run(candles,dict(BASELINE),100000,.95,2,0)
        base=stats(tr,data,100000)
        top=optimize(candles,dict(BASELINE),100000,.95,2,0,trials=a.trials)
        best=max(top,key=lambda r:(r['stats']['total_return_pct'],r['stats']['trades'])) if top else None
        results.append({'interval':name,'rows':len(candles),'baseline':base,'best':best})
    a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps({'view':a.view,'results':results},indent=2,default=str))
    for r in results:
        b=r['best']['stats'] if r['best'] else {}
        print(r['interval'],r['rows'],'baseline',r['baseline']['total_return_pct'],r['baseline']['trades'],'best',b.get('total_return_pct'),b.get('trades'),b.get('max_drawdown_pct'),r['best']['params'] if r['best'] else None)

if __name__=='__main__': main()
