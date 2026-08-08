from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence

from .dispersion import (
    DispersionResult,
    dataset_provides_n,
    evaluate_dataset,
    validate_wavelength_um,
    wavelength_nm_to_um,
)


def _key(value: str | None) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _material_lookup_key(value: str | None) -> str:


    key = _key(value)
    for prefix in ("schott_", "ohara_", "hoya_", "cdgm_"):
        if key.startswith(prefix):
            key = key[len(prefix):]
            break
    if key.startswith("glass_"):
        key = key[len("glass_"):]
    return key


@dataclass(frozen=True, slots=True)
class MaterialEntry:
    material: str
    source: str
    type: str
    wl_min: float | None
    wl_max: float | None
    ref_short: str | None = None
    ref_full: str | None = None
    comments: str | None = None
    raw: dict[str, object] | None = None

    def supports(self, wavelength_um: float) -> bool:
        try:
            validate_wavelength_um(
                wavelength_um,
                wl_min=self.wl_min,
                wl_max=self.wl_max,
            )
            return True
        except ValueError:
            return False

    @property
    def provides_n(self) -> bool:
        return dataset_provides_n(self.raw or {})


@dataclass(frozen=True, slots=True)
class MaterialDescriptor:


    canonical_name: str
    display_name: str
    source: str
    wavelength_min_um: float | None
    wavelength_max_um: float | None
    reference_wavelength_nm: float
    refractive_index_reference: float
    refractive_index_d: float | None
    abbe_number_d: float | None
    supported_wavelengths_nm: tuple[float, ...]

    @property
    def is_optical_glass(self) -> bool:
        return self.canonical_name.startswith("glass_")


DEFAULT_ALIASES: dict[str, str] = {
    "bk7": "glass_N-BK7",
    "n_bk7": "glass_N-BK7",
    "n-bk7": "glass_N-BK7",
    "schott_n_bk7": "glass_N-BK7",
    "schott_n-bk7": "glass_N-BK7",
    "sf11": "glass_N-SF11",
    "n_sf11": "glass_N-SF11",
    "n-sf11": "glass_N-SF11",
    "n_fk5": "glass_N-FK5",
    "n_fk51a": "glass_N-FK51A",
    "n_fk58": "glass_N-FK58",
    "n_bak4": "glass_N-BAK4",
    "n_f2": "glass_N-F2",
    "n_sf5": "glass_N-SF5",
    "n_sf6": "glass_N-SF6",
    "n_sf10": "glass_N-SF10",
    "n_lak10": "glass_N-LAK10",
    "n_lak22": "glass_N-LAK22",
    "silica": "SiO2",
    "sio2": "SiO2",
    "fused_silica": "SiO2",
    "fused-silica": "SiO2",
    "uvfs": "SiO2",
    "calcium_fluoride": "CaF2",
    "caf2": "CaF2",
    "fluorite": "CaF2",
    "magnesium_fluoride": "MgF2",
    "mgf2": "MgF2",
    "sapphire": "Al2O3",
    "alumina": "Al2O3",
    "al2o3": "Al2O3",
}

DEFAULT_SOURCE_PREFERENCE: dict[str, str] = {
    "glass_N-BK7": "Schott",
    "glass_N-SF11": "Schott",
    "SiO2": "Malitson",
    "CaF2": "Malitson",
    "MgF2": "Dodge-o",
    "Al2O3": "Malitson",
}


class MaterialDatabase:


    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        aliases: dict[str, str] | None = None,
        source_preference: dict[str, str] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else default_data_dir()
        self.aliases = dict(DEFAULT_ALIASES)
        if aliases:
            self.aliases.update({_key(k): v for k, v in aliases.items()})
        self.source_preference = dict(DEFAULT_SOURCE_PREFERENCE)
        if source_preference:
            self.source_preference.update(source_preference)
        self._entries_cache: dict[str, list[dict[str, object]]] = {}

    def list_materials(self) -> list[str]:
        return sorted(path.stem for path in self.data_dir.glob("*.json"))

    def normalize_material_name(self, material: str) -> str:
        raw = str(material or "").strip()
        if not raw:
            raise KeyError("empty material name")
        if (self.data_dir / f"{raw}.json").exists():
            return raw
        alias_target = self.aliases.get(_key(raw))
        if alias_target and (self.data_dir / f"{alias_target}.json").exists():
            return alias_target

        
        
        
        glass_candidate = f"glass_{raw}"
        if (self.data_dir / f"{glass_candidate}.json").exists():
            return glass_candidate

        lookup = _material_lookup_key(raw)
        for name in self.list_materials():
            if _key(name) == _key(raw) or _material_lookup_key(name) == lookup:
                return name
        raise KeyError(f"unknown material {material!r}")

    def load_entries(self, material: str) -> list[dict[str, object]]:
        material_name = self.normalize_material_name(material)
        if material_name not in self._entries_cache:
            path = self.data_dir / f"{material_name}.json"
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError(f"material file must contain a list: {path}")
            self._entries_cache[material_name] = [dict(item) for item in data]
        return list(self._entries_cache[material_name])

    def list_sources(self, material: str) -> list[MaterialEntry]:
        material_name = self.normalize_material_name(material)
        result: list[MaterialEntry] = []
        for raw in self.load_entries(material_name):
            result.append(
                MaterialEntry(
                    material=material_name,
                    source=str(raw.get("source", "")),
                    type=str(raw.get("type", "")),
                    wl_min=_maybe_float(raw.get("wl_min")),
                    wl_max=_maybe_float(raw.get("wl_max")),
                    ref_short=_maybe_str(raw.get("ref_short")),
                    ref_full=_maybe_str(raw.get("ref_full")),
                    comments=_maybe_str(raw.get("comments")),
                    raw=raw,
                )
            )
        return result

    def select_entry(
        self,
        material: str,
        *,
        source: str | None = None,
        wavelength_um: float | None = None,
        require_n: bool = True,
    ) -> MaterialEntry:
        material_name = self.normalize_material_name(material)
        entries = self.list_sources(material_name)
        if source:
            matches = [e for e in entries if _key(e.source) == _key(source)]
            if not matches:
                available = ", ".join(e.source for e in entries[:12])
                raise KeyError(
                    f"source {source!r} not found for {material_name}. "
                    f"Available sources include: {available}"
                )
            entries = matches
        else:
            preferred = self.source_preference.get(material_name)
            if preferred:
                preferred_matches = [e for e in entries if _key(e.source) == _key(preferred)]
                if preferred_matches:
                    entries = preferred_matches + [e for e in entries if e not in preferred_matches]

        for entry in entries:
            if require_n and not entry.provides_n:
                continue
            if wavelength_um is not None and not entry.supports(wavelength_um):
                continue
            return entry

        constraints = []
        if require_n:
            constraints.append("providing n")
        if wavelength_um is not None:
            constraints.append(f"covering {wavelength_um:g} um")
        suffix = " and ".join(constraints) or "matching request"
        raise ValueError(f"no dataset for {material_name} {suffix}.")

    def evaluate(
        self,
        material: str,
        *,
        wavelength_um: float | None = None,
        wavelength_nm: float | None = None,
        source: str | None = None,
    ) -> DispersionResult:
        if wavelength_um is None:
            if wavelength_nm is None:
                raise ValueError("wavelength_um or wavelength_nm is required.")
            wavelength_um = wavelength_nm_to_um(float(wavelength_nm))
        wavelength_um = validate_wavelength_um(float(wavelength_um))
        entry = self.select_entry(
            material,
            source=source,
            wavelength_um=wavelength_um,
            require_n=False,
        )
        return evaluate_dataset(entry.raw or {}, wavelength_um)

    def get_n(
        self,
        material: str,
        *,
        wavelength_um: float | None = None,
        wavelength_nm: float | None = None,
        source: str | None = None,
    ) -> float:
        result = self.evaluate(
            material,
            wavelength_um=wavelength_um,
            wavelength_nm=wavelength_nm,
            source=source,
        )
        if result.n is None:
            raise ValueError(f"selected dataset for {material!r} does not provide n.")
        return float(result.n)

    def supports_wavelengths(
        self,
        material: str,
        wavelengths_nm: Sequence[float],
        *,
        source: str | None = None,
    ) -> bool:


        values = tuple(float(value) for value in wavelengths_nm)
        if not values:
            raise ValueError("wavelengths_nm must not be empty")
        try:
            for wavelength_nm in values:
                self.select_entry(
                    material,
                    source=source,
                    wavelength_um=wavelength_nm_to_um(wavelength_nm),
                    require_n=True,
                )
            return True
        except (KeyError, ValueError, NotImplementedError):
            return False

    def spectral_indices(
        self,
        material: str,
        wavelengths_nm: Sequence[float],
        *,
        source: str | None = None,
    ) -> tuple[float, ...]:


        values = tuple(float(value) for value in wavelengths_nm)
        if not values:
            raise ValueError("wavelengths_nm must not be empty")
        return tuple(
            self.get_n(material, wavelength_nm=value, source=source) for value in values
        )

    def abbe_number_d(
        self,
        material: str,
        *,
        source: str | None = None,
    ) -> float:


        n_d, n_f, n_c = self.spectral_indices(
            material, (587.5618, 486.1327, 656.2725), source=source
        )
        denominator = n_f - n_c
        if not math.isfinite(denominator) or abs(denominator) <= 1.0e-15:
            raise ValueError(f"cannot compute finite Abbe number for {material!r}")
        return float((n_d - 1.0) / denominator)

    def describe(
        self,
        material: str,
        *,
        reference_wavelength_nm: float = 1550.0,
        required_wavelengths_nm: Sequence[float] = (),
        source: str | None = None,
    ) -> MaterialDescriptor:


        canonical = self.normalize_material_name(material)
        entry = self.select_entry(
            canonical,
            source=source,
            wavelength_um=wavelength_nm_to_um(reference_wavelength_nm),
            require_n=True,
        )
        required = tuple(float(value) for value in required_wavelengths_nm)
        supported = tuple(
            value for value in required
            if self.supports_wavelengths(canonical, (value,), source=entry.source)
        )
        try:
            n_d = self.get_n(canonical, wavelength_nm=587.5618, source=entry.source)
            v_d = self.abbe_number_d(canonical, source=entry.source)
        except (ValueError, NotImplementedError):
            n_d = None
            v_d = None
        display = canonical[len("glass_"):] if canonical.startswith("glass_") else canonical
        return MaterialDescriptor(
            canonical_name=canonical,
            display_name=display,
            source=entry.source,
            wavelength_min_um=entry.wl_min,
            wavelength_max_um=entry.wl_max,
            reference_wavelength_nm=float(reference_wavelength_nm),
            refractive_index_reference=self.get_n(
                canonical, wavelength_nm=reference_wavelength_nm, source=entry.source
            ),
            refractive_index_d=n_d,
            abbe_number_d=v_d,
            supported_wavelengths_nm=supported,
        )

    def get_complex_index(
        self,
        material: str,
        *,
        wavelength_um: float | None = None,
        wavelength_nm: float | None = None,
        source: str | None = None,
    ) -> complex:
        result = self.evaluate(
            material,
            wavelength_um=wavelength_um,
            wavelength_nm=wavelength_nm,
            source=source,
        )
        return result.complex_index


def _maybe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except Exception:
        return None
    if not math.isfinite(out):
        return None
    return out


def _maybe_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def default_data_dir() -> Path:
    return Path(__file__).resolve().parent / "data"


@lru_cache(maxsize=1)
def default_material_database() -> MaterialDatabase:
    return MaterialDatabase(default_data_dir())
