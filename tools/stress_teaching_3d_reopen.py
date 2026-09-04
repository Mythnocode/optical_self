#!/usr/bin/env python3
"""Repeatedly create/destroy the real teaching Quick3D view under a live renderer."""
from __future__ import annotations
import argparse, gc, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QEventLoop,QTimer,QObject
from PySide6.QtWidgets import QApplication,QMainWindow
from frontend_pyside.features.teaching.unified_workbench import ExperimentModel
from frontend_pyside.features.teaching.unified_quick3d import UnifiedTeachingQuick3DView

def wait(ms:int):
    loop=QEventLoop(); QTimer.singleShot(ms,loop.quit); loop.exec()

def rss():
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith('VmRSS:'): return float(line.split()[1])/1024
    return 0.0

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--cycles',type=int,default=10); ap.add_argument('--output',type=Path,default=ROOT/'assets_3d/reports/reopen_stress.json'); a=ap.parse_args()
    app=QApplication.instance() or QApplication(sys.argv)
    base=rss(); rows=[]
    for i in range(a.cycles):
        w=QMainWindow(); v=UnifiedTeachingQuick3DView(); w.setCentralWidget(v); w.resize(960,620)
        m=ExperimentModel(); m.mode='free'; v.set_model(m); w.show(); wait(1100 if i==0 else 650)
        root=v._quick.rootObject(); errors=[e.toString() for e in v._quick.errors()]
        assets=[] if root is None else [o for o in root.findChildren(QObject) if o.objectName().startswith('asset:')]
        row={'cycle':i+1,'rss_mib':rss(),'qml_errors':errors,'assets':len(assets),'ready':sum(bool(o.property('visualReady')) for o in assets),'failed':sum(bool(o.property('assetLoadFailed')) for o in assets)}
        rows.append(row)
        w.close(); v.deleteLater(); w.deleteLater(); app.processEvents(); wait(120); gc.collect(); app.processEvents()
        row['rss_after_close_mib']=rss()
    tail=[r['rss_after_close_mib'] for r in rows[-5:]]
    tail_growth=(max(tail)-min(tail)) if tail else 0.0
    total=rows[-1]['rss_after_close_mib']-base if rows else 0.0
    warm_start = rows[min(4, len(rows)-1)]['rss_after_close_mib'] if rows else base
    warm_growth = rows[-1]['rss_after_close_mib'] - warm_start if rows else 0.0
    checks={
      'all_cycles_qml_clean': all(not r['qml_errors'] for r in rows),
      'all_assets_ready': all(r['assets']==10 and r['ready']==10 and r['failed']==0 for r in rows),
      'tail_memory_plateau': tail_growth < 8.0,
      'warm_memory_growth_bounded': warm_growth < 8.0,
    }
    report={'status':'PASS' if all(checks.values()) else 'FAIL','baseline_rss_mib':base,'renderer_cache_init_growth_mib':total-warm_growth,'warm_growth_mib':warm_growth,'tail_span_mib':tail_growth,'checks':checks,'cycles':rows,'note':'Qt/Quick3D renderer and shader caches intentionally remain process-global; leak gating therefore starts after warm-up and checks the steady-state tail.'}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2)); return 0 if report['status']=='PASS' else 2
if __name__=='__main__': raise SystemExit(main())
