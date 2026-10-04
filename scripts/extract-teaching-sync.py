"""Extract original engineering scene mapping into a Qt-free shared helper."""
import ast
from pathlib import Path
import textwrap

root=Path(__file__).resolve().parents[1]
path=root/'frontend_pyside/modules/teaching/shell.py'
source=path.read_text(encoding='utf-8')
tree=ast.parse(source)
shell=next(node for node in ast.walk(tree) if isinstance(node,ast.ClassDef) and node.name=='TeachingShell')
groups=next(node for node in shell.body if isinstance(node,ast.FunctionDef) and node.name=='_engineering_lens_groups')
sync=next(node for node in shell.body if isinstance(node,ast.FunctionDef) and node.name=='_sync_scene_from_engineering_project')
lines=source.splitlines(keepends=True)
group_source=textwrap.dedent(''.join(lines[groups.lineno-1:groups.end_lineno])).replace('_engineering_lens_groups','engineering_lens_groups',1)
sync_source=''.join(lines[sync.lineno-1:sync.end_lineno])
start=sync_source.index('        source = dict(serialized.get("source") or {})')
end=sync_source.index('        contract = serialized.get("calculation_contract")')
body=sync_source[start:end].replace('self.store','store').replace('self._engineering_lens_groups','engineering_lens_groups')
helper='''"""Original engineering-project → Teaching scene mapping, without Qt."""
from typing import Any
from shared_presentation.teaching_model import BENCH_ORIGIN_X_MM

'''+group_source+'\n\ndef scene_from_engineering(store, project, serialized):\n'+textwrap.indent(textwrap.dedent(body),'    ')+'    return store.to_dict()\n'
(root/'shared_presentation/teaching_sync.py').write_text(helper,encoding='utf-8')
replacement='        scene_from_engineering(self.store, project, serialized)\n'
updated=source.replace(sync_source,sync_source[:start]+replacement+sync_source[end:],1)
group_start=groups.decorator_list[0].lineno-1
old=''.join(lines[group_start:groups.end_lineno])
updated=updated.replace(old,'    _engineering_lens_groups = staticmethod(engineering_lens_groups)\n',1)
updated=updated.replace('from shared_presentation.teaching_equipment import EQUIPMENT_PRESETS, equipment_groups','from shared_presentation.teaching_equipment import EQUIPMENT_PRESETS, equipment_groups\nfrom shared_presentation.teaching_sync import engineering_lens_groups, scene_from_engineering',1)
path.write_text(updated,encoding='utf-8')
print('Extracted original mapping; original UI delegates to the shared helper.')
