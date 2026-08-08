from __future__ import annotations

from typing import Any

from optical_core.models.domain.optical_network import ScalarOpticalNetwork
from optical_core.physics.multipath.coherent_combination import _read, _require_mapping
from optical_core.physics.multipath.ideal_scalar_combiner import summarize_ideal_2x2_scalar_combiner
from optical_core.physics.multipath.power_combination import validate_non_negative_finite


SUPPORTED_SCALAR_NODE_TYPES = {
    "ideal_2x2_scalar_combiner",
    "ideal-2x2-scalar-combiner",
    "ideal_2x2_combiner",
    "scalar_2x2_combiner",
    "beam_combiner_2x2",
    "beam_splitter_2x2",
}


def _path_id(path: Any, index: int) -> str:
    return str(_read(path, "path_id", "id", default=f"path_{index + 1}")).strip()


def _network_from_combination(combination_options: dict[str, Any]) -> ScalarOpticalNetwork:
    raw_network = combination_options.get("network") or combination_options.get("optical_network")
    if raw_network is None:
        raise ValueError("scalar_optical_network requires combination.network")
    if not isinstance(raw_network, dict):
        raise ValueError("combination.network must be a mapping")
    return ScalarOpticalNetwork.from_mapping(raw_network)


def _ordered_input_paths_for_2x2_node(*, node_input_ports: dict[str, str], paths: list[Any]) -> list[Any]:
    path_by_id = {_path_id(path, idx): path for idx, path in enumerate(paths)}
    required_ports = ("input_1", "input_2")
    missing_ports = [port for port in required_ports if port not in node_input_ports]
    if missing_ports:
        raise ValueError(
            "ideal 2x2 scalar network node requires input_ports for input_1 and input_2; missing "
            + ", ".join(missing_ports)
        )
    ordered: list[Any] = []
    for port in required_ports:
        path_id = str(node_input_ports[port]).strip()
        if path_id not in path_by_id:
            raise ValueError(f"network node input port {port} references unknown path_id {path_id!r}")
        ordered.append(path_by_id[path_id])
    return ordered


def _node_combiner_options(node_parameters: dict[str, Any], combination_options: dict[str, Any]) -> dict[str, Any]:
    allowed_global_keys = {
        "default_input_power_w",
        "phase_offsets_rad_by_path",
        "return_network_arrays",
        "return_combiner_arrays",
        "energy_conservation_tolerance",
        "transmission_amplitude",
        "reflection_amplitude",
        "transmission_power",
        "reflection_power",
        "transmission_phase_rad",
        "reflection_phase_rad",
    }
    options = {k: v for k, v in combination_options.items() if k in allowed_global_keys}
    options.update(node_parameters)
    return options


def _prefix_node_arrays(arrays: dict[str, Any], *, node_id: str) -> dict[str, Any]:
    prefixed: dict[str, Any] = {}
    for key, value in arrays.items():
        if key.startswith("multipath_2x2_"):
            suffix = key[len("multipath_2x2_") :]
            prefixed[f"multipath_network_{node_id}_{suffix}"] = value
        else:
            prefixed[f"multipath_network_{node_id}_{key}"] = value
    return prefixed


def summarize_scalar_optical_network(
    path_results: dict[str, dict[str, Any]],
    *,
    raw_arrays_by_path: dict[str, dict[str, Any]],
    paths: list[Any],
    default_input_power_w: float = 1.0e-3,
    phase_offsets_rad_by_path: dict[str, Any] | None = None,
    return_network_arrays: bool = False,
    combination_options: dict[str, Any] | None = None,
) -> dict[str, Any]:


    default_input_power_w = validate_non_negative_finite(
        default_input_power_w,
        name="default_input_power_w",
    )
    phase_offsets_rad_by_path = _require_mapping(
        phase_offsets_rad_by_path,
        "phase_offsets_rad_by_path",
    )
    combination_options = dict(combination_options or {})
    network = _network_from_combination(combination_options)

    warnings: list[str] = []
    arrays: dict[str, Any] = {}

    if len(network.nodes) != 1:
        raise ValueError(
            "legacy scalar_optical_network supports exactly one device node; "
            "use coherent_network for multi-node propagation"
        )
    if network.edges:
        raise ValueError(
            "legacy scalar_optical_network does not yet propagate graph edges; use coherent_network"
        )

    node = network.nodes[0]
    if node.node_type not in SUPPORTED_SCALAR_NODE_TYPES:
        raise ValueError(f"unsupported scalar optical network node_type {node.node_type!r}")
    if network.output_node_id != node.node_id:
        raise ValueError("legacy scalar optical network output_node_id must be the single supported node_id")

    ordered_paths = _ordered_input_paths_for_2x2_node(node_input_ports=node.input_ports, paths=paths)
    ordered_input_ids = [_path_id(path, idx) for idx, path in enumerate(ordered_paths)]

    unknown_phase_ids = sorted(set(phase_offsets_rad_by_path) - set(_path_id(path, idx) for idx, path in enumerate(paths)))
    if unknown_phase_ids:
        raise ValueError(
            "phase_offsets_rad_by_path contains unknown path_id values: "
            + ", ".join(unknown_phase_ids)
        )

    node_options = _node_combiner_options(node.parameters, combination_options)
    node_summary = summarize_ideal_2x2_scalar_combiner(
        path_results,
        raw_arrays_by_path=raw_arrays_by_path,
        paths=ordered_paths,
        default_input_power_w=default_input_power_w,
        phase_offsets_rad_by_path=phase_offsets_rad_by_path,
        return_port_arrays=return_network_arrays,
        combination_options=node_options,
    )
    node_arrays = dict(node_summary.pop("arrays", {}) or {})
    if node_arrays:
        arrays.update(_prefix_node_arrays(node_arrays, node_id=node.node_id))
    warnings.extend(node_summary.get("warnings", []) or [])

    summary_complete = bool(node_summary.get("ideal_2x2_summary_complete", False))
    energy_conservation_passed = bool(node_summary.get("energy_conservation_passed", False))

    result: dict[str, Any] = {
        "mode": "scalar_optical_network",
        "power_unit": "W",
        "network_stage": "stage5_nodeized_scalar_network",
        "model_note": (
            "Frozen one-node scalar compatibility model. It intentionally omits physical surface "
            "branching, coating physics and Jones propagation. Use coherent_network for general "
            "multi-node field propagation and nonsequential RayTree for physical reflection/diffraction paths."
        ),
        "network_summary_complete": summary_complete,
        "node_count": len(network.nodes),
        "edge_count": len(network.edges),
        "output_node_id": network.output_node_id,
        "network": network.as_dict(),
        "node_order": [node.node_id],
        "node_type_by_id": {node.node_id: node.node_type},
        "input_ports_by_node": {node.node_id: dict(node.input_ports)},
        "output_ports_by_node": {node.node_id: list(node.output_ports or ["output_1", "output_2"])},
        "ordered_input_path_ids": ordered_input_ids,
        "node_summaries": {node.node_id: node_summary},
        "output_node_summary": node_summary,
        "best_output_port_id": node_summary.get("best_output_port_id"),
        "best_output_coupled_power_w": node_summary.get("best_output_coupled_power_w"),
        "total_input_power_w": node_summary.get("total_input_power_w"),
        "total_transmitted_power_w": node_summary.get("total_transmitted_power_w"),
        "total_output_field_power_w": node_summary.get("total_output_field_power_w"),
        "total_output_coupled_power_w": node_summary.get("total_output_coupled_power_w"),
        "output_field_power_w_by_port": dict(node_summary.get("output_field_power_w_by_port", {}) or {}),
        "output_coupled_power_w_by_port": dict(node_summary.get("output_coupled_power_w_by_port", {}) or {}),
        "output_overlap_efficiency_by_port": dict(node_summary.get("output_overlap_efficiency_by_port", {}) or {}),
        "energy_conservation_checked": bool(node_summary.get("energy_conservation_checked", False)),
        "energy_conservation_passed": energy_conservation_passed,
        "energy_conservation_error_w": node_summary.get("energy_conservation_error_w"),
        "relative_energy_conservation_error": node_summary.get("relative_energy_conservation_error"),
        "coefficient_unitary_like": bool(node_summary.get("coefficient_unitary_like", False)),
        "coefficient_info_by_node": {node.node_id: dict(node_summary.get("coefficient_info", {}) or {})},
        "network_assumption_grid_checked": bool(node_summary.get("combiner_assumption_grid_checked", False)),
        "network_assumption_grid_uniform_checked": bool(node_summary.get("combiner_assumption_grid_uniform_checked", False)),
        "network_assumption_wavelength_checked": bool(node_summary.get("combiner_assumption_wavelength_checked", False)),
        "network_assumption_mode_phase_checked": bool(node_summary.get("combiner_assumption_mode_phase_checked", False)),
        "network_assumption_polarization_checked": False,
        "network_assumption_phase_reference_checked": False,
        "warnings": warnings,
    }
    if arrays:
        result["arrays"] = arrays
    return result
