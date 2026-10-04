"""Adapt the original material library without importing its Qt widgets."""
from types import SimpleNamespace
from shared_presentation.materials import all_material_records, used_lens_materials, material_detail_pairs, _format_index, _wavelength_text


def material_library(wavelength_nm: float, custom: list[dict], used_names: list[str]) -> dict:
    project = SimpleNamespace(custom_materials=custom, surfaces=[SimpleNamespace(material=name) for name in used_names])
    def present(record):
        return {**record, "index_text": _format_index(record.get("n")), "wavelength_text": _wavelength_text(record),
                "detail_pairs": material_detail_pairs(record)}
    return {"records": [present(row) for row in all_material_records(project, wavelength_nm)],
            "used": [present(row) for row in used_lens_materials(project, wavelength_nm)]}
