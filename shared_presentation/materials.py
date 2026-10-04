"""Material catalog and labels shared by the desktop and browser presentation."""
from __future__ import annotations
from math import sqrt
from typing import Any
from optical_core.materials.catalog import default_material_database
from optical_core.materials.dispersion import wavelength_nm_to_um

_AIR_NAMES = {"", "AIR", "VACUUM", "NONE", "真空"}
_CATALOG_CACHE: dict[int, tuple[dict[str, Any], ...]] = {}


def is_air_material(name: str) -> bool:
    return str(name or "").strip().upper() in _AIR_NAMES


def display_material_name(name: str) -> str:
    text = str(name or "").strip()
    if text.startswith("glass_"):
        return text[len("glass_") :]
    return text or "—"


def _format_index(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{float(value):.6g}"


def _custom_index(record: dict[str, Any], wavelength_nm: float) -> float | None:
    model = str(record.get("model") or "constant")
    try:
        if model == "cauchy":
            wavelength_um = float(wavelength_nm) / 1000.0
            a = float(record.get("a", 1.5) or 1.5)
            b = float(record.get("b_um2", 0.0) or 0.0)
            c = float(record.get("c_um4", 0.0) or 0.0)
            return a + b / (wavelength_um ** 2) + c / (wavelength_um ** 4)
        if model == "sellmeier":
            lam2 = (float(wavelength_nm) / 1000.0) ** 2
            n2 = 1.0
            for index in (1, 2, 3):
                b = float(record.get(f"b{index}", 0.0) or 0.0)
                c = float(record.get(f"c{index}_um2", 0.0) or 0.0)
                n2 += b * lam2 / (lam2 - c) if abs(lam2 - c) > 1e-15 else 0.0
            return sqrt(max(n2, 0.0))
        return float(record.get("n", 1.5) or 1.5)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _catalog_entry(name: str, wavelength_nm: float) -> dict[str, Any] | None:
    database = default_material_database()
    try:
        canonical = database.normalize_material_name(name)
        entry = database.select_entry(
            canonical,
            wavelength_um=wavelength_nm_to_um(wavelength_nm),
            require_n=True,
        )
        index = database.get_n(canonical, wavelength_nm=wavelength_nm, source=entry.source)
        raw = dict(entry.raw or {})
        return {
            "name": display_material_name(canonical),
            "canonical": canonical,
            "n": float(index),
            "wavelength_nm": float(wavelength_nm),
            "custom": False,
            "source": entry.source,
            "type": entry.type,
            "wl_min_um": entry.wl_min,
            "wl_max_um": entry.wl_max,
            "coeffs": list(raw.get("coeffs") or []),
            "comments": entry.comments or "",
        }
    except Exception:
        return None


def _builtin_catalog(wavelength_nm: float) -> tuple[dict[str, Any], ...]:
    key = int(round(float(wavelength_nm) * 10.0))
    cached = _CATALOG_CACHE.get(key)
    if cached is not None:
        return cached
    database = default_material_database()
    rows: list[dict[str, Any]] = [
        {
            "name": "AIR",
            "canonical": "AIR",
            "n": 1.0,
            "wavelength_nm": float(wavelength_nm),
            "custom": False,
            "source": "constant",
            "type": "constant",
            "wl_min_um": 0.2,
            "wl_max_um": 20.0,
            "coeffs": [],
            "comments": "n = 1",
        },
        {
            "name": "MIRROR",
            "canonical": "MIRROR",
            "n": None,
            "wavelength_nm": float(wavelength_nm),
            "custom": False,
            "source": "ideal",
            "type": "mirror",
            "wl_min_um": None,
            "wl_max_um": None,
            "coeffs": [],
            "comments": "理想反射",
        },
    ]
    seen = {"air", "mirror"}
    for canonical in database.list_materials():
        record = _catalog_entry(canonical, wavelength_nm)
        if record is None:
            continue
        marker = str(record["name"]).strip().lower()
        if marker in seen:
            continue
        seen.add(marker)
        rows.append(record)
    rows.sort(key=lambda item: str(item.get("name") or "").lower())
    packed = tuple(rows)
    _CATALOG_CACHE[key] = packed
    return packed


def custom_material_records(project, wavelength_nm: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in list(getattr(project, "custom_materials", ()) or ()):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        rows.append(
            {
                **dict(item),
                "name": name,
                "canonical": name,
                "n": _custom_index(item, wavelength_nm),
                "wavelength_nm": float(wavelength_nm),
                "custom": True,
            }
        )
    return rows


def all_material_records(project, wavelength_nm: float) -> list[dict[str, Any]]:
    custom = custom_material_records(project, wavelength_nm)
    custom_names = {str(item["name"]).strip().lower() for item in custom}
    catalog = [
        dict(item)
        for item in _builtin_catalog(wavelength_nm)
        if str(item.get("name") or "").strip().lower() not in custom_names
    ]
    return custom + catalog


def used_lens_materials(project, wavelength_nm: float) -> list[dict[str, Any]]:
    used: list[str] = []
    for surface in list(getattr(project, "surfaces", ()) or ()):
        name = str(getattr(surface, "material", "") or "").strip()
        if not name or is_air_material(name) or name in used:
            continue
        used.append(name)
    custom = {
        str(item.get("name") or "").strip().lower(): item
        for item in custom_material_records(project, wavelength_nm)
    }
    rows: list[dict[str, Any]] = []
    for name in used:
        record = custom.get(name.lower()) or _catalog_entry(name, wavelength_nm)
        if record is None:
            record = {
                "name": name,
                "canonical": name,
                "n": None,
                "wavelength_nm": float(wavelength_nm),
                "custom": False,
                "comments": "当前波长下没有折射率数据",
            }
        rows.append(record)
    return rows


def _wavelength_text(record: dict[str, Any]) -> str:
    value = record.get("wavelength_nm")
    try:
        return f"{float(value):g} nm"
    except (TypeError, ValueError):
        return "—"


def material_detail_pairs(record: dict[str, Any]) -> list[tuple[str, str]]:
    pairs = [
        ("材料名", str(record.get("name") or "—")),
        ("折射率", _format_index(record.get("n"))),
        ("波长", _wavelength_text(record)),
        ("来源", str(record.get("source") or ("自定义" if record.get("custom") else "—"))),
        ("模型", str(record.get("type") or record.get("model") or "—")),
    ]
    wl_min = record.get("wl_min_um")
    wl_max = record.get("wl_max_um")
    if wl_min is not None or wl_max is not None:
        low = f"{float(wl_min):g}" if isinstance(wl_min, (int, float)) else "—"
        high = f"{float(wl_max):g}" if isinstance(wl_max, (int, float)) else "—"
        pairs.append(("有效波段", f"{low}–{high} μm"))
    if record.get("custom"):
        model = str(record.get("model") or "constant")
        if model == "constant":
            pairs.append(("消光系数 k", f"{float(record.get('k', 0.0) or 0.0):g}"))
        elif model == "cauchy":
            pairs.extend(
                (
                    ("A", f"{float(record.get('a', 0.0) or 0.0):g}"),
                    ("B / μm²", f"{float(record.get('b_um2', 0.0) or 0.0):g}"),
                    ("C / μm⁴", f"{float(record.get('c_um4', 0.0) or 0.0):g}"),
                )
            )
        elif model == "sellmeier":
            for index in (1, 2, 3):
                pairs.append((f"B{index}", f"{float(record.get(f'b{index}', 0.0) or 0.0):g}"))
                pairs.append((f"C{index} / μm²", f"{float(record.get(f'c{index}_um2', 0.0) or 0.0):g}"))
    coeffs = record.get("coeffs") or []
    if coeffs:
        pairs.append(("色散系数", ", ".join(f"{float(value):.6g}" for value in coeffs[:8])))
    comment = str(record.get("comments") or "").strip()
    if comment:
        pairs.append(("说明", comment))
    return pairs
