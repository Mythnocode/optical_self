# 定义光学网络结构
# 用节点、端口和连线描述光路之间的连接关系，为合束器、分束器和多节点相干网络提供统一的数据格式
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class OpticalPortRef:


    node_id: str
    port_id: str

    @classmethod
    def parse(cls, value: str | Mapping[str, Any]) -> "OpticalPortRef":
        if isinstance(value, str):
            if "." not in value:
                raise ValueError("port reference strings must use 'node_id.port_id' format")
            node_id, port_id = value.split(".", 1)
            node_id = node_id.strip()
            port_id = port_id.strip()
        else:
            node_id = str(value.get("node_id") or value.get("node") or "").strip()
            port_id = str(value.get("port_id") or value.get("port") or "").strip()
        if not node_id or not port_id:
            raise ValueError("optical port references require both node_id and port_id")
        return cls(node_id=node_id, port_id=port_id)

    def as_dict(self) -> dict[str, str]:
        return {"node_id": self.node_id, "port_id": self.port_id}


@dataclass(frozen=True)
class OpticalNetworkNode:


    node_id: str
    node_type: str
    input_ports: dict[str, str] = field(default_factory=dict)
    output_ports: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OpticalNetworkNode":
        node_id = str(value.get("node_id") or value.get("id") or value.get("name") or "").strip()
        node_type = str(value.get("node_type") or value.get("type") or "").strip().lower()
        if not node_id:
            raise ValueError("network node requires a non-empty node_id")
        if not node_type:
            raise ValueError(f"network node {node_id!r} requires a non-empty node_type")

        raw_inputs = value.get("input_ports", value.get("inputs", {})) or {}
        if not isinstance(raw_inputs, Mapping):
            raise ValueError(f"network node {node_id!r} input_ports must be a mapping")
        input_ports = {str(k): str(v) for k, v in raw_inputs.items()}

        raw_outputs = value.get("output_ports", value.get("outputs", [])) or []
        if isinstance(raw_outputs, Mapping):
            raise ValueError(
                f"network node {node_id!r} output_ports mapping is not supported by the legacy scalar API; "
                "use an empty list or ['output_1', 'output_2']"
            )
        output_ports = [str(item).strip() for item in raw_outputs]
        if output_ports and output_ports != ["output_1", "output_2"]:
            raise ValueError(
                f"network node {node_id!r} output_ports must be omitted/empty or exactly "
                "['output_1', 'output_2'] in the legacy scalar_optical_network API"
            )

        raw_parameters = value.get("parameters", {}) or {}
        if not isinstance(raw_parameters, Mapping):
            raise ValueError(f"network node {node_id!r} parameters must be a mapping")

        reserved = {
            "node_id",
            "id",
            "name",
            "node_type",
            "type",
            "input_ports",
            "inputs",
            "output_ports",
            "outputs",
            "parameters",
        }
        parameters = {str(k): v for k, v in raw_parameters.items()}
        parameters.update({str(k): v for k, v in value.items() if k not in reserved})
        return cls(
            node_id=node_id,
            node_type=node_type,
            input_ports=input_ports,
            output_ports=output_ports,
            parameters=parameters,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "input_ports": dict(self.input_ports),
            "output_ports": list(self.output_ports),
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True)
class OpticalNetworkEdge:
    """供后续多节点网络预留的可序列化光路边描述体。"""

    edge_id: str
    source: OpticalPortRef
    target: OpticalPortRef
    parameters: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OpticalNetworkEdge":
        edge_id = str(value.get("edge_id") or value.get("id") or value.get("name") or "").strip()
        if not edge_id:
            raise ValueError("network edge requires a non-empty edge_id")
        source = OpticalPortRef.parse(value.get("source") or value.get("from"))
        target = OpticalPortRef.parse(value.get("target") or value.get("to"))
        reserved = {"edge_id", "id", "name", "source", "from", "target", "to"}
        parameters = {str(k): v for k, v in value.items() if k not in reserved}
        return cls(edge_id=edge_id, source=source, target=target, parameters=parameters)

    def as_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source": self.source.as_dict(),
            "target": self.target.as_dict(),
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True)
class ScalarOpticalNetwork:


    nodes: list[OpticalNetworkNode]
    edges: list[OpticalNetworkEdge] = field(default_factory=list)
    output_node_id: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ScalarOpticalNetwork":
        raw_nodes = value.get("nodes", [])
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raise ValueError("scalar optical network requires a non-empty nodes list")
        nodes = [OpticalNetworkNode.from_mapping(item) for item in raw_nodes]
        node_ids = [node.node_id for node in nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("scalar optical network node_id values must be unique")

        raw_edges = value.get("edges", []) or []
        if not isinstance(raw_edges, list):
            raise ValueError("scalar optical network edges must be a list")
        edges = [OpticalNetworkEdge.from_mapping(item) for item in raw_edges]

        output_node_id = value.get("output_node_id") or value.get("output_node")
        if output_node_id is not None:
            output_node_id = str(output_node_id).strip()
            if output_node_id not in set(node_ids):
                raise ValueError(f"scalar optical network output_node_id {output_node_id!r} does not match any node")
        else:
            output_node_id = nodes[-1].node_id
        return cls(nodes=nodes, edges=edges, output_node_id=output_node_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.as_dict() for node in self.nodes],
            "edges": [edge.as_dict() for edge in self.edges],
            "output_node_id": self.output_node_id,
        }
