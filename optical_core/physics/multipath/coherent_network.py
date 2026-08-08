
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
import math

import numpy as np


@dataclass(frozen=True, slots=True)
class NetworkFieldState:
    field: np.ndarray
    wavelength_nm: float
    sample_area_mm2: float = 1.0
    optical_path_mm: float = 0.0
    delay_s: float = 0.0
    path_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        values = np.asarray(self.field, dtype=np.complex128)
        if values.ndim not in {1, 2, 3}:
            raise ValueError("network field must be scalar/Jones sampled data")
        if values.ndim == 3 and values.shape[0] not in {2, 3}:
            raise ValueError("vector network fields use leading component axis of length 2 or 3")
        if not np.all(np.isfinite(values)):
            raise ValueError("network field contains non-finite values")
        if float(self.wavelength_nm) <= 0.0 or float(self.sample_area_mm2) <= 0.0:
            raise ValueError("wavelength and sample area must be positive")
        object.__setattr__(self, "field", values)

    @property
    def power(self) -> float:
        return float(np.sum(np.abs(self.field) ** 2) * float(self.sample_area_mm2))

    def scaled(self, coefficient: complex, *, delay_s: float = 0.0, optical_path_mm: float = 0.0, path_id: str | None = None) -> "NetworkFieldState":
        return NetworkFieldState(
            field=self.field * complex(coefficient),
            wavelength_nm=self.wavelength_nm,
            sample_area_mm2=self.sample_area_mm2,
            optical_path_mm=float(self.optical_path_mm) + float(optical_path_mm),
            delay_s=float(self.delay_s) + float(delay_s),
            path_id=self.path_id if path_id is None else str(path_id),
            metadata=dict(self.metadata),
        )


@dataclass(frozen=True, slots=True)
class ScatteringNode:
    node_id: str
    input_ports: tuple[str, ...]
    output_ports: tuple[str, ...]
    scattering_matrix: np.ndarray
    jones_matrix_by_output_input: Mapping[tuple[str, str], np.ndarray] = field(default_factory=dict)

    def __post_init__(self) -> None:
        matrix = np.asarray(self.scattering_matrix, dtype=np.complex128)
        expected = (len(self.output_ports), len(self.input_ports))
        if matrix.shape != expected:
            raise ValueError(f"node {self.node_id!r} scattering matrix shape {matrix.shape} != {expected}")
        if len(set(self.input_ports)) != len(self.input_ports) or len(set(self.output_ports)) != len(self.output_ports):
            raise ValueError("network node port names must be unique")
        object.__setattr__(self, "scattering_matrix", matrix)

    @property
    def passivity_excess(self) -> float:
        singular = np.linalg.svd(self.scattering_matrix, compute_uv=False)
        return float(max((singular[0] ** 2 if singular.size else 0.0) - 1.0, 0.0))


@dataclass(frozen=True, slots=True)
class NetworkEdge:
    edge_id: str
    source_node: str
    source_port: str
    target_node: str
    target_port: str
    amplitude: complex = 1.0 + 0.0j
    loss_db: float = 0.0
    phase_rad: float = 0.0
    optical_path_mm: float = 0.0
    delay_s: float = 0.0

    @property
    def coefficient(self) -> complex:
        return complex(self.amplitude) * 10.0 ** (-max(float(self.loss_db), 0.0) / 20.0) * np.exp(1j * float(self.phase_rad))


@dataclass(frozen=True, slots=True)
class CoherentNetworkResult:
    output_states: Mapping[tuple[str, str], NetworkFieldState]
    port_contributions: Mapping[tuple[str, str], tuple[NetworkFieldState, ...]]
    metrics: Mapping[str, Any]
    warnings: tuple[str, ...] = ()


def _validate_common(states: list[NetworkFieldState]) -> None:
    if not states:
        return
    shape = states[0].field.shape
    wavelength = states[0].wavelength_nm
    area = states[0].sample_area_mm2
    for state in states[1:]:
        if state.field.shape != shape:
            raise ValueError("all network fields at a port must share a shape")
        if not math.isclose(state.wavelength_nm, wavelength, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("monochromatic coherent network inputs must share wavelength")
        if not math.isclose(state.sample_area_mm2, area, rel_tol=1e-12, abs_tol=1e-18):
            raise ValueError("all network fields must share sample area")


def coherence_matrix_from_delays(
    delays_s: np.ndarray,
    *,
    coherence_time_s: float | None,
    phase_noise_std_rad: float = 0.0,
) -> np.ndarray:
    delays = np.asarray(delays_s, dtype=float).reshape(-1)
    difference = delays[:, None] - delays[None, :]
    if coherence_time_s is None or math.isinf(float(coherence_time_s)):
        gamma = np.ones_like(difference, dtype=np.complex128)
    elif float(coherence_time_s) <= 0.0:
        gamma = np.eye(delays.size, dtype=np.complex128)
    else:
        gamma = np.exp(-0.5 * (difference / float(coherence_time_s)) ** 2).astype(np.complex128)
    if phase_noise_std_rad > 0.0:
        off_diagonal_factor = math.exp(-float(phase_noise_std_rad) ** 2)
        gamma = np.eye(delays.size) + off_diagonal_factor * (gamma - np.eye(delays.size))
    return gamma


def partially_coherent_intensity(
    states: list[NetworkFieldState],
    coherence_matrix: np.ndarray,
) -> np.ndarray:
    if not states:
        raise ValueError("at least one field state is required")
    _validate_common(states)
    gamma = np.asarray(coherence_matrix, dtype=np.complex128)
    if gamma.shape != (len(states), len(states)):
        raise ValueError("coherence matrix shape must match number of states")
    if not np.allclose(gamma, gamma.conj().T, atol=1e-10):
        raise ValueError("coherence matrix must be Hermitian")
    eigenvalues = np.linalg.eigvalsh(gamma)
    if float(np.min(eigenvalues)) < -1e-9:
        raise ValueError("coherence matrix must be positive semidefinite")
    fields = np.stack([state.field for state in states], axis=0)
    intensity = np.einsum("ij,i...,j...->...", gamma, fields, np.conj(fields), optimize=True)
    return np.maximum(np.real(intensity), 0.0)


def _combine_coherent(states: list[NetworkFieldState], path_id: str) -> NetworkFieldState:
    _validate_common(states)
    values = np.sum(np.stack([state.field for state in states], axis=0), axis=0)
    return NetworkFieldState(
        field=values,
        wavelength_nm=states[0].wavelength_nm,
        sample_area_mm2=states[0].sample_area_mm2,
        optical_path_mm=min(state.optical_path_mm for state in states),
        delay_s=min(state.delay_s for state in states),
        path_id=path_id,
        metadata={"combined_path_count": len(states)},
    )


def propagate_coherent_network(
    *,
    nodes: tuple[ScatteringNode, ...],
    edges: tuple[NetworkEdge, ...],
    source_states: Mapping[tuple[str, str], NetworkFieldState],
    output_ports: tuple[tuple[str, str], ...] | None = None,
    passivity_tolerance: float = 1e-9,
) -> CoherentNetworkResult:

    node_by_id = {node.node_id: node for node in nodes}
    if len(node_by_id) != len(nodes):
        raise ValueError("node ids must be unique")
    warnings: list[str] = []
    for node in nodes:
        if node.passivity_excess > passivity_tolerance:
            raise ValueError(f"scattering node {node.node_id!r} is active/non-passive")
    outgoing_by_source: dict[tuple[str, str], list[NetworkEdge]] = {}
    indegree = {node.node_id: 0 for node in nodes}
    for edge in edges:
        if edge.source_node not in node_by_id or edge.target_node not in node_by_id:
            raise ValueError(f"edge {edge.edge_id!r} references unknown node")
        outgoing_by_source.setdefault((edge.source_node, edge.source_port), []).append(edge)
        indegree[edge.target_node] += 1
    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    order: list[str] = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        for edge in edges:
            if edge.source_node == current:
                indegree[edge.target_node] -= 1
                if indegree[edge.target_node] == 0:
                    queue.append(edge.target_node)
    if len(order) != len(nodes):
        raise ValueError("coherent network must be acyclic")

    input_contributions: dict[tuple[str, str], list[NetworkFieldState]] = {
        key: [value] for key, value in source_states.items()
    }
    output_states_map: dict[tuple[str, str], NetworkFieldState] = {}
    output_contributions: dict[tuple[str, str], tuple[NetworkFieldState, ...]] = {}
    total_source_power = float(sum(state.power for state in source_states.values()))

    for node_id in order:
        node = node_by_id[node_id]
        input_states: list[NetworkFieldState | None] = []
        for port in node.input_ports:
            contributions = input_contributions.get((node_id, port), [])
            input_states.append(_combine_coherent(contributions, f"{node_id}.{port}") if contributions else None)
        reference = next((state for state in input_states if state is not None), None)
        if reference is None:
            continue
        for out_index, output_port in enumerate(node.output_ports):
            contributions: list[NetworkFieldState] = []
            for in_index, input_port in enumerate(node.input_ports):
                state = input_states[in_index]
                if state is None:
                    continue
                coefficient = node.scattering_matrix[out_index, in_index]
                values = state.field
                jones = node.jones_matrix_by_output_input.get((output_port, input_port))
                if jones is not None:
                    matrix = np.asarray(jones, dtype=np.complex128)
                    if values.ndim < 2 or values.shape[0] != 2 or matrix.shape != (2, 2):
                        raise ValueError("Jones device matrices require a two-component leading field axis")
                    values = np.einsum("ab,b...->a...", matrix, values, optimize=True)
                    state = NetworkFieldState(
                        field=values,
                        wavelength_nm=state.wavelength_nm,
                        sample_area_mm2=state.sample_area_mm2,
                        optical_path_mm=state.optical_path_mm,
                        delay_s=state.delay_s,
                        path_id=state.path_id,
                        metadata=state.metadata,
                    )
                contributions.append(state.scaled(coefficient, path_id=f"{state.path_id}>{node_id}.{output_port}"))
            if not contributions:
                continue
            port_key = (node_id, output_port)
            output_contributions[port_key] = tuple(contributions)
            state_out = _combine_coherent(contributions, f"{node_id}.{output_port}")
            output_states_map[port_key] = state_out
            for edge in outgoing_by_source.get(port_key, []):
                edge_state = state_out.scaled(
                    edge.coefficient,
                    delay_s=edge.delay_s,
                    optical_path_mm=edge.optical_path_mm,
                    path_id=f"{state_out.path_id}>{edge.edge_id}",
                )
                input_contributions.setdefault((edge.target_node, edge.target_port), []).append(edge_state)

    selected = output_ports or tuple(output_states_map)
    selected_power = float(sum(output_states_map[key].power for key in selected if key in output_states_map))
    return CoherentNetworkResult(
        output_states={key: output_states_map[key] for key in selected if key in output_states_map},
        port_contributions=output_contributions,
        metrics={
            "network_node_count": len(nodes),
            "network_edge_count": len(edges),
            "network_source_power": total_source_power,
            "network_selected_output_power": selected_power,
            "network_output_to_source_ratio": selected_power / max(total_source_power, 1e-30),
            "network_topological_order": order,
            "network_passive": True,
            "model": "complex_scattering_dag",
        },
        warnings=tuple(warnings),
    )


__all__ = [
    "NetworkFieldState",
    "ScatteringNode",
    "NetworkEdge",
    "CoherentNetworkResult",
    "coherence_matrix_from_delays",
    "partially_coherent_intensity",
    "propagate_coherent_network",
]
