"""One-time move of pure native formula presentation, retaining Qt imports."""
import ast
from pathlib import Path

root = Path(__file__).resolve().parents[1]
actions = root/'frontend_pyside/features/explainability/actions.py'
formula = root/'frontend_pyside/features/explainability/formula_presentation.py'
destination = root/'shared_presentation/explanation_formulas.py'
if destination.exists():
    raise SystemExit('Already extracted; preserve subsequent shared changes.')
source = actions.read_text(encoding='utf-8')
names = {'FORMULA_CATALOG','feature_display_name','formula_binding_for_feature',
         'formula_location_for_feature','physical_mechanism_for_feature',
         'suggested_action_for_feature','formula_latex','formula_chain_for_feature'}
nodes = [node for node in ast.parse(source).body
         if getattr(node,'name','') in names or
         isinstance(node,ast.AnnAssign) and getattr(node.target,'id','') in names]
lines = source.splitlines(keepends=True)
parts = [''.join(lines[n.lineno-1:n.end_lineno]) for n in nodes]
destination.write_text('"""Original optical formula metadata shared by Qt and Web presentation."""\n'
                       'from __future__ import annotations\nimport re\n\n'+
                       '\n\n'.join(parts).replace('from frontend_pyside.shared.feature_labels import',
                                                'from shared_presentation.feature_labels import')+'\n',encoding='utf-8')
for n in reversed(nodes):
    lines[n.lineno-1:n.end_lineno] = []
source = ''.join(lines)
source = source.replace('from shared_presentation.explainability import explain_shap_failure',
                        'from shared_presentation.explainability import explain_shap_failure\n'
                        'from shared_presentation.explanation_formulas import (\n    '+',\n    '.join(sorted(names))+'\n)')
actions.write_text(source,encoding='utf-8')
source = formula.read_text(encoding='utf-8')
lines = source.splitlines(keepends=True)
nodes = [n for n in ast.parse(source).body if getattr(n,'name','') in {'_render_formula_png','render_formula_png'}]
parts=[]
for n in nodes:
    start = min([n.lineno]+[d.lineno for d in n.decorator_list])-1
    parts.append(''.join(lines[start:n.end_lineno]))
(root/'shared_presentation/formula_images.py').write_text('"""Original mathtext equation rendering without a Qt import."""\n'
                        'from __future__ import annotations\nfrom functools import lru_cache\n\n'+
                        '\n\n'.join(parts)+'\n',encoding='utf-8')
for n in reversed(nodes):
    start = min([n.lineno]+[d.lineno for d in n.decorator_list])-1
    lines[start:n.end_lineno]=[]
source=''.join(lines).replace('from html import escape','from html import escape\nfrom shared_presentation.formula_images import _render_formula_png, render_formula_png')
formula.write_text(source,encoding='utf-8')
print('Extracted original formula helpers and PNG rendering.')
