<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { onBackendConnected } from '../domain/backend-connection.js';
import {storeToRefs} from 'pinia';
import {useModelWorkspaceStore} from '../stores/model-workspace.js';
import { useRoute, useRouter } from "vue-router";
import BaseToast from "../components/BaseToast.vue";
import SimulationResultView from "../components/SimulationResultView.vue";
import type { ResultKind } from "../domain/simulation-results.js";
import SimulationLensEditor from "../components/SimulationLensEditor.vue";
import SimulationInspectors from "../components/SimulationInspectors.vue";
import MaterialLibraryView from '../components/MaterialLibraryView.vue';
import { useSimulationStore } from "../stores/simulation.js";
import { surfaceName, surfaceTypes } from "../domain/simulation-project.js";
import TrainingResultView from "../components/TrainingResultView.vue";
import SimulationNumber from '../components/SimulationNumber.vue';
import DatasetGeneration from '../components/DatasetGeneration.vue';
import DatasetStateIcon from '../components/DatasetStateIcon.vue';
import OptimizationRail from '../components/OptimizationRail.vue';
import OptimizationVariables from '../components/OptimizationVariables.vue';
import OptimizationResult from '../components/OptimizationResult.vue';
import ScanView from '../components/ScanView.vue';
import ExplainabilityRail from '../components/ExplainabilityRail.vue';
import ExplainabilityGlobal from '../components/ExplainabilityGlobal.vue';
import ExplainabilityParameter from '../components/ExplainabilityParameter.vue';
import ExplanationParameterRail from '../components/ExplanationParameterRail.vue';
import ExplainabilityCurrent from '../components/ExplainabilityCurrent.vue';
import CurrentExplanationRail from '../components/CurrentExplanationRail.vue';
import {useDatasetGenerationStore} from '../stores/dataset-generation.js';
import type { LocalFileSelection } from "../../../desktop/bridge-contract.js";
import { useDatasetsStore } from "../stores/datasets.js";
import { useModelsStore } from "../stores/models.js";
import { useTrainingStore } from "../stores/training.js";
import { getProjectFeatures, type ModelRecord, type PredictionResult } from "../api/models.js";

interface WorkbenchItem {
  key: string;
  kind: string;
  title: string;
  subtitle: string;
  icon: string;
}

const route = useRoute();
const router = useRouter();
const datasets = useDatasetsStore();
const models = useModelsStore();
const training = useTrainingStore();
const simulation = useSimulationStore();
const generation = useDatasetGenerationStore();
const {datasetSource,datasetSampleMode,datasetFile,sequenceFileReady,trainingOptionsOpen,randomForestTrees,randomForestDepth,randomForestLeaf,randomForestMaxFeatures,xgboostRounds,xgboostLearningRate,xgboostDepth,xgboostSubsample,xgboostFeatureSample,bilstmEpochs,bilstmBatchSize,sequenceSystemIdColumn,sequenceOrderColumn,sequenceElementTypeColumn,sequenceNumericColumns,sequenceTargetColumns}=storeToRefs(useModelWorkspaceStore());
const familyDatasets=computed(()=>datasets.items.filter(item=>(item.dataset_layout==='sequence_long'?'sequence':'tabular')===datasetSampleMode.value));
const datasetNotice = ref("");
const datasetNoticeTone = ref<"info" | "success" | "warning" | "error">("info");

const moduleInfo: Record<string, { title: string; items: WorkbenchItem[]; objects: string[] }> = {
  simulation: {
    title: "仿真",
    items: [
      { key: "lens_data", kind: "lens_data", title: "镜头数据", subtitle: "镜头数据表格", icon: "sim_lens_data.png" },
      { key: "layout", kind: "ray_layout", title: "光路图", subtitle: "仿真光路图", icon: "sim_layout.png" },
      { key: "image_quality", kind: "spot", title: "光斑图", subtitle: "成像质量分析", icon: "sim_spot.png" },
      { key: "fiber_coupling", kind: "coupling", title: "光纤耦合", subtitle: "耦合结果", icon: "sim_fiber_coupling.png" },
      { key: "wave_diffraction", kind: "wavefront", title: "波前与衍射", subtitle: "波前分析", icon: "sim_wavefront.png" },
    ],
    objects: ["光源", "L1 · 镜头", "L2 · 镜头", "L3 · 镜头", "L4 · 镜头", "像面", "光纤"],
  },
  model: {
    title: "模型",
    items: [
      { key: "dataset", kind: "dataset", title: "数据集", subtitle: "数据准备与生成", icon: "ml_dataset.png" },
      { key: "train_result", kind: "train_result", title: "训练结果", subtitle: "模型训练与评估", icon: "ml_train_result.png" },
      { key: "predict_eval", kind: "predict", title: "模型预测", subtitle: "预测与评估", icon: "ml_predict.png" },
    ],
    objects: ["内置演示·780 nm 四透镜八变量", "数据集", "已训练模型"],
  },
  optimization: {
    title: "优化",
    items: [
      { key: "scan", kind: "scan", title: "扫描", subtitle: "单变量与双变量扫描", icon: "opt_scan.png" },
      { key: "opt_vars", kind: "opt_vars", title: "优化", subtitle: "选择变量与范围", icon: "opt_vars.png" },
      { key: "opt_result", kind: "opt_result", title: "优化结果", subtitle: "候选对照与写入", icon: "opt_result.png" },
    ],
    objects: ["优化目标", "优化变量", "约束条件"],
  },
  explainability: {
    title: "解释",
    items: [
      { key: "global_contrib", kind: "global_contrib", title: "贡献排序", subtitle: "SHAP 全局重要性", icon: "explain_global.png" },
      { key: "param_trend", kind: "param_trend", title: "物理链路", subtitle: "参数与目标变化", icon: "explain_trend.png" },
    ],
    objects: ["数据集", "训练模型", "目标指标"],
  },
};

const moduleKey = computed(() => String(route.params.module ?? "simulation"));
const definition = computed(() => moduleInfo[moduleKey.value] ?? moduleInfo.simulation);
const activeKind = computed(() => String(route.params.kind ?? definition.value.items[0]?.kind ?? ""));
const activeItem = computed(() => definition.value.items.find((item) => item.kind === activeKind.value || item.key === activeKind.value || (activeKind.value === "layout_3d" && item.kind === "ray_layout")) ?? definition.value.items[0]);


watch([moduleKey, activeKind], ([module, kind]) => {
  if (module === "model" && kind === "dataset") {
    void datasets.refresh();
  }
  if (module === "model" && kind !== "dataset") {
    void models.refresh();
  }
}, { immediate: true });

onBackendConnected(() => {
  if (moduleKey.value !== 'model') return;
  if (activeKind.value === 'dataset') void datasets.refresh();
  else void models.refresh();
});

interface SurfaceRow {
  number: number;
  name: string;
  type: string;
  radius: string;
  thickness: string;
  material: string;
  aperture: string;
  a6: string;
}

const surfaceRows = computed<SurfaceRow[]>(() => simulation.project.surfaces.map((surface) => ({
  number: surface.index + 1, name: surfaceName(surface), type: surfaceTypes[surface.surface_type] || surface.surface_type,
  radius: String(surface.radius_mm ?? 0), thickness: String(surface.distance_to_next_mm),
  material: surface.material_after, aperture: String(surface.clear_aperture_mm ?? 0), a6: String(surface.asphere_coefficients[1] ?? 0),
})));

interface PredictionInputRow {
  key: string;
  feature: string;
  label: string;
  value: number | null;
  displayValue: string;
  unit: string;
}

const selectedModel = computed(() => models.selected);
const projectFeatures = ref<Record<string, number>>({});
const projectFeaturesLoading = ref(false);
const projectFeaturesError = ref("");
let featureRequestVersion = 0;
watch([() => selectedModel.value?.model_id, () => simulation.revision, activeKind], async () => {
  const version = ++featureRequestVersion;
  projectFeatures.value = {}; projectFeaturesError.value = ""; projectFeaturesLoading.value = false;
  models.clearPrediction();
  const record = selectedModel.value;
  if (!record || models.isSequenceModel(record) || !['predict', 'predict_eval'].includes(activeKind.value) || !record.feature_paths?.length) return;
  projectFeaturesLoading.value = true;
  try { const values = await getProjectFeatures(simulation.project, record.feature_paths); if (version === featureRequestVersion) projectFeatures.value = values; }
  catch (cause) { if (version === featureRequestVersion) projectFeaturesError.value = cause instanceof Error ? cause.message : String(cause); }
  finally { if (version === featureRequestVersion) projectFeaturesLoading.value = false; }
}, { immediate: true });
const sequenceBindings = computed(() => simulation.project.surfaces.slice(0, -1).flatMap((surface, index) =>
  ['', 'AIR', 'VACUUM', '空气', '真空'].includes(surface.material_after.trim().toUpperCase()) ? [] : [{ front: index, back: index + 1 }],
));
const modelIsSequence = computed(() => Boolean(selectedModel.value && models.isSequenceModel(selectedModel.value)));
const modelTargets = computed(() => (selectedModel.value?.target_names ?? []).map(displayTargetName).join("、") || "—");
const modelVersion = computed(() => selectedModel.value?.model_version || selectedModel.value?.version || selectedModel.value?.model_id || "—");
const modelUsability = computed(() => selectedModel.value ? modelPredictionStatus(selectedModel.value) : { usable: false, reason: "请先选择模型。" });
const predictionInputs = computed(() => {
  const record = selectedModel.value;
  if (!record) return [] as PredictionInputRow[];
  if (models.isSequenceModel(record)) return sequenceInputRows(record);
  return (record.feature_paths ?? []).map((feature, index) => {
    const value = projectFeatures.value[feature] ?? null;
    return {
      key: `${feature}-${index}`,
      feature,
      label: displayFeatureName(feature),
      value,
      displayValue: value === null ? "当前系统未提供" : formatFeatureNumber(value),
      unit: featureUnit(record, feature, index),
    };
  });
});
const predictionReady = computed(() => Boolean(
  selectedModel.value
  && modelUsability.value.usable
  && predictionInputs.value.length
  && predictionInputs.value.every((row) => row.value !== null),
));
const trainingBusy = computed(() => Boolean(
  training.submitting
  || (training.job && !["completed", "failed", "cancelled"].includes(String(training.job.status))),
));
watch(()=>datasets.manifest,(manifest)=>{
  if(manifest?.dataset_id!==datasets.selectedId)return;
  const family=manifest.metadata?.dataset_layout==='sequence_long'?'sequence':'tabular';
  if(datasetSampleMode.value!==family){datasetSampleMode.value=family;trainingOptionsOpen.value=false;}
});

function numericText(value: string): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function sequenceInputRows(record: ModelRecord): PredictionInputRow[] {
  const names = record.numeric_feature_names ?? [];
  const lensCount = sequenceBindings.value.length;
  const rows: PredictionInputRow[] = [];
  for (let lensIndex = 0; lensIndex < lensCount; lensIndex += 1) {
    const front = surfaceRows.value[sequenceBindings.value[lensIndex].front];
    const back = surfaceRows.value[sequenceBindings.value[lensIndex].back];
    for (let featureIndex = 0; featureIndex < names.length; featureIndex += 1) {
      const feature = names[featureIndex];
      const value = sequenceFeatureValue(feature, front, back);
      rows.push({
        key: `${lensIndex}-${featureIndex}-${feature}`,
        feature,
        label: `L${lensIndex + 1} · ${displayFeatureName(feature)}`,
        value,
        displayValue: value === null ? "当前系统未提供" : formatFeatureNumber(value),
        unit: featureUnit(record, feature, featureIndex),
      });
    }
  }
  return rows;
}

function sequenceFeatureValue(feature: string, front: SurfaceRow, back: SurfaceRow): number | null {
  const aliases: Record<string, string> = {
    radius_mm: front.radius,
    front_radius_mm: front.radius,
    back_radius_mm: back.radius,
    thickness_mm: front.thickness,
    front_semi_aperture_mm: front.aperture,
    back_semi_aperture_mm: back.aperture,
    air_gap_after_mm: back.thickness,
    front_conic: String(simulation.project.surfaces[front.number - 1].conic),
    back_conic: String(simulation.project.surfaces[back.number - 1].conic),
    receiver_offset_x_um: String(simulation.project.receiver.offset_x_mm * 1000),
    receiver_offset_y_um: String(simulation.project.receiver.offset_y_mm * 1000),
    receiver_axial_offset_z_um: String(simulation.project.receiver.axial_offset_z_mm * 1000),
  };
  const value = aliases[feature];
  return value === undefined ? null : numericText(value);
}

function featureUnit(record: ModelRecord, feature: string, index: number): string {
  const units = record.feature_units;
  if (Array.isArray(units)) return String(units[index] ?? "");
  if (units && typeof units === "object") return String(units[feature] ?? "");
  if (/_mm$/.test(feature)) return "mm";
  if (/_um$/.test(feature)) return "μm";
  if (/_nm$/.test(feature)) return "nm";
  return "";
}

function formatFeatureNumber(value: number): string {
  return Number(value.toPrecision(6)).toString();
}

function displayFeatureName(path: string): string {
  const surface = path.match(/^surfaces?(?:\[(\d+)\]|\.(\d+))\.(.+)$/i);
  if (surface) {
    const index = Number(surface[1] ?? surface[2]) + 1;
    const names: Record<string, string> = {
      radius_mm: "曲率半径",
      thickness_mm: "厚度",
      distance_to_next_mm: "厚度",
      semi_aperture_mm: "半口径",
      conic: "圆锥系数",
    };
    return `第${index}面${names[surface[3]] ?? surface[3]}`;
  }
  const labels: Record<string, string> = {
    radius_mm: "曲率半径",
    thickness_mm: "厚度",
    front_radius_mm: "前表面曲率半径",
    back_radius_mm: "后表面曲率半径",
    front_conic: "前表面圆锥系数",
    back_conic: "后表面圆锥系数",
    front_semi_aperture_mm: "前表面半口径",
    back_semi_aperture_mm: "后表面半口径",
    air_gap_after_mm: "后方空气间隔",
    coupling_loss_db: "耦合损耗（dB）",
    coupling_efficiency: "耦合效率",
    rms_spot_radius_um: "RMS 光斑半径（μm）",
    strehl_estimate_marechal: "Strehl 比",
  };
  if (labels[path]) return labels[path];
  return path.includes(".") ? `未登记特征：${path}` : path;
}

function displayTargetName(target: string): string {
  return displayFeatureName(target);
}

function displayModelType(type: string | undefined): string {
  const labels: Record<string, string> = {
    random_forest: "随机森林",
    xgboost_physics_residual: "XGBoost 物理残差",
    bilstm_structure_sequence: "BiLSTM 元件序列",
  };
  return labels[String(type || "")] || type || "模型";
}

function modelPredictionStatus(record: ModelRecord): { usable: boolean; reason: string } {
  if (record.status && record.status !== "available") {
    return { usable: false, reason: record.manifest_error || "该模型状态不可用。" };
  }
  if (record.model_quality?.prediction_usable === false) {
    return { usable: false, reason: record.model_quality.reason || "该模型质量未达到预测门槛。" };
  }
  const rawTestR2 = record.test_metrics?.r2;
  if (rawTestR2 !== undefined && rawTestR2 !== null) {
    const testR2 = Number(rawTestR2);
    if (!Number.isFinite(testR2) || testR2 <= 0) {
      return {
        usable: false,
        reason: Number.isFinite(testR2)
          ? `测试 R²=${formatFeatureNumber(testR2)}，低于 0，不能用于当前镜头预测。`
          : "该模型的测试 R² 不是有效数值，不能用于预测。",
      };
    }
  }
  return { usable: true, reason: "" };
}

function selectModelFromInput(event: Event): void {
  const target = event.target;
  if (target instanceof HTMLSelectElement) models.select(target.value);
}

function selectAndAdoptModel(modelId: string): void {
  models.adopt(modelId);
  if (activeKind.value === "train_result") training.viewModel(modelId);
}

async function runModelPrediction(): Promise<void> {
  const record = selectedModel.value;
  if (!record || !modelUsability.value.usable) return;
  if (!predictionReady.value) {
    const unavailable = predictionInputs.value.filter((row) => row.value === null).map((row) => row.label);
    showDatasetNotice(
      unavailable.length
        ? `当前系统缺少模型输入：${unavailable.slice(0, 3).join("、")}${unavailable.length > 3 ? " 等" : ""}`
        : "当前模型没有可用的输入字段。",
      "warning",
    );
    return;
  }
  try {
    if (models.isSequenceModel(record)) {
      const numericNames = record.numeric_feature_names ?? [];
      const numericValues: number[][] = [];
      const lensCount = sequenceBindings.value.length;
      for (let index = 0; index < lensCount; index += 1) {
        const front = surfaceRows.value[sequenceBindings.value[index].front];
        const back = surfaceRows.value[sequenceBindings.value[index].back];
        numericValues.push(numericNames.map((name) => sequenceFeatureValue(name, front, back) as number));
      }
      const elementTypes = Array.from({ length: lensCount }, (_, index) => {
        const material = surfaceRows.value[sequenceBindings.value[index].front]?.material || "lens";
        return material === "AIR" ? "lens" : material;
      });
      await models.runSequencePrediction({ element_types: elementTypes, numeric_values: numericValues });
    } else {
      const features = Object.fromEntries(predictionInputs.value.map((row) => [row.feature, row.value as number]));
      await models.runPrediction(features);
    }
  } catch {
    // The store keeps the API error beside the prediction result for display.
  }
}

function predictionRows(result: PredictionResult | null): Array<[string, string]> {
  if (!result) return [];
  const predictions = result.predictions;
  if (predictions && typeof predictions === "object") {
    return Object.entries(predictions).map(([target, value]) => [
      displayFeatureName(target),
      typeof value === "number" && Number.isFinite(value) ? formatFeatureNumber(value) : String(value),
    ]);
  }
  return [];
}

function openItem(item: WorkbenchItem): void {
  void router.push({ name: "workbench", params: { module: moduleKey.value, kind: item.kind } });
}

async function chooseDatasetFile(): Promise<void> {
  const desktop = window.opticalDesktop;
  if (!desktop) {
    showDatasetNotice("本机文件导入需要在 Electron 桌面版中操作。", "warning");
    return;
  }
  try {
    const selected = await desktop.selectTabularDatasetFile();
    if (selected) {
      datasetFile.value = selected;
      sequenceFileReady.value = false;
      datasets.select("");
      datasetNotice.value = "";
    }
  } catch (cause) {
    showDatasetNotice(cause instanceof Error ? cause.message : String(cause), "error");
  }
}

async function importDatasetFile(): Promise<void> {
  if (!datasetFile.value || datasets.importing) return;
  if (datasetSampleMode.value !== "tabular") {
    sequenceFileReady.value = true;
    showDatasetNotice(`元件序列文件已就绪：${datasetFile.value.name}`, "success");
    return;
  }
  try {
    await datasets.importFile(datasetFile.value);
    showDatasetNotice(`已导入并选中：${datasetFile.value.name}`, "success");
  } catch (cause) {
    showDatasetNotice(cause instanceof Error ? cause.message : String(cause), "error");
  }
}

function selectBuiltinDataset(): void {
  const available = datasets.items.find((item) => item.dataset_id === "dataset-880bdde6c292");
  if (!available) {
    showDatasetNotice("当前没有可用的内置数据集。", "warning");
    return;
  }
  datasetFile.value = null;
  datasets.select(available.dataset_id);
  datasetNotice.value = "";
}

function selectDataset(datasetId: string): void {
  datasetFile.value = null;
  datasets.select(datasetId);
}

function changeDatasetSource(): void {
  datasetFile.value = null;
  sequenceFileReady.value = false;
  datasets.select("");
}

function changeDatasetSampleMode(): void {
  datasetFile.value = null;
  sequenceFileReady.value = false;
  trainingOptionsOpen.value = false;
  datasets.select("");
}

function toggleTrainingFamily(): void {
  datasetSampleMode.value = datasetSampleMode.value === "tabular" ? "sequence" : "tabular";
  changeDatasetSampleMode();
}

function parseColumnNames(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

async function startTraining(): Promise<void> {
  if (trainingBusy.value || generation.busy) return;
  try {
    validateTrainingOptions();
    if (datasetSampleMode.value === "sequence") {
      const generated=datasets.manifest?.dataset_id===datasets.selectedId && datasets.manifest.metadata?.dataset_layout==='sequence_long'?datasets.manifest.metadata:null;
      const generatedPath=String(generated?.sequence_dataset_path??'');
      if (!generatedPath && (!datasetFile.value || !sequenceFileReady.value)) {
        showDatasetNotice("请选择元件序列表格并点击“导入”，再开始 BiLSTM 训练。", "warning");
        return;
      }
      const numericFeatures = generated?listManifestValues(generated.numeric_feature_columns):parseColumnNames(sequenceNumericColumns.value);
      const targets = generated?listManifestValues(generated.target_columns):parseColumnNames(sequenceTargetColumns.value);
      if (!numericFeatures.length || !targets.length) {
        showDatasetNotice("请填写至少一个数值特征列和一个目标列。", "warning");
        return;
      }
      await training.submitBiLSTM({
        dataset_path: generatedPath||datasetFile.value!.path,
        system_id_column: String(generated?.system_id_column??sequenceSystemIdColumn.value.trim()) || "system_id",
        order_column: String(generated?.order_column??sequenceOrderColumn.value.trim()) || "element_index",
        element_type_column: String(generated?.element_type_column??sequenceElementTypeColumn.value.trim()) || "element_type",
        numeric_feature_columns: numericFeatures,
        target_columns: targets,
        config: {
          max_epochs: bilstmEpochs.value,
          batch_size: bilstmBatchSize.value,
          random_seed: generation.options.random_seed,
        },
      });
    } else {
      if (!datasets.selectedId) {
        showDatasetNotice("请选择已就绪的数据集后再开始训练。", "warning");
        return;
      }
      await training.submitJoint({
        dataset_id: datasets.selectedId,
        random_seed: generation.options.random_seed,
        random_forest_hyperparameters: {
          n_estimators: randomForestTrees.value,
          max_depth: randomForestDepth.value,
          min_samples_leaf: randomForestLeaf.value,
          max_features: randomForestMaxFeatures.value === "1.0" ? 1 : randomForestMaxFeatures.value,
        },
        xgboost_hyperparameters: {
          n_estimators: xgboostRounds.value,
          learning_rate: xgboostLearningRate.value,
          max_depth: xgboostDepth.value,
          subsample: xgboostSubsample.value,
          colsample_bytree: xgboostFeatureSample.value,
        },
      });
    }
    showDatasetNotice("训练任务已提交，可在训练结果页或任务中心查看进度。", "success");
    await router.push({ name: "workbench", params: { module: "model", kind: "train_result" } });
  } catch (cause) {
    showDatasetNotice(cause instanceof Error ? cause.message : String(cause), "error");
  }
}

function validateTrainingOptions(): void {
  const fields: Array<[string, unknown, number, number, boolean]> = datasetSampleMode.value === "sequence"
    ? [["最大轮数", bilstmEpochs.value, 1, 5000, true], ["批大小", bilstmBatchSize.value, 1, 1024, true]]
    : [
      ["树数量", randomForestTrees.value, 1, 10000, true],
      ["最大深度（0=自动）", randomForestDepth.value, 0, 256, true],
      ["叶节点最小样本", randomForestLeaf.value, 1, 100, true],
      ["迭代轮数", xgboostRounds.value, 10, 10000, true],
      ["学习率", xgboostLearningRate.value, 0.000001, 1, false],
      ["最大深度", xgboostDepth.value, 1, 32, true],
      ["样本采样率", xgboostSubsample.value, 0.01, 1, false],
      ["特征采样率", xgboostFeatureSample.value, 0.01, 1, false],
    ];
  for (const [label, value, low, high, integer] of fields) {
    if (typeof value !== "number" || !Number.isFinite(value) || value < low || value > high || (integer && !Number.isInteger(value))) {
      throw new Error(`${label}必须是 ${low} 到 ${high} 之间的${integer ? "整数" : "数值"}。`);
    }
  }
}

function showDatasetNotice(message: string, tone: "info" | "success" | "warning" | "error"): void {
  datasetNotice.value = message;
  datasetNoticeTone.value = tone;
}

async function exportDatasetManifest(): Promise<void> {
  const datasetId = datasets.selectedId;
  if (!datasetId) {
    showDatasetNotice("请先选择数据集。", "warning");
    return;
  }
  try {
    const manifest = datasets.manifest?.dataset_id === datasetId
      ? datasets.manifest
      : await datasets.loadManifest(datasetId);
    const contents = JSON.stringify(manifest, null, 2);
    const fileName = `${datasets.details?.dataset_name || datasetId}-manifest.json`;
    const desktop = window.opticalDesktop;
    if (desktop) {
      const saved = await desktop.saveTextFile({ suggestedName: fileName, contents });
      if (!saved.canceled) showDatasetNotice(`Manifest 已保存：${saved.name || fileName}`, "success");
      return;
    }
    const url = URL.createObjectURL(new Blob([contents], { type: "application/json;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = fileName;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
    showDatasetNotice(`Manifest 已导出：${fileName}`, "success");
  } catch (cause) {
    showDatasetNotice(cause instanceof Error ? cause.message : String(cause), "error");
  }
}

function listManifestValues(values: unknown): string[] {
  return Array.isArray(values) ? values.map(String) : [];
}
</script>

<template>
  <section class="workbench-page" :class="`${moduleKey}-page`">
    <nav class="secondary-bar" :aria-label="`${definition.title}功能`">
      <button
        v-for="item in definition.items"
        :key="item.key"
        class="secondary-button"
        :class="[`${moduleKey}-secondary-button`, { active: activeItem?.key === item.key && !(moduleKey==='explainability'&&activeKind==='current_system') }]"
        type="button"
        :title="item.subtitle"
        @click="openItem(item)"
      >
        <img :src="`/icons/${item.icon}`" alt="" />
        <span>{{ item.title }}</span>
      </button>
    </nav>
    <div class="workbench-body">
      <aside class="object-rail" :class="{ 'simulation-object-rail': moduleKey === 'simulation', 'model-object-rail': moduleKey === 'model', 'optimization-object-rail': moduleKey === 'optimization', 'explainability-object-rail': moduleKey === 'explainability' }">
        <h2 class="rail-title">{{ moduleKey === 'model' ? (activeKind === 'dataset' ? '数据集' : activeKind === 'train_result' || activeKind === 'train' ? '训练结果' : '模型预测') : moduleKey === 'explainability' ? (activeKind==='param_trend'?'参数':'模型') : moduleKey === 'optimization' ? '优化' : '对象' }}</h2>
        <template v-if="moduleKey === 'simulation'">
          <SimulationInspectors />
        </template>
        <template v-else-if="moduleKey === 'model' && activeKind === 'dataset'">
          <div class="dataset-library" aria-label="数据集列表">
            <section v-if="generation.jobId && !generation.completedDatasetId && generation.options.family===datasetSampleMode" class="dataset-generation-progress" :class="{'generation-failed':generation.job?.status==='failed','generation-cancelled':generation.job?.status==='cancelled'}" aria-label="数据集生成" :title="!generation.submitting&&generation.job?.error?(typeof generation.job.error==='string'?generation.job.error:generation.job.error.message):generation.status">
              <div class="generation-progress-title"><span>数据集生成</span><span class="dataset-selection-check" :aria-label="generation.job?.status==='failed'?'生成失败':generation.job?.status==='cancelled'?'已取消':'已选中'"><DatasetStateIcon :failed="generation.job?.status==='failed'||generation.job?.status==='cancelled'" /></span><button v-if="generation.busy" type="button" :disabled="generation.cancelling||generation.submitting" @click="generation.cancel">{{generation.cancelling?'取消中':'取消'}}</button></div>
              <div class="generation-progress-values"><span>{{generation.status}} {{Math.round((generation.submitting?0:generation.job?.progress??0)*100)}}%</span><progress :value="generation.submitting?0:generation.job?.progress??0" max="1" aria-label="数据集生成进度"></progress></div>
            </section>
            <button
              v-for="item in familyDatasets"
              :key="item.dataset_id"
              type="button"
              :class="{ selected: datasets.selectedId === item.dataset_id }"
              :aria-pressed="datasets.selectedId === item.dataset_id"
              :title="`${item.dataset_name || item.dataset_id} · ${item.sample_count} 个样本`"
              @click="selectDataset(item.dataset_id)"
            ><span>{{ item.dataset_name || item.dataset_id }}</span><span v-if="datasets.selectedId===item.dataset_id" class="dataset-selection-check" aria-label="已选中"><DatasetStateIcon /></span></button>
            <span v-if="datasets.loading && !datasets.loadedFromBackend" class="dataset-list-status">正在读取数据集…</span>
            <span v-else-if="datasets.loadedFromBackend && !datasets.items.length" class="dataset-list-status">暂无数据集</span>
            <span v-if="datasets.error" class="dataset-list-error">{{ datasets.error }}</span>
          </div>
        </template>
        <template v-else-if="moduleKey === 'model'">
          <div class="dataset-library model-library" aria-label="模型列表">
            <button
              v-for="item in models.records"
              :key="item.model_id"
              type="button"
              :class="{ selected: models.selectedId === item.model_id, adopted: activeKind !== 'train_result' && models.currentModelId === item.model_id }"
              :aria-pressed="models.selectedId === item.model_id"
              :title="`${models.displayName(item)} · ${displayModelType(item.model_type)}`"
              @click="selectAndAdoptModel(item.model_id)"
            >{{ models.displayName(item) }}</button>
            <span v-if="models.loading && !models.loaded" class="dataset-list-status">正在读取模型…</span>
            <span v-else-if="models.loaded && !models.records.length" class="dataset-list-status">暂无可用模型</span>
            <span v-if="models.error" class="dataset-list-error">{{ models.error }}</span>
          </div>
          <section v-if="selectedModel && activeKind !== 'train_result'" class="model-details" aria-label="模型详情">
            <header><strong>{{ models.displayName(selectedModel) }}</strong><span>{{ selectedModel.status || 'available' }}</span></header>
            <dl class="model-details-grid">
              <div><dt>类型</dt><dd>{{ displayModelType(selectedModel.model_type) }}</dd></div>
              <div><dt>版本 / ID</dt><dd>{{ modelVersion }}</dd></div>
              <div><dt>目标</dt><dd>{{ modelTargets }}</dd></div>
              <div><dt>创建</dt><dd>{{ selectedModel.created_at || '—' }}</dd></div>
            </dl>
            <button
              class="model-adopt-button"
              type="button"
              :disabled="models.currentModelId === selectedModel.model_id"
              @click="selectAndAdoptModel(selectedModel.model_id)"
            >{{ models.currentModelId === selectedModel.model_id ? '当前模型' : '设为当前模型' }}</button>
          </section>
        </template>
        <template v-else-if="moduleKey === 'optimization'">
          <OptimizationRail />
        </template>
        <template v-else-if="moduleKey === 'explainability'">
          <ExplanationParameterRail v-if="activeKind==='param_trend'" />
          <CurrentExplanationRail v-else-if="activeKind==='current_system'" />
          <ExplainabilityRail v-else />
        </template>
        <template v-else>
          <input class="rail-search" type="search" placeholder="筛选…" aria-label="筛选对象" />
          <div class="rail-list">
            <button v-for="object in definition.objects" :key="object" type="button">{{ object }}</button>
          </div>
        </template>
      </aside>
      <main class="workbench-documents" :class="{ 'simulation-document-layout': moduleKey === 'simulation' && activeKind === 'lens_data', 'simulation-materials-layout': moduleKey === 'simulation' && ['material_library','materials'].includes(activeKind), 'simulation-results-layout': moduleKey === 'simulation' && !['lens_data','material_library','materials'].includes(activeKind), 'model-document-layout': moduleKey === 'model' && activeKind === 'dataset', 'model-predict-document-layout': moduleKey === 'model' && (activeKind === 'predict' || activeKind === 'predict_eval'), 'optimization-document-layout': moduleKey === 'optimization' && ['scan','opt_vars','opt_result'].includes(activeKind), 'explainability-document-layout': moduleKey === 'explainability' && ['global_contrib','param_trend','current_system'].includes(activeKind) }">
        <template v-if="moduleKey === 'simulation' && activeKind === 'lens_data'">
          <SimulationLensEditor />
        </template>
        <MaterialLibraryView v-else-if="moduleKey==='simulation' && ['material_library','materials'].includes(activeKind)" />
        <SimulationResultView v-else-if="moduleKey === 'simulation'" :kind="(activeKind === 'layout_3d' ? 'layout_3d' : activeItem.kind) as ResultKind" @related="router.push({ name: 'workbench', params: { module: 'simulation', kind: $event } })" />
        <template v-else-if="moduleKey === 'model' && activeKind === 'dataset'">
          <div class="model-dataset-layout">
            <section class="model-form-panel model-data-panel" :class="{ 'model-data-generation-panel':datasetSource==='generate', 'model-data-sequence-panel': datasetSampleMode === 'sequence' && datasetFile }">
              <h2>1. 数据</h2>
              <label class="model-form-row"><span>数据来源</span><select v-model="datasetSource" aria-label="数据来源" @change="changeDatasetSource"><option value="import">导入</option><option value="generate">生成</option></select></label>
              <template v-if="datasetSource === 'import'">
                <label class="model-form-row"><span>采样方式</span><select v-model="datasetSampleMode" aria-label="采样方式" @change="changeDatasetSampleMode"><option value="tabular">按照镜头</option><option value="sequence">按照元件</option></select></label>
                <div class="model-file-row">
                  <input type="text" readonly :value="datasetFile?.name ?? ''" :placeholder="datasetSampleMode === 'sequence' ? '选择自定义长表后映射列；内置结构表无需映射' : '选择 CSV / JSONL 表格样本'" aria-label="所选数据文件" />
                  <button type="button" :disabled="datasets.importing" @click="chooseDatasetFile">选择文件</button>
                  <button type="button" :disabled="!datasetFile || datasets.importing" @click="importDatasetFile">{{ datasets.importing ? '导入中…' : datasetSampleMode === 'sequence' && sequenceFileReady ? '已就绪' : '导入' }}</button>
                  <button type="button" :disabled="datasetSampleMode === 'sequence'" :aria-pressed="datasets.selectedId === 'dataset-880bdde6c292'" @click="selectBuiltinDataset">内置</button>
                </div>
                <section v-if="datasetSampleMode === 'sequence' && datasetFile && sequenceFileReady" class="training-options-group sequence-mapping-group"><h3>列对应（自定义文件）</h3><div class="sequence-mapping-grid">
                  <label>系统编号列<input v-model="sequenceSystemIdColumn" /></label>
                  <label>元件顺序列<input v-model="sequenceOrderColumn" /></label>
                  <label>元件类型列<input v-model="sequenceElementTypeColumn" /></label>
                  <label>半径/厚度列<input v-model="sequenceNumericColumns" /></label>
                  <label>目标列<input v-model="sequenceTargetColumns" /></label>
                </div></section>
              </template>
              <DatasetGeneration v-show="datasetSource==='generate'" :visible="datasetSource==='generate'" :family="datasetSampleMode" :training-busy="trainingBusy" @toggle-family="toggleTrainingFamily" />
            </section>
            <section class="model-form-panel model-training-panel" :class="{ 'model-training-panel-expanded': trainingOptionsOpen, 'model-training-sequence-panel': datasetSampleMode === 'sequence' }">
              <h2>2. 训练</h2>
              <div class="model-training-actions"><button class="fixed-lens-count" type="button" @click="toggleTrainingFamily">{{ datasetSampleMode === 'tabular' ? '固定镜头数' : '任意镜头数' }}</button><button class="model-more-button" type="button" :aria-expanded="trainingOptionsOpen" @click="trainingOptionsOpen = !trainingOptionsOpen">更多参数</button><button class="start-training-button" type="button" :disabled="trainingBusy||generation.busy" @click="startTraining">{{ training.submitting ? '提交中…' : trainingBusy ? '训练中…' : '开始训练' }}</button></div>
              <div v-if="trainingOptionsOpen" class="model-training-options">
                <template v-if="datasetSampleMode === 'tabular'">
                  <section class="training-options-group training-options-rf">
                  <h3>随机森林 · 直接效率基准</h3>
                  <div class="training-options-grid"><label><span>树数量</span><SimulationNumber label="树数量" v-model="randomForestTrees" :min="1" :max="10000" integer /></label><label><span>最大深度（0=自动）</span><SimulationNumber label="最大深度（0=自动）" v-model="randomForestDepth" :min="0" :max="256" integer /></label><label><span>叶节点最小样本</span><SimulationNumber label="叶节点最小样本" v-model="randomForestLeaf" :min="1" :max="100" integer /></label><label><span>最大特征</span><select v-model="randomForestMaxFeatures"><option value="sqrt">sqrt</option><option value="log2">log2</option><option value="1.0">1.0</option></select></label></div>
                  </section>
                  <section class="training-options-group training-options-xgb">
                  <h3>XGBoost · 物理公式残差主模型</h3>
                  <div class="training-options-grid"><label><span>迭代轮数</span><SimulationNumber label="迭代轮数" v-model="xgboostRounds" :min="10" :max="10000" integer /></label><label><span>学习率</span><SimulationNumber label="学习率" v-model="xgboostLearningRate" :min="1e-06" :max="1" :decimals="8" :step="0.01" /></label><label><span>最大深度</span><SimulationNumber label="最大深度" v-model="xgboostDepth" :min="1" :max="32" integer /></label><label><span>样本采样率</span><SimulationNumber label="样本采样率" v-model="xgboostSubsample" :min="0.01" :max="1" :decimals="8" :step="0.01" /></label><label><span>特征采样率</span><SimulationNumber label="特征采样率" v-model="xgboostFeatureSample" :min="0.01" :max="1" :decimals="8" :step="0.01" /></label></div>
                  </section>
                </template>
                <template v-else>
                  <section class="training-options-group training-options-bilstm">
                  <h3>BiLSTM · 序列模型</h3>
                  <div class="training-options-grid"><label><span>最大轮数</span><SimulationNumber label="最大轮数" v-model="bilstmEpochs" :min="1" :max="5000" integer /></label><label><span>批大小</span><SimulationNumber label="批大小" v-model="bilstmBatchSize" :min="1" :max="1024" integer /></label></div>
                  </section>
                </template>
              </div>
            </section>
          </div>
        </template>
        <template v-else-if="moduleKey === 'model' && (activeKind === 'predict' || activeKind === 'predict_eval')">
          <div class="model-predict-layout">
            <section class="model-predict-section model-predict-setup">
              <h2>1. 设置</h2>
              <div class="model-predict-controls">
                <label><span>已训练模型</span><select :value="models.selectedId" aria-label="已训练模型" @change="selectModelFromInput"><option value="">请选择模型</option><option v-for="item in models.records" :key="item.model_id" :value="item.model_id">{{ models.displayName(item) }}</option></select></label>
                <label><span>目标</span><strong>{{ modelTargets }}</strong></label>
                <button type="button" :disabled="!predictionReady || models.predicting" @click="runModelPrediction">{{ models.predicting ? '预测中…' : '预测' }}</button>
              </div>
              <p v-if="selectedModel" class="model-predict-model-meta">{{ models.displayName(selectedModel) }} · {{ displayModelType(selectedModel.model_type) }} · 版本 / ID：{{ modelVersion }}</p>
              <p v-if="projectFeaturesLoading" class="model-predict-hint">正在读取当前系统的模型输入…</p>
              <p v-if="projectFeaturesError" class="dataset-details-error">{{ projectFeaturesError }}</p>
              <p v-if="modelUsability.reason" class="model-predict-hint">{{ modelUsability.reason }}</p>
            </section>
            <section class="model-predict-section model-predict-inputs">
              <h2>2. 当前镜头</h2>
              <div class="model-predict-table-wrap">
                <table class="model-predict-table">
                  <thead><tr><th>参数</th><th>当前值</th></tr></thead>
                  <tbody>
                    <tr v-for="row in predictionInputs" :key="row.key"><td>{{ row.label }}</td><td>{{ row.displayValue }}<span v-if="row.unit && row.value !== null"> {{ row.unit }}</span></td></tr>
                    <tr v-if="!predictionInputs.length"><td colspan="2">{{ models.loading ? '正在读取模型…' : '选择已训练模型后，用上面这组当前镜头参数做预测。' }}</td></tr>
                  </tbody>
                </table>
              </div>
            </section>
            <section class="model-predict-section model-predict-results">
              <h2>3. 结果</h2>
              <div class="model-predict-table-wrap">
                <table class="model-predict-table">
                  <thead><tr><th>量</th><th>值</th></tr></thead>
                  <tbody>
                    <tr v-for="([name, value], index) in predictionRows(models.prediction)" :key="`${name}-${index}`"><td>{{ name }}</td><td>{{ value }}</td></tr>
                    <tr v-if="!predictionRows(models.prediction).length"><td colspan="2">{{ models.predicting ? '正在预测…' : '尚无预测结果' }}</td></tr>
                  </tbody>
                </table>
              </div>
              <p v-if="models.predictionError" class="model-predict-error">{{ models.predictionError }}</p>
              <p v-else-if="models.prediction" class="model-predict-metrics">
                模型 {{ selectedModel?.name || selectedModel?.model_id }} · {{ models.prediction.in_training_domain === false ? '输入超出训练数据范围' : '输入位于训练数据范围' }}
                <span v-for="(warning, index) in models.prediction.warnings || []" :key="index">{{ warning }}</span>
              </p>
              <p v-else class="model-predict-metrics">选择已训练模型后，用上面这组当前镜头参数做预测。</p>
            </section>
          </div>
        </template>
        <template v-else-if="moduleKey === 'model' && (activeKind === 'train_result' || activeKind === 'train')">
          <TrainingResultView />
        </template>
        <template v-else-if="moduleKey === 'optimization' && activeKind === 'scan'">
          <ScanView />
        </template>
        <template v-else-if="moduleKey === 'optimization' && activeKind === 'opt_vars'">
          <OptimizationVariables />
        </template>
        <template v-else-if="moduleKey === 'optimization' && activeKind === 'opt_result'">
          <OptimizationResult />
        </template>
        <template v-else-if="moduleKey === 'explainability' && activeKind === 'global_contrib'">
          <ExplainabilityGlobal />
        </template>
        <template v-else-if="moduleKey === 'explainability' && activeKind === 'param_trend'">
          <ExplainabilityParameter />
        </template>
        <template v-else-if="moduleKey === 'explainability' && activeKind === 'current_system'">
          <ExplainabilityCurrent />
        </template>
        <section v-else class="document-surface">
          <h1 class="document-title">{{ activeItem?.title ?? definition.title }}</h1>
          <p class="document-subtitle">{{ activeItem?.subtitle }}</p>
          <div class="document-empty" aria-label="工作区"></div>
        </section>
      </main>
    </div>
  </section>
  <BaseToast v-if="simulation.error && moduleKey === 'simulation'" :message="simulation.error" tone="error" @close="simulation.error = ''" />
  <BaseToast v-if="moduleKey === 'model' && datasetNotice" :message="datasetNotice" :tone="datasetNoticeTone" @close="datasetNotice = ''" />
</template>
