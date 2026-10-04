"""Export the legacy default request for the JS migration, without changing it."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from frontend_pyside.state.project_context import default_project
from frontend_pyside.features.simulation.form_state import SimulationFormState
from frontend_pyside.features.simulation.payloads import build_simulation_payload

project = default_project()
for index, surface in enumerate(project.surfaces):
    surface.element_id = f"element-demo-{surface.group_id}"
    surface.surface_id = f"surface-demo-{index + 1}"
payload = build_simulation_payload(project, SimulationFormState())
payload["request_id"] = "sim-migration-default"
output = ROOT / "frontend_web/src/domain/default-simulation.json"
output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(output)
