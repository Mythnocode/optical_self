import { defineStore } from "pinia";
import { computed, ref } from "vue";
import {
  listModels,
  listStructureModels,
  predictModel,
  predictStructureModel,
  type ModelRecord,
  type PredictionResult,
} from "../api/models.js";

const CURRENT_MODEL_STORAGE_KEY = "optical-self.current-model-id";

function modelId(record: ModelRecord): string {
  return String(record.model_id || "");
}

export const useModelsStore = defineStore("models", () => {
  const records = ref<ModelRecord[]>([]);
  const selectedId = ref("");
  const currentModelId = ref(localStorage.getItem(CURRENT_MODEL_STORAGE_KEY) || "");
  const loading = ref(false);
  const loaded = ref(false);
  const error = ref("");
  const predicting = ref(false);
  const predictionError = ref("");
  const prediction = ref<PredictionResult | null>(null);
  let predictionVersion = 0;
  const selected = computed(() => records.value.find((item) => modelId(item) === selectedId.value) ?? null);
  const current = computed(() => records.value.find((item) => modelId(item) === currentModelId.value) ?? null);

  async function refresh(): Promise<void> {
    if (loading.value) return;
    loading.value = true;
    error.value = "";
    try {
      const results = await Promise.allSettled([listModels(), listStructureModels()]);
      const available = results.flatMap((result, index) => result.status === "fulfilled"
        ? result.value.map((record) => ({
            ...record,
            model_type: record.model_type || (index === 1 ? "bilstm_structure_sequence" : ""),
          }))
        : []);
      const failures = results.flatMap((result) => result.status === "rejected"
        ? [result.reason instanceof Error ? result.reason.message : String(result.reason)]
        : []);
      records.value = available.filter((record) => modelId(record)).sort((a, b) => {
        const time = (record: ModelRecord) => { const parsed = Date.parse(record.created_at ?? ""); return Number.isFinite(parsed) ? parsed : Number.MAX_SAFE_INTEGER; };
        return time(a) - time(b) || a.model_id.localeCompare(b.model_id);
      });
      loaded.value = true;
      if (!failures.length && currentModelId.value && !records.value.some((record) => modelId(record) === currentModelId.value)) {
        currentModelId.value = "";
        localStorage.removeItem(CURRENT_MODEL_STORAGE_KEY);
      }
      if (!records.value.some((record) => modelId(record) === selectedId.value)) {
        selectedId.value = currentModelId.value;
      }
      if (failures.length && !available.length) error.value = failures[0];
      else if (failures.length) error.value = `部分模型列表暂不可用：${failures[0]}`;
    } finally {
      loading.value = false;
    }
  }

  function select(modelIdValue: string): void {
    selectedId.value = records.value.some((item) => modelId(item) === modelIdValue) ? modelIdValue : "";
    clearPrediction();
  }

  function clearPrediction(): void { predictionVersion++; prediction.value = null; predictionError.value = ""; predicting.value = false; }

  function adopt(modelIdValue: string): void {
    const exists = records.value.some((item) => modelId(item) === modelIdValue);
    currentModelId.value = exists ? modelIdValue : "";
    if (currentModelId.value) localStorage.setItem(CURRENT_MODEL_STORAGE_KEY, currentModelId.value);
    else localStorage.removeItem(CURRENT_MODEL_STORAGE_KEY);
    select(currentModelId.value);
  }

  async function runPrediction(features: Record<string, number>): Promise<void> {
    const record = selected.value;
    if (!record) throw new Error("请先选择模型。");
    const version = ++predictionVersion;
    predicting.value = true;
    predictionError.value = "";
    prediction.value = null;
    try {
      const response = await predictModel(modelId(record), features);
      if (version === predictionVersion) prediction.value = response;
    } catch (cause) {
      if (version === predictionVersion) predictionError.value = cause instanceof Error ? cause.message : String(cause);
      throw cause;
    } finally {
      if (version === predictionVersion) predicting.value = false;
    }
  }

  async function runSequencePrediction(payload: { element_types: string[]; numeric_values: number[][] }): Promise<void> {
    const record = selected.value;
    if (!record) throw new Error("请先选择模型。");
    const version = ++predictionVersion;
    predicting.value = true;
    predictionError.value = "";
    prediction.value = null;
    try {
      const response = await predictStructureModel(modelId(record), payload);
      if (version === predictionVersion) prediction.value = response;
    } catch (cause) {
      if (version === predictionVersion) predictionError.value = cause instanceof Error ? cause.message : String(cause);
      throw cause;
    } finally {
      if (version === predictionVersion) predicting.value = false;
    }
  }

  function isSequenceModel(record: ModelRecord): boolean {
    return [record.model_type, record.name].some((value) => String(value || "").toLowerCase().includes("bilstm"))
      || String(record.model_type || "") === "bilstm_structure_sequence";
  }

  function displayName(record: ModelRecord): string {
    if (record.name && record.name !== record.model_id) return record.name;
    const type = record.model_type ?? "";
    const label = ({ random_forest: "随机森林", xgboost_physics_residual: "XGBoost物理残差", bilstm_structure_sequence: "BiLSTM" } as Record<string, string>)[type];
    if (!label) return record.model_id;
    const family = records.value.filter((item) => item.model_type === type);
    const reserved = new Set(family.flatMap((item) => {
      const name = item.name ?? "";
      const number = name.startsWith(label) ? Number(name.slice(label.length)) : NaN;
      return Number.isInteger(number) && number > 0 ? [number] : [];
    }));
    let number = 0;
    for (const item of family.filter((item) => !item.name || item.name === item.model_id)) {
      do { number++; } while (reserved.has(number));
      if (item.model_id === record.model_id) break;
    }
    return `${label}${number}`;
  }

  return {
    records, selectedId, currentModelId, selected, current, loading, loaded, error,
    predicting, predictionError, prediction, refresh, select, adopt, runPrediction,
    runSequencePrediction, isSequenceModel, displayName, clearPrediction,
  };
});
