from __future__ import annotations

import argparse, json, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolButton

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.features.assistant.dialog import AiAssistantDialog
from frontend_pyside.features.machine_learning.page import MachineLearningPage
from frontend_pyside.features.optimization.page import OptimizationPage
from frontend_pyside.features.simulation.page import SimulationPage
from frontend_pyside.features.tasks.page import TasksPage
from frontend_pyside.features.teaching.page import TeachingPage


def _check(v,msg):
    if not v: raise AssertionError(msg)

def _click(app,w):
    _check(w is not None and w.isEnabled(), f'控件不可点击: {getattr(w,"objectName",lambda:"?")()}')
    QTest.mouseClick(w, Qt.MouseButton.LeftButton); app.processEvents()

def run(screenshots_dir: Path | None = None):
    app=QApplication.instance() or QApplication([])
    rows=[]
    shot_index = {"value": 0}
    def save_shot(widget, slug: str):
        if screenshots_dir is None:
            return
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        shot_index["value"] += 1
        path = screenshots_dir / f"{shot_index['value']:02d}_{slug}.png"
        if not widget.grab().save(str(path)):
            raise AssertionError(f"截图保存失败: {path}")
    def case(name,fn):
        try: rows.append({'persona':name,'status':'PASS','detail':str(fn() or '通过')})
        except Exception as e: rows.append({'persona':name,'status':'FAIL','detail':f'{type(e).__name__}: {e}'})

    def ai_guided_beginner():
        ctx=create_app_context(); d=AiAssistantDialog(ctx); d.resize(520,700); d.set_page_context('simulation'); d.show(); app.processEvents()
        _check(d.task_title.isVisible(),'Task-first 当前建议卡不可见')
        _check(bool(d.task_state.text().strip()),'AI 没有读取当前研究状态')
        emitted=[]; d.actionRequested.connect(lambda a: emitted.append(dict(a)))
        if d.task_action_button.isVisible() and d.task_action_button.isEnabled(): _click(app,d.task_action_button)
        if emitted:
            a=emitted[-1]; _check(a.get('target_page') and a.get('target_control'),'AssistantAction 缺少页面/控件目标')
            _check(not bool(a.get('starts_job')),'AI 点击建议直接启动了耗时任务')
            _check(bool(a.get('why')) and bool(a.get('what_happens_next')),'AI Action 缺少为什么/下一步说明')
        save_shot(d, 'ai_guided_beginner'); d.close(); return 'Task-first 建议可见；结构化 Action 不直接执行正式计算'

    def self_exploring_beginner():
        ctx=create_app_context(); t=TeachingPage(ctx); t.resize(1366,768); t.show(); app.processEvents()
        before=ctx.project.design_revision
        combo=t.workbench.teaching_mismatch_combo
        _check(combo is not None and combo.count()==5,'教学研究变量下拉不可用')
        t._show_exploration('concept','gaussian_q'); app.processEvents()
        _check(t.exploration_panel.isVisible(),'现象探索没有打开')
        close = next((b for b in t.exploration_panel.findChildren(QToolButton) if b.toolTip() == "关闭探索面板"), None)
        _click(app, close)
        t.workbench._on_tool_category_requested('工具'); app.processEvents()
        _check(t.workbench.left_drawer.isVisible(),'器材工具没有打开抽屉')
        _check(ctx.project.design_revision==before,'教学探索污染正式 revision')
        save_shot(t, 'self_exploring_beginner'); t.close(); return '可自由探索/打开器材；不需要闯关且不污染正式项目'

    def optical_researcher():
        ctx=create_app_context(); p=SimulationPage(ctx); p.resize(1366,768); p.show(); app.processEvents()
        rev0=ctx.project.design_revision
        _click(app,p.parameter_toggle_button); _click(app,p.parameter_toggle_button)
        target=p.assistant_action_target_widget({'target':'simulation.formal'})
        _check(target is p.formal_button,'AI 正式仿真没有精确定位到按钮')
        _check(ctx.project.design_revision==rev0,'只切换参数面板却修改了设计 revision')
        save_shot(p, 'optical_researcher'); p.close(); return '参数区高频操作稳定；AI 能精确定位正式计算控件'

    def experiment_validation_user():
        ctx=create_app_context(); p=OptimizationPage(ctx); p.resize(1366,768); p.show(); app.processEvents()
        rev0=ctx.project.design_revision
        _click(app,p.validation_workspace_button)
        _check(p.validation_workspace_button.isChecked(),'没有进入实验验证工作区')
        _check(ctx.project.design_revision==rev0,'只查看实验验证改变了设计 revision')
        save_shot(p, 'experiment_validation'); p.close(); return '实验验证入口可达；浏览冻结验证模块不会改变正式设计'

    def ml_researcher():
        ctx=create_app_context(); ctx.registry.set_models([
            {'model_id':'m1','name':'当前可靠模型','test_metrics':{'r2':0.90}},
            {'model_id':'m2','name':'最近差模型','test_metrics':{'r2':-0.20}}])
        ctx.registry.set_current_model('m1'); ctx.registry.set_recent_model('m2')
        p=MachineLearningPage(ctx); p.resize(1366,768); p.show(); app.processEvents()
        _click(app,p.workflow_buttons[0]); app.processEvents()
        _check(ctx.registry.current_model_id=='m1','浏览/最近训练模型偷偷替换当前模型')
        save_shot(p, 'ml_researcher'); p.close(); return '最近模型与当前正式模型保持分离'

    def teacher_student():
        ctx=create_app_context(); t=TeachingPage(ctx); t.resize(1366,768); t.show(); app.processEvents(); rev0=ctx.project.design_revision
        t._show_exploration('diagnosis','curve_features'); app.processEvents()
        ep=t.exploration_panel; _check(ep.isVisible(),'诊断推理未打开')
        ep.open_section('mismatch','lateral'); app.processEvents()
        _check(ep.mismatch_selector.count()==5,'五类失配没有完整提供')
        # real clicks on phase and overlay visualization buttons
        _click(app, ep.display_group.button(1)); _check(ep.mismatch_visual.display_mode=='phase','相位视图没有切换')
        ep.mismatch_mode.setCurrentIndex(1); app.processEvents(); _check(ep.mismatch_stack.currentIndex()==1,'对比模式不可用')
        ep.mismatch_mode.setCurrentIndex(2); app.processEvents(); _check(ep.mismatch_stack.currentIndex()==2,'复合失配不可用')
        _check(ctx.project.design_revision==rev0,'教学实验修改了正式 revision')
        save_shot(t, 'teacher_student'); t.close(); return '五类失配/相位/对比/多因素可操作；教学保持 Sandbox'

    def fault_recovery_user():
        ctx=create_app_context(); p=TasksPage(ctx); p.resize(1366,768); p.show(); app.processEvents()
        _check(not p.retry_button.isEnabled(),'无失败任务时重试错误启用')
        _check(not p.detail_view_result.isEnabled(),'无正式结果时查看结果错误启用')
        # refresh is a real compact icon click; any backend failure must not fabricate a task.
        n0=len(ctx.tasks.tasks)
        _click(app,p.refresh_button); QTest.qWait(60); app.processEvents()
        _check(len(ctx.tasks.tasks)>=n0,'刷新导致本地任务状态异常丢失')
        save_shot(p, 'fault_recovery'); p.close(); return '任务刷新为真实图标操作；无结果/无可重试任务时动作保持禁用'

    def proficient_high_frequency():
        ctx=create_app_context(); t=TeachingPage(ctx); t.resize(1366,768); t.show(); app.processEvents()
        for _ in range(4):
            t.workbench.set_view_kind('2d'); app.processEvents()
            t.workbench.set_view_kind('3d'); app.processEvents()
            t._show_exploration('concept','model_boundary'); app.processEvents()
            t._show_exploration_request('workbench'); app.processEvents()
        _check(t.workbench._view_kind=='3d','高频切换后视图状态漂移')
        _check(not t.exploration_panel.isVisible(),'回到自由实验后探索层仍残留')
        save_shot(t, 'proficient_high_frequency'); t.close(); return '高频 2D/3D/原理/自由实验切换后页面状态一致'

    for name,fn in [
        ('AI 引导型新手',ai_guided_beginner),('自主探索型新手',self_exploring_beginner),
        ('光学科研用户',optical_researcher),('实验验证用户',experiment_validation_user),
        ('机器学习研究用户',ml_researcher),('教师/学生用户',teacher_student),
        ('故障恢复用户',fault_recovery_user),('熟练高频用户',proficient_high_frequency)]: case(name,fn)
    return rows

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--out',default=''); ap.add_argument('--screenshots-dir',default=''); a=ap.parse_args(); rows=run(Path(a.screenshots_dir) if a.screenshots_dir else None); print(json.dumps(rows,ensure_ascii=False,indent=2))
    if a.out:
        p=Path(a.out); p.parent.mkdir(parents=True,exist_ok=True); p.write_text('\n'.join([f"{r['persona']}\t{r['status']}\t{r['detail']}" for r in rows])+'\n',encoding='utf-8')
    return 0 if all(r['status']=='PASS' for r in rows) else 1
if __name__=='__main__': raise SystemExit(main())
