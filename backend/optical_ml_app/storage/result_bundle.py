from __future__ import annotations

import json
from pathlib import Path
import re
import os
from typing import Any

import numpy as np

from backend.optical_ml_app.storage.atomic_files import atomic_write_text, atomic_write_via


BUNDLE_VERSION = 1
ARRAY_THRESHOLD = 2048
TABLE_THRESHOLD = 256
ANALYSIS_KEYS = {
    "raytrace", "rays", "spot", "spot_diagram", "psf", "mtf", "wavefront",
    "coupling", "field", "receiver_field", "amplitude", "phase", "scan",
    "history", "predictions", "residuals", "shap", "explainability",
    "tolerance", "multipath", "paths", "plots", "test_predictions",
}


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(value)).strip("._")
    return cleaned[:100] or "section"


def _is_numeric_sequence(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or not value:
        return False
    try:
        array = np.asarray(value)
    except Exception:
        return False
    return array.dtype.kind in "biufc" and array.size >= ARRAY_THRESHOLD


def _table_candidate(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= TABLE_THRESHOLD
        and all(isinstance(row, dict) for row in value[: min(32, len(value))])
    )


def _externalize(value: Any, arrays: dict[str, np.ndarray], path: str) -> Any:
    if isinstance(value, np.ndarray):
        if value.size >= ARRAY_THRESHOLD and value.dtype.kind in "biufc":
            key = _safe_name(path or f"array_{len(arrays)}")
            while key in arrays:
                key = f"{key}_{len(arrays)}"
            arrays[key] = np.ascontiguousarray(value)
            return {"__array_ref__": key, "shape": list(value.shape), "dtype": str(value.dtype)}
        return value.tolist()
    if _is_numeric_sequence(value):
        array = np.asarray(value)
        key = _safe_name(path or f"array_{len(arrays)}")
        while key in arrays:
            key = f"{key}_{len(arrays)}"
        arrays[key] = np.ascontiguousarray(array)
        return {"__array_ref__": key, "shape": list(array.shape), "dtype": str(array.dtype)}
    if isinstance(value, dict):
        return {
            str(key): _externalize(item, arrays, f"{path}.{key}" if path else str(key))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _externalize(item, arrays, f"{path}.{index}" if path else str(index))
            for index, item in enumerate(value)
        ]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _restore(value: Any, arrays: Any) -> Any:
    if isinstance(value, dict) and "__array_ref__" in value:
        key = str(value["__array_ref__"])
        return arrays[key].tolist()
    if isinstance(value, dict):
        return {key: _restore(item, arrays) for key, item in value.items()}
    if isinstance(value, list):
        return [_restore(item, arrays) for item in value]
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str),
        encoding="utf-8",
    )


def _try_write_parquet(path: Path, rows: list[dict]) -> bool:
    try:
        import pandas as pd
        frame = pd.DataFrame(rows)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
        return True
    except Exception:
        return False



def _write_npz(path: Path, arrays: dict[str, np.ndarray]) -> None:
    # Deflate compression is CPU-heavy and used to dominate the visible 98-99%
    # tail of otherwise fast jobs.  Stored NPZ preserves dtype/shape/values
    # exactly and is fully compatible with np.load; compression remains opt-in
    # for disk-constrained deployments.
    mode = str(os.getenv("OPTICAL_RESULT_NPZ_COMPRESSION", "stored") or "stored").strip().lower()
    writer = np.savez_compressed if mode in {"compressed", "deflate", "zip"} else np.savez
    with Path(path).open("wb") as handle:
        writer(handle, **arrays)


def save_result_bundle(job_dir: Path, payload: Any) -> dict[str, Any]:
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    analyses_dir = job_dir / "analyses"
    analyses_dir.mkdir(exist_ok=True)
    arrays: dict[str, np.ndarray] = {}
    manifest: dict[str, Any] = {
        "version": BUNDLE_VERSION,
        "metadata": "result_metadata.json",
        "arrays": None,
        "sections": {},
        "analysis_views": {},
        "array_container": "npz",
        "array_compression": (
            "deflate" if str(os.getenv("OPTICAL_RESULT_NPZ_COMPRESSION", "stored")).strip().lower()
            in {"compressed", "deflate", "zip"} else "stored"
        ),
    }
    if not isinstance(payload, dict):
        payload = {"result": payload}

    metadata: dict[str, Any] = {}
    encoded_values: dict[str, Any] = {}
    for key, value in payload.items():
        name = _safe_name(str(key))
        if _table_candidate(value):
            parquet = analyses_dir / f"{name}.parquet"
            if _try_write_parquet(parquet, value):
                manifest["sections"][str(key)] = {"format": "parquet", "path": str(parquet.relative_to(job_dir))}
                continue
        encoded = _externalize(value, arrays, str(key))
        encoded_values[str(key)] = encoded
        is_analysis = str(key).lower() in ANALYSIS_KEYS
        if is_analysis or isinstance(value, (list, tuple, np.ndarray)):
            section_path = analyses_dir / f"{name}.json"
            _write_json(section_path, encoded)
            manifest["sections"][str(key)] = {"format": "json", "path": str(section_path.relative_to(job_dir))}
        else:
            metadata[str(key)] = encoded

    
    
    
    
    
    
    payload_metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    requested = payload_metadata.get("requested_analyses")
    requested_single = (
        str(requested[0]).strip()
        if isinstance(requested, (list, tuple))
        and len(requested) == 1
        and str(requested[0]).strip()
        else ""
    )
    primary_analysis = payload_metadata.get("analysis") or payload.get("analysis") or payload.get("analysis_type")
    if not primary_analysis:
        primary_analysis = requested_single
    if isinstance(primary_analysis, str) and primary_analysis.strip():
        analysis_name = primary_analysis.strip()
        view_keys = (
            "request_id", "status", "metrics", "arrays", "warnings", "errors",
            "elapsed_ms", "converged", "metadata",
        )
        view = {key: encoded_values[key] for key in view_keys if key in encoded_values}
        if view:
            view_path = analyses_dir / f"{_safe_name(analysis_name)}.json"
            _write_json(view_path, view)
            descriptor = {
                "format": "json",
                "path": str(view_path.relative_to(job_dir)),
            }
            manifest["analysis_views"][analysis_name] = descriptor
            
            
            
            
            if requested_single and requested_single != analysis_name:
                manifest["analysis_views"][requested_single] = dict(descriptor)

    _write_json(job_dir / "result_metadata.json", metadata)
    if arrays:
        atomic_write_via(
            job_dir / "result_arrays.npz",
            lambda tmp: _write_npz(tmp, arrays),
        )
        manifest["arrays"] = "result_arrays.npz"
    _write_json(job_dir / "result_manifest.json", manifest)
    legacy = job_dir / "result.json"
    if legacy.exists():
        legacy.unlink()
    return manifest


def _load_section(job_dir: Path, descriptor: dict[str, Any]) -> Any:
    path = job_dir / str(descriptor["path"])
    if descriptor.get("format") == "parquet":
        try:
            import pandas as pd
            return pd.read_parquet(path).to_dict(orient="records")
        except Exception as exc:
            raise RuntimeError(f"cannot read parquet result section: {path}") from exc
    return json.loads(path.read_text(encoding="utf-8"))


def load_result_bundle(job_dir: Path, analysis: str | None = None) -> Any:
    job_dir = Path(job_dir)
    manifest_path = job_dir / "result_manifest.json"
    if not manifest_path.exists():
        legacy = job_dir / "result.json"
        if not legacy.exists():
            raise FileNotFoundError(legacy)
        return json.loads(legacy.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    arrays_path = manifest.get("arrays")
    arrays = np.load(job_dir / arrays_path, allow_pickle=False) if arrays_path else {}
    try:
        sections = manifest.get("sections", {})
        if analysis is not None:
            if analysis in sections:
                return _restore(_load_section(job_dir, sections[analysis]), arrays)
            analysis_views = manifest.get("analysis_views", {})
            if analysis in analysis_views:
                return _restore(_load_section(job_dir, analysis_views[analysis]), arrays)
            raise KeyError(analysis)
        metadata = json.loads((job_dir / manifest.get("metadata", "result_metadata.json")).read_text(encoding="utf-8"))
        result = _restore(metadata, arrays)
        for key, descriptor in sections.items():
            result[key] = _restore(_load_section(job_dir, descriptor), arrays)
        return result
    finally:
        close = getattr(arrays, "close", None)
        if callable(close):
            close()


def bundle_size(job_dir: Path) -> int:
    total = 0
    for path in Path(job_dir).rglob("*"):
        if not path.is_file() or "live_arrays" in path.parts:
            continue
        total += path.stat().st_size
    return total


def load_result_summary(job_dir: Path) -> dict[str, Any]:

    job_dir = Path(job_dir)
    manifest_path = job_dir / "result_manifest.json"
    if not manifest_path.exists():
        result = load_result_bundle(job_dir)
        if not isinstance(result, dict):
            return {"result": result}
        return {
            key: value for key, value in result.items()
            if key not in ANALYSIS_KEYS and not isinstance(value, (list, tuple, np.ndarray))
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata_path = job_dir / manifest.get("metadata", "result_metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["available_sections"] = sorted((manifest.get("sections") or {}).keys())
    metadata["available_analysis_views"] = sorted((manifest.get("analysis_views") or {}).keys())
    metadata["bundle_version"] = int(manifest.get("version", BUNDLE_VERSION))
    return metadata
