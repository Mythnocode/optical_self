
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .analysis_mapper import AnalysisSpec
from .analysis_registry import DEFAULT_ANALYSIS_REGISTRY
from .sampling_roles import infer_sampling_role


@dataclass(frozen=True, slots=True)
class TaskNode:
    node_id: str
    kind: str
    payload: Any = None
    dependencies: tuple[str, ...] = ()


@dataclass(slots=True)
class SimulationTaskGraph:
    nodes: dict[str, TaskNode] = field(default_factory=dict)

    def add(self, node: TaskNode) -> None:
        if node.node_id in self.nodes:
            raise KeyError(f"duplicate task node: {node.node_id}")
        self.nodes[node.node_id] = node

    def topological_order(self) -> list[TaskNode]:
        pending = dict(self.nodes)
        completed: set[str] = set()
        ordered: list[TaskNode] = []
        while pending:
            ready = sorted(
                (node for node in pending.values() if set(node.dependencies) <= completed),
                key=_execution_priority,
            )
            if not ready:
                raise RuntimeError("simulation task graph contains a cycle or missing dependency")
            for node in ready:
                ordered.append(node)
                completed.add(node.node_id)
                pending.pop(node.node_id)
        return ordered



_ANALYSIS_PRIORITY = {
    
    "coupling": 10,
    "fiber_alignment": 12,
    "power_audit": 14,
    "throughput": 15,
    
    "raytrace": 20,
    "spot": 22,
    "psf": 24,
    "fourier_psf_mtf": 25,
    "psf_mtf": 25,
    "mtf": 26,
    "wavefront": 30,
    "wavefront_quality": 31,
    
    "focus_search": 50,
    "fiber_tolerance": 70,
    "coupling_research": 75,
    "quality_audit": 80,
}

def _execution_priority(node: TaskNode) -> tuple[int, str]:
    if node.kind == "scene":
        return (0, node.node_id)
    if node.kind == "trace":
        return (5, node.node_id)
    if node.kind == "analysis":
        name = str(getattr(node.payload, "name", ""))
        return (_ANALYSIS_PRIORITY.get(name, 40), node.node_id)
    return (90, node.node_id)

def build_task_graph(analyses: list[AnalysisSpec], context: Any) -> SimulationTaskGraph:
    graph = SimulationTaskGraph()
    graph.add(TaskNode("scene", "scene"))
    trace_nodes: dict[str, str] = {}
    
    
    record_surface_superset = any(
        DEFAULT_ANALYSIS_REGISTRY.resolve(spec.name).requires_complex_field
        for spec in analyses
    )
    for index, spec in enumerate(analyses):
        definition = DEFAULT_ANALYSIS_REGISTRY.resolve(spec.name)
        dependencies = ["scene"]
        if definition.requires_trace:
            group_options = dict(context.scene.options.get(definition.category.value, {}) or {})
            trace_options = {**group_options, **dict(spec.options or {})}
            if record_surface_superset:
                trace_options["record_surfaces"] = True
            sampling_role = infer_sampling_role((spec.name,), trace_options)
            
            
            
            
            
            if record_surface_superset and sampling_role in {"geometric_analysis", "complex_field_dense"}:
                sampling_role = "complex_field_dense"
            trace_options["sampling_role"] = sampling_role
            token = context.trace_key(trace_options).token()
            trace_id = trace_nodes.get(token)
            if trace_id is None:
                trace_id = f"trace:{token}"
                trace_nodes[token] = trace_id
                graph.add(TaskNode(trace_id, "trace", trace_options, ("scene",)))
            dependencies.append(trace_id)
        graph.add(TaskNode(f"analysis:{index:03d}:{spec.name}", "analysis", spec, tuple(dependencies)))
    return graph
