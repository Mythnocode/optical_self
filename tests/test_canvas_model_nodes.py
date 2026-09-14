import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QApplication, QGraphicsItem

from frontend_pyside.features.canvas.lens_node import LensNode
from frontend_pyside.features.canvas.config_node import ConfigNode
from frontend_pyside.features.canvas.dataset_node import DatasetNode
from frontend_pyside.features.canvas.model_node import ModelNode
from frontend_pyside.features.canvas.native_summary_node import NativeSummaryNode
from frontend_pyside.features.canvas.registry import specs
from frontend_pyside.features.canvas.scene import CanvasScene
from frontend_pyside.features.canvas.task_node import TaskNode
from frontend_pyside.features.canvas.task_runner import _augment_payload
from frontend_pyside.features.canvas.parameter_catalog import (
    APERTURE_TYPE_CHOICES,
    CALC_PRECISION_CHOICES,
    DATASET_SAMPLING_CHOICES,
    DATASET_TARGET_CHOICES,
    LAYOUT_PUPIL_CHOICES,
    PROPAGATION_CHOICES,
    RECEIVER_MODE_CHOICES,
    SOURCE_TYPE_CHOICES,
    VALIDATION_METRIC_CHOICES,
    VALIDATION_REFERENCE_CHOICES,
)


def _app():
    return QApplication.instance() or QApplication([])


def test_legacy_dropdown_catalog_is_not_reduced_by_node_split():
    assert SOURCE_TYPE_CHOICES == ("高斯模式", "均匀光瞳", "点光源")
    assert APERTURE_TYPE_CHOICES == ("圆形通光孔径", "矩形孔径", "椭圆孔径", "用户孔径")
    assert RECEIVER_MODE_CHOICES == ("高斯近似", "LP01", "HE11", "导入复场")
    assert CALC_PRECISION_CHOICES == ("129×129", "257×257", "513×513", "1025×1025")
    assert LAYOUT_PUPIL_CHOICES == ("7 × 7", "9 × 9", "13 × 13", "17 × 17")
    assert PROPAGATION_CHOICES == ("普通角谱", "带限角谱", "缩放角谱", "缩放 Fresnel", "ISSC", "Fresnel")
    assert DATASET_SAMPLING_CHOICES == ("Latin Hypercube", "Sobol低差异采样")
    assert DATASET_TARGET_CHOICES == ("耦合损耗(dB)", "耦合效率", "RMS 光斑", "Strehl")
    assert VALIDATION_METRIC_CHOICES == ("E003 耦合效率", "E004 横向 3 dB 全宽", "E006 角度 3 dB 全宽", "自定义指标")
    assert VALIDATION_REFERENCE_CHOICES == ("实验数据", "文献理论")


def test_lens_and_model_nodes_do_not_embed_full_pages():
    _app()
    scene = CanvasScene()
    lens = scene.add_node("lens_editor", QPointF(300, 120), expanded=True)
    model = scene.add_node("random_forest", QPointF(1040, 160), expanded=True)

    assert isinstance(lens, LensNode)
    assert lens.editor().__class__.__name__ == "LensSurfaceTable"
    assert isinstance(model, ModelNode)
    assert model._chrome_settings and model._chrome_run

    model.toggle_parameter_capsules()
    assert len(model._capsules) == 5
    assert len(model._parameter_edges) == 5
    assert len(scene.edges()) == 1
    assert all(edge.direction == 1 for edge in model._parameter_edges)


def test_model_config_is_snapshotted_and_training_payload_is_typed():
    _app()
    scene = CanvasScene()
    model = scene.add_node("random_forest")
    model.config.update({"dataset_id": "d1", "max_depth": 0, "max_features": "1.0"})
    snap = scene.snapshot()
    restored = CanvasScene()
    assert restored.restore(snap)
    assert restored.nodes_by_key("random_forest")[0].config["dataset_id"] == "d1"

    payload = {}
    _augment_payload(payload, "random_forest", model.config)
    assert payload["dataset_id"] == "d1"
    assert payload["model_type"] == "random_forest"
    assert "max_depth" not in payload["hyperparameters"]
    assert payload["hyperparameters"]["max_features"] == 1.0


def test_task_config_is_restored_without_accepting_unknown_fields():
    _app()
    scene = CanvasScene()
    task = scene.add_node("scan")
    assert isinstance(task, TaskNode)
    task.restore_config({"param_label": "镜头前表面半径", "unknown": "ignored"})
    assert task.config["param_label"] == "镜头前表面半径"
    assert "unknown" not in task.config


def test_ribbon_specs_never_register_full_page_factories():
    _app()
    assert all(not item.factory_path for item in specs())
    scene = CanvasScene()
    for key in ("overview", "system", "model_manage", "data", "tasks"):
        node = scene.add_node(key)
        if key == "data":
            assert isinstance(node, DatasetNode)
        else:
            assert isinstance(node, NativeSummaryNode)
        assert node.__class__.__name__ != "PanelNode"


def test_inverse_design_nodes_use_native_optimization_payloads():
    _app()
    scene = CanvasScene()
    physical = scene.add_node("physical_inverse")
    ml_inverse = scene.add_node("ml_inverse")
    assert isinstance(physical, TaskNode)
    assert isinstance(ml_inverse, TaskNode)
    assert physical._chrome_settings and physical._chrome_run
    assert ml_inverse._chrome_settings and ml_inverse._chrome_run

    physical_payload = {}
    _augment_payload(physical_payload, "physical_inverse", physical.config)
    assert physical_payload["opt_objectives"][0]["goal"] == "target"
    assert physical_payload["opt_options"]["mode"] == "physical_inverse_design"

    ml_inverse.config["surrogate_model_id"] = "model-1"
    ml_payload = {}
    _augment_payload(ml_payload, "ml_inverse", ml_inverse.config)
    assert ml_payload["opt_options"]["surrogate_model_id"] == "model-1"
    assert ml_payload["opt_options"]["coarse_fraction"] == 0.88


def test_legacy_panel_snapshot_restores_as_compact_native_node():
    _app()
    scene = CanvasScene()
    assert scene.restore({
        "version": 1,
        "nodes": [{
            "id": "physical_inverse#old",
            "key": "physical_inverse",
            "x": 100,
            "y": 80,
            "w": 1120,
            "h": 760,
            "expanded": True,
        }],
        "edges": [],
    })
    node = scene.node("physical_inverse#old")
    assert isinstance(node, TaskNode)
    assert node._full_w == 420
    assert node._full_h < 520
    assert node.__class__.__name__ != "PanelNode"


def test_compute_settings_uses_capsules_instead_of_embedded_form():
    _app()
    scene = CanvasScene()
    node = scene.add_node("compute_settings", expanded=True)
    assert isinstance(node, ConfigNode)
    assert not hasattr(node, "_host")
    node.toggle_parameter_capsules()
    assert len(node._capsules) == 4
    assert len(node._parameter_edges) == 4
    assert len(scene.edges()) == 0


def test_dataset_flow_keeps_research_dataset_and_model_edges():
    _app()
    scene = CanvasScene()
    lens = scene.add_node("lens_editor")
    scan = scene.add_node("scan")
    data = scene.add_node("data")
    model = scene.add_node("random_forest")
    assert lens is not None and scan is not None and data is not None and model is not None
    pairs = {(edge.source.spec.key, edge.target.spec.key) for edge in scene.edges()}
    assert ("lens_editor", "scan") in pairs
    assert ("scan", "data") in pairs
    assert ("data", "random_forest") in pairs
    assert ("lens_editor", "random_forest") not in pairs
    assert scan.pos().x() > lens.pos().x()
    assert data.pos().x() > scan.pos().x()
    assert model.pos().x() > data.pos().x()


def test_outgoing_edge_ports_follow_target_vertical_order():
    _app()
    scene = CanvasScene()
    lens = scene.add_node("lens_editor", QPointF(0.0, 0.0))
    lower = scene.add_node("mtf", QPointF(400.0, 280.0))
    upper = scene.add_node("intensity", QPointF(400.0, 20.0))
    assert lens is not None and lower is not None and upper is not None
    scene.refresh_attached_edges(lens)
    starts = {
        edge.target.spec.key: edge.path().elementAt(0).y
        for edge in scene.edges()
        if edge.source is lens
    }
    assert starts["intensity"] < starts["mtf"]


def test_incident_edges_thicken_blue_when_node_selected_and_brighten_on_hover():
    _app()
    scene = CanvasScene()
    lens = scene.add_node("lens_editor", QPointF(0.0, 0.0))
    chart = scene.add_node("mtf", QPointF(400.0, 40.0))
    assert lens is not None and chart is not None
    edge = next(item for item in scene.edges() if item.source is lens and item.target is chart)
    assert scene.edge_highlight_for(edge) == ""
    chart.setSelected(True)
    QApplication.instance().processEvents()
    assert scene.edge_highlight_for(edge) == "selected"
    assert edge.pen().color().name().lower() == "#1d4ed8"
    assert edge.pen().widthF() == 3.0
    chart.setSelected(False)
    QApplication.instance().processEvents()
    scene.set_hovered_node(lens)
    assert scene.edge_highlight_for(edge) == "hover"
    assert edge.pen().widthF() == 2.2
    scene.set_hovered_node(None)
    scene.clearSelection()
    QApplication.instance().processEvents()
    assert scene.edge_highlight_for(edge) == ""
    assert edge.pen().widthF() < 2.0


def test_compute_settings_is_not_auto_wired_into_data_flow():
    _app()
    scene = CanvasScene()
    scene.add_node("lens_editor")
    scene.add_node("compute_settings")
    scene.add_node("mtf")
    pairs = {(edge.source.spec.key, edge.target.spec.key) for edge in scene.edges()}
    assert ("lens_editor", "mtf") in pairs
    assert ("lens_editor", "compute_settings") not in pairs


def test_model_run_without_dataset_stays_failed_instead_of_submitting():
    _app()
    from types import SimpleNamespace
    from frontend_pyside.state.registry_context import RegistryContext

    registry = RegistryContext()
    context = SimpleNamespace(registry=registry, services=SimpleNamespace(), api_client=None)
    model_spec = next(item for item in specs() if item.key == "random_forest")
    model = ModelNode("random_forest#empty", model_spec, "random_forest", context=context)
    emitted: list[str] = []
    model.taskRunRequested.connect(emitted.append)
    model.run_task()
    assert emitted == []
    assert model.phase == "failed"
    assert "数据集" in model.summary_text()


def test_model_dataset_selection_is_shared_with_registry():
    _app()
    from types import SimpleNamespace
    from frontend_pyside.state.registry_context import RegistryContext

    registry = RegistryContext()
    context = SimpleNamespace(registry=registry, services=SimpleNamespace(), api_client=None)
    model_spec = next(item for item in specs() if item.key == "random_forest")
    model = ModelNode("random_forest#ctx", model_spec, "random_forest", context=context)
    registry.set_datasets([{"dataset_id": "dataset-1", "dataset_name": "研究样本", "sample_count": 50}])
    registry.set_current_dataset("dataset-1")
    assert model.config["dataset_id"] == "dataset-1"


def test_model_dataset_api_list_accepts_backend_items_shape():
    _app()
    from types import SimpleNamespace
    from frontend_pyside.state.registry_context import RegistryContext

    registry = RegistryContext()
    context = SimpleNamespace(registry=registry, services=SimpleNamespace(), api_client=None)
    model_spec = next(item for item in specs() if item.key == "random_forest")
    model = ModelNode("random_forest#api", model_spec, "random_forest", context=context)
    model._dataset_list_key = "dataset-list"
    model._on_api_completed("dataset-list", {"items": [{"dataset_id": "dataset-api", "dataset_name": "API 数据集"}]})
    assert registry.dataset("dataset-api")["dataset_name"] == "API 数据集"


def test_xgboost_legacy_early_stop_fields_are_forwarded():
    payload = {}
    _augment_payload(payload, "xgboost_physics_residual", {
        "dataset_id": "dataset-1",
        "target_name": "coupling_loss_db",
        "early_stopping": True,
        "patience": 37,
        "early_stopping_rounds": 25,
        "seed": 42,
    })
    assert payload["hyperparameters"]["early_stopping_rounds"] == 37


def test_xgboost_early_stop_can_be_turned_off():
    from frontend_pyside.features.canvas.model_node import MODEL_DEFINITIONS, coerce_bool

    training = next(group for group in MODEL_DEFINITIONS["xgboost_physics_residual"].groups if group[0] == "training")
    fields = {field.key: field for field in training[2]}
    assert fields["early_stopping"].kind == "bool"
    assert "early_stopping_rounds" not in fields

    assert coerce_bool("False") is False
    assert coerce_bool("false") is False
    assert coerce_bool("True") is True
    payload = {}
    _augment_payload(payload, "xgboost_physics_residual", {
        "dataset_id": "dataset-1",
        "target_name": "coupling_loss_db",
        "early_stopping": "False",
        "patience": 37,
        "early_stopping_rounds": 25,
        "seed": 42,
    })
    assert payload["hyperparameters"]["early_stopping"] is False
    assert payload["hyperparameters"]["early_stopping_rounds"] == 0


def _node_rect(node):
    return QRectF(node.pos().x(), node.pos().y(), node._w, node.height)


def test_auto_layout_spreads_workflow_lanes():
    _app()
    scene = CanvasScene()
    lens = scene.add_node("lens_editor", expanded=True)
    chart = scene.add_node("mtf", expanded=True)
    data = scene.add_node("data", expanded=True)
    model = scene.add_node("random_forest", expanded=True)
    chart.setPos(lens.pos())
    data.setPos(lens.pos())
    model.setPos(lens.pos())
    scene.auto_layout()
    assert lens.pos().x() < chart.pos().x() < data.pos().x() < model.pos().x()
    assert chart.pos().x() != data.pos().x()
    assert not _node_rect(lens).intersects(_node_rect(chart))
    assert not _node_rect(chart).intersects(_node_rect(data))
    assert not _node_rect(data).intersects(_node_rect(model))


def test_auto_layout_uses_expanded_size_and_keeps_info_child():
    _app()
    scene = CanvasScene()
    lens = scene.add_node("lens_editor", expanded=True)
    forward = scene.add_node("forward", expanded=True)
    result = scene.add_node("forward_result", expanded=True)
    chart = scene.add_node("mtf", expanded=True)
    wave = scene.add_node("wave", expanded=True)
    data = scene.add_node("data", expanded=True)
    forward.result_child_id = result.node_id
    scene.connect_edge(forward.node_id, result.node_id)
    forward.setPos(QPointF(120.0, 80.0))
    result.setPos(lens.pos())
    chart.setPos(QPointF(120.0, 80.0))
    wave.setPos(QPointF(120.0, 900.0))
    data.setPos(lens.pos())
    scene.auto_layout()

    assert chart.pos().x() == wave.pos().x()
    assert chart.pos().y() < wave.pos().y()
    vertical_gap = wave.pos().y() - (chart.pos().y() + chart.height)
    assert vertical_gap >= 47.0

    assert result.pos().x() == forward.pos().x() + forward._w + 48.0
    assert result.pos().y() == forward.pos().y()

    assert lens.pos().x() < chart.pos().x() < data.pos().x() < forward.pos().x()
    assert not _node_rect(lens).intersects(_node_rect(forward))
    assert not _node_rect(forward).intersects(_node_rect(chart))
    assert not _node_rect(forward).intersects(_node_rect(data))
    assert not _node_rect(result).intersects(_node_rect(chart))
    assert not _node_rect(result).intersects(_node_rect(data))


def test_auto_layout_finds_info_child_without_edge():
    _app()
    scene = CanvasScene()
    scene.add_node("lens_editor", expanded=True)
    forward = scene.add_node("forward", expanded=True)
    result = scene.add_node("forward_result", expanded=True)
    forward.result_child_id = result.node_id
    result.setPos(QPointF(40.0, 40.0))
    scene.auto_layout()
    assert result.pos().x() == forward.pos().x() + forward._w + 48.0
    assert result.pos().y() == forward.pos().y()


def test_tolerance_rows_keep_per_parameter_distribution_and_legacy_options():
    payload = {}
    _augment_payload(payload, "tolerance", {
        "params": [
            {"path": "source.wavelength_nm", "nominal": 780.0, "sigma": 2.0, "distribution_label": "均匀", "enabled": True},
            {"path": "receiver.offset_x_mm", "nominal": 0.0, "sigma": 0.01, "distribution_label": "三角", "enabled": False},
        ],
        "sampling": "Sobol",
        "distribution": "正态",
        "sample_count": 256,
        "candidate": "当前最优候选",
        "template": "优化参数 + 常用装调",
        "threshold_efficiency": 0.9,
        "include_deterministic_sensitivity": True,
    })
    assert payload["tolerance_parameters"][0]["distribution"]["name"] == "uniform"
    assert payload["tolerance_parameters"][1]["distribution"]["name"] == "triangular"
    assert payload["tolerance_parameters"][1]["enabled"] is False
    assert payload["tolerance_sampling_method"] == "sobol"
    assert payload["tolerance_options"]["include_deterministic_budget"] is True


def test_bilstm_can_select_generated_dataset_path_from_registry():
    _app()
    from types import SimpleNamespace
    from frontend_pyside.state.registry_context import RegistryContext

    registry = RegistryContext()
    context = SimpleNamespace(registry=registry, services=SimpleNamespace(), api_client=None)
    model_spec = next(item for item in specs() if item.key == "bilstm_structure_sequence")
    model = ModelNode("bilstm#ctx", model_spec, "bilstm_structure_sequence", context=context)
    registry.set_datasets([{
        "dataset_id": "dataset-sequence",
        "dataset_name": "序列样本",
        "training_samples_flat_csv_path": "D:/datasets/sequence/samples_flat.csv",
    }])
    registry.set_current_dataset("dataset-sequence")
    assert model.config["dataset_path"].endswith("sequence/samples_flat.csv")


def test_forward_host_clips_oversized_combo_to_node_card():
    _app()
    scene = CanvasScene()
    node = scene.add_node("forward", expanded=True)
    inner_w = node._full_w - 24.0
    assert node.panel.model_combo.itemText(0) == "（暂无已训练模型）"
    assert node._host.flags() & QGraphicsItem.GraphicsItemFlag.ItemClipsToShape
    node.panel.model_combo.setEnabled(True)
    node.panel.model_combo.clear()
    node.panel.model_combo.addItem("（暂无已训练模型，请先生成数据集并训练）" * 3, "")
    node._host.sync_geometry(*node._content_geometry())
    assert node._host.boundingRect().width() <= inner_w + 0.5
    host_rect = node._host.sceneBoundingRect()
    card_rect = node.sceneBoundingRect()
    assert host_rect.right() <= card_rect.right() + 0.5
    assert host_rect.left() >= card_rect.left() - 0.5
    assert node.panel.model_combo.sizeHint().width() < node._w


def test_explain_node_follows_current_model_instead_of_static_placeholder():
    _app()
    from types import SimpleNamespace
    from frontend_pyside.features.canvas.explain_node import ExplainNode
    from frontend_pyside.state.registry_context import RegistryContext

    registry = RegistryContext()
    context = SimpleNamespace(registry=registry, services=SimpleNamespace(), api_client=None)
    scene = CanvasScene()
    node = scene.add_node("model_explain", expanded=True)
    assert isinstance(node, ExplainNode)
    assert "选择模型后计算" not in node.summary_text()
    assert "请先训练" in node.summary_text()
    node.context = context
    node._bind_context()
    registry.merge_model({
        "model_id": "model-xgb",
        "name": "XGBoost物理残差",
        "model_type": "xgboost_physics_residual",
        "dataset_id": "dataset-1",
    })
    registry.set_current_model("model-xgb")
    assert node._model_title(node._current_model()) == "XGBoost物理残差"
    assert "参数贡献" in node.summary_text()


def test_shap_contribution_rows_use_chinese_effects():
    from frontend_pyside.features.canvas.explain_node import shap_contribution_rows

    rows = shap_contribution_rows(
        {
            "target_name": "coupling_loss_db",
            "top_features": [
                {"feature": "size_log_mismatch", "mean_shap": 0.4},
                {"feature": "receiver.offset_x_mm", "mean_shap": -0.2},
            ],
        }
    )
    assert rows[0][0] == "尺寸失配程度（对数）"
    assert "增加损耗" in rows[0][1]
    assert "光纤 X 方向偏移" in rows[1][0]
    assert "降低损耗" in rows[1][1]
