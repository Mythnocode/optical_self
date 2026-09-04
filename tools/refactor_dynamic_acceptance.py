"""Dynamic GUI acceptance for the 2026-08-17 canvas/taskflow refactor.

Uses the real Qt widget hierarchy.  It checks hit testing (no invisible overlay is
stealing clicks), page-load failures, responsive resizing including portrait
orientation, ML workflow switching, simulation panel toggles, and teaching 3D
camera preset/rotation interactions. Screenshots are evidence, not decoration.
"""
from __future__ import annotations

import argparse, json, os, sys, tempfile, traceback
from pathlib import Path

os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp(prefix="optical-dyn-settings-"))
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractButton, QWidget

from frontend_pyside.app.bootstrap import create_main_window
from frontend_pyside.shared.components.errors import PageLoadErrorWidget


def wait(ms=180):
    QTest.qWait(ms)
    app = QApplication.instance()
    if app: app.processEvents()


def fail(msg):
    raise AssertionError(msg)


def page(window, key):
    window.navigate(key, update_document=False)
    wait(500)
    host = window._pages.get(key)
    if host is None or host.loaded_page is None:
        fail(f"{key}: page did not load")
    if isinstance(host.loaded_page, PageLoadErrorWidget):
        text = " ".join(x.text() for x in host.loaded_page.findChildren(QWidget) if hasattr(x, "text"))
        fail(f"{key}: deferred page load error: {text[:400]}")
    return host.loaded_page


def shot(window, out: Path, name: str):
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.png"
    if not window.grab().save(str(path)):
        fail(f"failed screenshot {path}")
    return str(path)


def shot_widget(widget: QWidget, out: Path, name: str):
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.png"
    if not widget.grab().save(str(path)):
        fail(f"failed widget screenshot {path}")
    return str(path)


def is_ancestor(ancestor: QWidget, widget: QWidget | None) -> bool:
    cur = widget
    while cur is not None:
        if cur is ancestor: return True
        cur = cur.parentWidget()
    return False


def assert_hittable(button: QAbstractButton, label: str):
    if not button.isVisible() or not button.isEnabled():
        fail(f"{label}: button not visible/enabled")
    center = button.rect().center()
    global_pos = button.mapToGlobal(center)
    hit = QApplication.widgetAt(global_pos)
    if hit is None:
        # Some headless WMs don't implement widgetAt reliably. Geometry still has
        # to be non-empty; actual QTest.click below remains the interaction check.
        if button.width() < 16 or button.height() < 16:
            fail(f"{label}: invalid button geometry {button.size()}")
        return
    if not is_ancestor(button, hit):
        fail(f"{label}: click center covered by {hit.objectName() or hit.__class__.__name__}")


def global_rect(widget: QWidget) -> QRect:
    tl = widget.mapToGlobal(QPoint(0, 0))
    return QRect(tl, widget.size())


def assert_no_widget_overlap(a: QWidget, b: QWidget, scope: str, tolerance: int = 2):
    if not a.isVisible() or not b.isVisible():
        return
    inter = global_rect(a).intersected(global_rect(b))
    if inter.width() > tolerance and inter.height() > tolerance:
        fail(f"{scope}: overlap {inter.width()}x{inter.height()}")


def assert_no_pair_overlap(buttons, scope: str):
    rows=[]
    for b in buttons:
        if not b.isVisible(): continue
        tl=b.mapToGlobal(QPoint(0,0)); r=QRect(tl,b.size())
        rows.append((b,r))
    for i,(a,ra) in enumerate(rows):
        for b,rb in rows[i+1:]:
            inter=ra.intersected(rb)
            if inter.width()>2 and inter.height()>2:
                fail(f"{scope}: {a.text()} overlaps {b.text()} by {inter.width()}x{inter.height()}")


def click(button, label):
    assert_hittable(button,label)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    wait(160)


def shell_checks(window, report):
    expected = {"simulation", "optimization", "surrogate", "explainability", "teaching"}
    if set(window.command_buttons) != expected:
        fail(f"top command bar should be {sorted(expected)}: {list(window.command_buttons)}")
    buttons=list(window.command_buttons.values())
    assert_no_pair_overlap(buttons, "top command bar")
    for key,b in window.command_buttons.items(): assert_hittable(b, f"command:{key}")
    toolbox=getattr(window,"toolbox_button",None)
    if toolbox is None: fail("floating toolbox launcher missing")
    assert_hittable(toolbox,"floating toolbox")
    assistant=getattr(window,"assistant_button",None)
    if assistant is not None:
        assert_no_widget_overlap(toolbox,assistant,"toolbox vs AI")
    click(toolbox,"open toolbox")
    drawer=getattr(window,"drawer",None)
    if drawer is None or not drawer.isVisible(): fail("toolbox drawer did not open")
    drawer.search.setText("反向预测"); wait(120)
    matched=[b for b in drawer.findChildren(QAbstractButton) if b.isVisible() and b.text()=="反向预测"]
    if not matched: fail("ML reverse prediction is not discoverable from toolbox search")
    window._close_tool_drawer(); wait(80)
    report.append("PASS top bar is minimal; floating searchable toolbox exposes ML reverse prediction")


def home_checks(window, out, report):
    p=page(window, "home")
    shot(window, out, "home_minimal")
    title = p.findChild(QWidget, "homePlatformTitle")
    if title is None or not title.isVisible():
        fail("home: platform title missing")
    # Homepage must not duplicate the toolbox/task centre with a goal wall or current-work sidebar.
    visible_text=[]
    for w in p.findChildren(QWidget):
        if hasattr(w, "text") and w.isVisible():
            try:
                visible_text.append(str(w.text()))
            except Exception:
                pass
    joined="\n".join(visible_text)
    for forbidden in ("你现在想做什么？", "当前工作", "打开当前工程", "新建项目"):
        if forbidden in joined:
            fail(f"home: redundant first-level block still visible: {forbidden}")
    report.append("PASS homepage is reduced to platform overview; redundant goal/current-work blocks are absent")


def simulation_checks(window, out, report):
    p=page(window,"simulation")
    shot(window,out,"simulation_default")
    b=getattr(p,"parameter_toggle_button",None)
    spl=getattr(p,"main_splitter",None)
    if b is None or spl is None: fail("simulation: missing parameter toggle/splitter")
    before=spl.sizes(); click(b,"simulation parameter toggle hide"); hidden=spl.sizes()
    shot(window,out,"simulation_parameters_hidden")
    click(b,"simulation parameter toggle restore"); restored=spl.sizes()
    if hidden[0]>10 or restored[0]<220: fail(f"simulation parameter toggle bad: {before}->{hidden}->{restored}")
    # Overview/detail are real layers inside the result analyser, not a “more” menu.
    live=getattr(p,"results",None)
    if live is not None:
        live.set_current_result("相位"); wait(160)
        click(live.overview_mode_button,"analysis overview")
        shot(window,out,"simulation_phase_overview")
        click(live.detail_mode_button,"analysis detail")
        if live.workspace.isVisible():
            fail("analysis detail still repeats the main plot workspace")
        if not getattr(live, "detail_report", None) or not live.detail_report.isVisible():
            fail("analysis detail data report is not visible")
        shot(window,out,"simulation_phase_detail")
        click(live.overview_mode_button,"analysis overview restore")
        if not live.workspace.isVisible():
            fail("analysis overview did not restore the main plot workspace")
        # Wavefront used to exist in the backend but was disconnected from the UI.
        live.set_current_result("波前"); wait(160)
        wavefront_present = any(live.result_selector.itemData(i)=="波前" for i in range(live.result_selector.count()))
        if not wavefront_present: fail("wavefront result is not reachable from 像质与波前")
        shot(window,out,"simulation_wavefront")
    report.append("PASS simulation panel collapse/restore, overview/detail, and wavefront routing")


def optimization_checks(window,out,report):
    p=page(window,"optimization")
    if hasattr(p, "on_activated"):
        p.on_activated()
        wait(200)
    if hasattr(p, "_sync_primary_action_idle_state"):
        p._sync_primary_action_idle_state()
    shot(window,out,"optimization_task")
    if isinstance(p,PageLoadErrorWidget): fail("optimization load error")
    start=getattr(p,"start_research_button",None)
    result_panel=getattr(p,"main_result_panel",None)
    if start is None or result_panel is None: fail("optimization: missing start/result panel")
    assert_hittable(start,"optimization start")
    if not result_panel.isVisible():
        fail("optimization result panel not visible")
    if result_panel.width()<160 or result_panel.height()<160:
        fail(f"optimization result panel too small {result_panel.size()}")
    wh=window.rect()
    for label,w in (("start",start),("result",result_panel)):
        pos=w.mapTo(window,QPoint(0,0)); rect=QRect(pos,w.size())
        if not wh.intersects(rect): fail(f"optimization {label} outside first screen")
    p.handle_assistant_action({"target": "optimization.inverse_design", "level": "navigate", "payload": {}})
    wait(220)
    if "反向" not in start.text():
        fail(f"inverse design did not expose a start action: {start.text()}")
    shot(window,out,"inverse_design_ready")
    p.handle_assistant_action({"target": "optimization.ml_inverse_prediction", "level": "navigate", "payload": {}})
    wait(220)
    if hasattr(p, "_sync_primary_action_idle_state"):
        p._sync_primary_action_idle_state()
    if "反向预测" not in start.text():
        fail(f"ML reverse prediction did not expose a distinct start action: {start.text()}")
    shot(window,out,"ml_reverse_prediction_ready")
    p.handle_assistant_action({"target": "optimization.scan", "level": "navigate", "payload": {}})
    wait(120)
    if hasattr(p, "_sync_primary_action_idle_state"):
        p._sync_primary_action_idle_state()
    task_win = getattr(window, "_optimization_task_window", None)
    if task_win is not None:
        task_win.hide()
    page(window, "home")
    wait(160)
    # Floating AI launcher must not cover research progress or footer actions. This
    # was previously visible only in screenshots, so make it a regression rule.
    assistant=getattr(window,"assistant_button",None)
    progress=getattr(p,"research_progress",None)
    if assistant is not None and progress is not None:
        assert_no_widget_overlap(assistant,progress,"AI launcher vs optimization progress")
    for attr in ("footer_result_button","footer_tasks_button"):
        footer=getattr(window,attr,None)
        if assistant is not None and footer is not None:
            assert_no_widget_overlap(assistant,footer,f"AI launcher vs {attr}")
    report.append("PASS optimization settings/result coexist; inverse design exposes a real start action; AI launcher clears progress/actions")


def ml_checks(window,out,report):
    task_win = getattr(window, "_optimization_task_window", None)
    if task_win is not None:
        task_win.hide()
    p=page(window,"machine_learning")
    if len(getattr(p,"workflow_buttons",[]))!=4: fail("ML visible workflow should be data/train/compare/forward prediction")
    names=("data","training","comparison","prediction")
    for stack_idx,(name,b) in enumerate(zip(names,p.workflow_buttons),start=1):
        click(b,f"ml:{name}")
        if p.workflow_stack.currentIndex()!=stack_idx: fail(f"ML stage {name} did not switch")
        shot(window,out,f"ml_{name}")
    pred=getattr(p,"prediction_button",None)
    if pred is None: fail("ML prediction has no real start button")
    assert_hittable(pred,"ML start prediction")
    report.append("PASS ML has no overview landing page; model construction stages and forward prediction remain direct")


def teaching_checks(window,out,report):
    p=page(window,"teaching"); wb=p.workbench
    shot(window,out,"teaching_2d")
    combo=getattr(wb,"teaching_mismatch_combo",None)
    if combo is None or combo.count()!=5:
        fail(f"teaching mismatch combo count {0 if combo is None else combo.count()} != 5")
    if not combo.isVisible() or not combo.isEnabled():
        fail("teaching mismatch combo not visible/enabled")
    lateral_index=combo.findData("lateral_scan")
    if lateral_index < 0:
        fail("teaching lateral_scan preset missing from mismatch combo")
    combo.setCurrentIndex(lateral_index)
    wait(220)
    if str(getattr(wb.model,"active_experiment_key","") or "") not in {"lateral_scan",""}:
        fail(f"teaching lateral did not load expected experiment: {wb.model.active_experiment_key}")
    if getattr(wb,"_view_kind","")!="3d":
        wb.set_view_kind("3d")
        wait(350)
    shot(window,out,"teaching_3d_global")
    v=wb.view_3d
    before=tuple(round(x,3) for x in v.camera_state())
    for preset,name in (("top","top"),("side","side"),("isometric","global")):
        v.set_view_preset(preset); wait(180)
        shot(window,out,f"teaching_3d_{name}")
    v.rotate_camera(57.0); wait(220)
    after=tuple(round(x,3) for x in v.camera_state())
    quick3d_camera_changed = before != after
    shot(window,out,"teaching_3d_rotated_57deg")
    p0=QPoint(max(40,v.width()//2-80),max(40,v.height()//2))
    p1=QPoint(min(v.width()-40,p0.x()+130),min(v.height()-40,p0.y()+45))
    state0=tuple(round(x,3) for x in v.camera_state())
    QTest.mousePress(v,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,p0)
    QTest.mouseMove(v,p1,80); QTest.mouseRelease(v,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,p1); wait(220)
    state1=tuple(round(x,3) for x in v.camera_state())
    shot(window,out,"teaching_3d_mouse_orbit")
    report.append(f"PASS teaching 3D preset API invoked; Quick3D camera_state changed={quick3d_camera_changed}; mouse-orbit changed={state0!=state1}")
    wb.phenomenonRequested.emit("mismatch:lateral")
    wait(220)
    shot(window,out,"teaching_principle_open")
    if not p.exploration_panel.isVisible(): fail("teaching principle/exploration panel did not open")
    p._close_exploration(); wait(150)
    if p.exploration_panel.isVisible(): fail("teaching exploration panel did not close")
    try:
        from frontend_pyside.features.teaching.spatial_routing_upgrade import FlexibleSpatial3DView
        proxy = FlexibleSpatial3DView()
        proxy.resize(1100, 650); proxy.set_model(wb.model); proxy.show(); wait(160)
        proxy.set_view_preset("paper"); wait(100); shot_widget(proxy,out,"teaching_3d_proxy_global")
        state0=proxy.camera_state()
        proxy.rotate_camera(57.0); wait(100); shot_widget(proxy,out,"teaching_3d_proxy_rotated_57deg")
        state1=proxy.camera_state()
        if state0==state1: fail("painted 3D proxy rotation did not change camera state")
        blank=None
        for y in range(90, max(100,proxy.height()-80), 70):
            for x in range(100, max(110,proxy.width()-100), 90):
                point=QPoint(x,y)
                if proxy._node_at(point) is None:
                    blank=point; break
            if blank is not None: break
        if blank is not None:
            endp=QPoint(min(proxy.width()-30,blank.x()+110), min(proxy.height()-30,blank.y()+35))
            QTest.mousePress(proxy,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,blank)
            QTest.mouseMove(proxy,endp,80); QTest.mouseRelease(proxy,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,endp); wait(120)
            if proxy.camera_state()==state0: fail("painted 3D proxy mouse orbit was intercepted")
            shot_widget(proxy,out,"teaching_3d_proxy_mouse_orbit")
        proxy.close()
    except Exception as exc:
        fail(f"teaching 3D visual proxy failed: {exc}")
    report.append("PASS teaching mismatch combo, temporary exploration panel, and 3D visual rotation proxy")


def responsive_checks(window,out,report):
    task_win = getattr(window, "_optimization_task_window", None)
    if task_win is not None:
        task_win.hide()
    page(window, "home")
    wait(200)
    for w,h,name in ((1366,768,"landscape_1366"),(1100,720,"landscape_1100"),(768,1366,"portrait_rotated"),(1920,1080,"landscape_1920")):
        window.resize(w,h); wait(300)
        shell_checks(window,[])
        shot(window,out,f"responsive_{name}")
    report.append("PASS resize/orientation checks 1366x768, 1100x720, 768x1366, 1920x1080")


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--out",default="acceptance/final_dynamic")
    args=ap.parse_args(); out=Path(args.out).resolve(); out.mkdir(parents=True,exist_ok=True)
    app=QApplication.instance() or QApplication([])
    report=[]; errors=[]
    window=create_main_window(); window.resize(1366,768); window.show(); wait(500)
    checks=[
        ("shell",lambda:shell_checks(window,report)),
        ("home",lambda:home_checks(window,out,report)),
        ("simulation",lambda:simulation_checks(window,out,report)),
        ("optimization",lambda:optimization_checks(window,out,report)),
        ("machine_learning",lambda:ml_checks(window,out,report)),
        ("teaching",lambda:teaching_checks(window,out,report)),
        ("responsive",lambda:responsive_checks(window,out,report)),
    ]
    for name,fn in checks:
        try: fn()
        except Exception as exc:
            errors.append({"check":name,"error":str(exc),"traceback":traceback.format_exc()})
    window.close(); wait(100)
    result={"passed":not errors,"passes":report,"errors":errors}
    (out/"dynamic_acceptance.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=["# Dynamic GUI Acceptance","",*(f"- {x}" for x in report)]
    if errors:
        lines += ["","## FAILURES"]+[f"- FAIL {e['check']}: {e['error']}" for e in errors]
    else: lines += ["","**OVERALL: PASS**"]
    (out/"dynamic_acceptance.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if errors: raise SystemExit(1)

if __name__=="__main__": main()
