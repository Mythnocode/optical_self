"""One-time extraction of the existing Qt-independent explanation presentation."""
import ast
from pathlib import Path
from textwrap import dedent

root = Path(__file__).resolve().parents[1]
document = root / 'frontend_pyside/modules/explainability/documents.py'
source = document.read_text(encoding='utf-8')
if 'from shared_presentation.explainability import design_variable_plot' in source:
    raise SystemExit('Presentation has already been extracted; preserve the shared implementation.')
tree = ast.parse(source)
method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == '_render_design_variable')

class Presentation(ast.NodeTransformer):
    def visit_Expr(self, node):
        call = node.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
            if call.func.attr == 'set_result':
                return ast.Return(value=call.args[2])
            if call.func.attr == '_show':
                return ast.Return(value=ast.Dict(keys=[ast.Constant('kind'), ast.Constant('message')], values=[ast.Constant('empty'), call.args[1]]))
        return self.generic_visit(node)

body = [node for node in method.body if not (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'chart' for t in node.targets))]
function = ast.FunctionDef(name='design_variable_plot', args=ast.arguments(posonlyargs=[], args=[ast.arg(arg='body'), ast.arg(arg='chart')], kwonlyargs=[], kw_defaults=[], defaults=[ast.Constant('全局特征重要性排名')]), body=body, decorator_list=[])
function = ast.fix_missing_locations(Presentation().visit(function))
shared = root / 'shared_presentation/explainability.py'
shared.write_text('"""Original design-variable chart payloads, without UI dependencies."""\nfrom typing import Any\n_TARGET_DISPLAY = {"coupling_efficiency": "耦合效率", "coupling_loss_db": "耦合效率"}\nCHARTS = ("全局特征重要性排名", "蜂群图", "特征依赖网格图", "单变量依赖趋势图", "物理一致性图", "瀑布图")\n\n' + ast.unparse(function) + '\n', encoding='utf-8')
lines = source.splitlines(keepends=True)
replacement = '''    def _render_design_variable(self, body: dict[str, Any]) -> None:
        from shared_presentation.explainability import design_variable_plot
        chart = str(self.shap_chart.currentText()) if self.shap_chart is not None else "全局特征重要性排名"
        plot = design_variable_plot(body, chart)
        if plot.get("kind") == "empty":
            self._show("贡献排序", plot["message"])
        else:
            self.workspace.set_result(0, chart, plot)
'''
lines[method.lineno - 1:method.end_lineno] = [replacement]
document.write_text(''.join(lines), encoding='utf-8')

canvas = root / 'frontend_pyside/shared/plotting/canvas_parts/canvas_2d.py'
source = canvas.read_text(encoding='utf-8')
tree = ast.parse(source)
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
names = {'_readable_category_labels', '_set_category_plot_layout', '_register_bar_items', '_annotate_bars', '_beeswarm', '_dependence_grid', '_dependence_fit_ci', '_physics_consistency', '_waterfall', '_empty'}
methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
assert len(methods) == len(names)
pieces = []
lines = source.splitlines(keepends=True)
for node in methods:
    start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
    pieces.append(''.join(lines[start:node.end_lineno]))
for node in sorted(methods, key=lambda n: n.lineno, reverse=True):
    start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
    del lines[start:node.end_lineno]
source = ''.join(lines).replace('class Canvas2DMixin:', 'class Canvas2DMixin(ExplainChartsMixin):')
source = source.replace('import numpy as np\n', 'import numpy as np\nfrom shared_presentation.plotting.explain_charts import ExplainChartsMixin\n', 1)
source = source.replace('        kind = data.get("kind", "empty")\n', '        kind = data.get("kind", "empty")\n        if kind in EXPLAIN_CHART_KINDS:\n            self.draw_explain_chart(ax, data)\n            return\n', 1)
source = source.replace('import ExplainChartsMixin\n', 'import ExplainChartsMixin, EXPLAIN_CHART_KINDS\n', 1)
canvas.write_text(source, encoding='utf-8')
dispatch = '''
    def draw_explain_chart(self, ax, data):
        kind = data.get("kind")
        if kind == "barh":
            labels = [str(v) for v in data.get("labels", [])]
            values = data.get("values", [])
            bars = ax.barh(labels, values, color=data.get("colors") or None)
            self._register_bar_items(bars, labels, data)
            self._annotate_bars(ax, bars, values, horizontal=True, enabled=bool(data.get("show_values")))
            ax.invert_yaxis()
        else:
            getattr(self, "_" + kind)(ax, data)
        if kind in {"dependence_grid", "dependence_fit_ci"}:
            return
        ax.set_title(data.get("title", "") if kind == "barh" else "", pad=8)
        ax.set_xlabel(data.get("x_label", ""))
        ax.set_ylabel(data.get("y_label", ""), rotation=90, labelpad=28 if kind in {"waterfall", "beeswarm"} else 12, va="center")
        if kind in {"beeswarm", "physics_consistency"}:
            ax.grid(True, alpha=0.72, color=theme.CHART_GRID)
        else:
            ax.grid(False)
'''
(root / 'shared_presentation/plotting/explain_charts.py').write_text('"""Original Matplotlib explanation charts shared by Qt and the API."""\nimport numpy as np\nfrom matplotlib.patches import Patch\nfrom shared_presentation import theme_tokens as theme\nEXPLAIN_CHART_KINDS = {"barh", "beeswarm", "waterfall", "dependence_grid", "dependence_fit_ci", "physics_consistency"}\n\nclass ExplainChartsMixin:\n' + '\n'.join(pieces) + dispatch, encoding='utf-8')

workspace = root / 'frontend_pyside/shared/plotting/result_workspace.py'
source = workspace.read_text(encoding='utf-8')
method = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == '_result_summary')
lines = source.splitlines(keepends=True)
summary = dedent(''.join(lines[method.lineno - 1:method.end_lineno])).replace('def _result_summary(', 'def result_summary(', 1)
(root / 'shared_presentation/plotting/result_summary.py').write_text('"""Original result-pane caption, shared without Qt."""\n' + summary + '\n', encoding='utf-8')
lines[method.lineno - 1:method.end_lineno] = ['    def _result_summary(data: dict) -> str:\n        from shared_presentation.plotting.result_summary import result_summary\n        return result_summary(data)\n']
workspace.write_text(''.join(lines), encoding='utf-8')
