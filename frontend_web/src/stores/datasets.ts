import { defineStore } from "pinia";
import { ref } from "vue";
import {
  getDataset,
  getDatasetManifest,
  importTabularDataset,
  listDatasets,
  type DatasetDetails,
  type DatasetManifest,
  type DatasetSummary,
} from "../api/datasets.js";

const BUILTIN_DATASET_ID = "dataset-880bdde6c292";
const BUILTIN_DATASET_NAME = "内置演示·780 nm 四透镜八变量";

export const useDatasetsStore = defineStore("datasets", () => {
  const items = ref<DatasetSummary[]>([{
    dataset_id: BUILTIN_DATASET_ID,
    dataset_name: BUILTIN_DATASET_NAME,
    dataset_type: "headless_lens4_coupling",
    target_column: "coupling_efficiency",
    sample_count: 90,
    status: "ready",
    created_at: "",
  }]);
  const selectedId = ref("");
  const details = ref<DatasetDetails | null>(null);
  const manifest = ref<DatasetManifest | null>(null);
  const loading = ref(false);
  const detailLoading = ref(false);
  const manifestLoading = ref(false);
  const importing = ref(false);
  const error = ref("");
  const detailError = ref("");
  const manifestError = ref("");
  const loadedFromBackend = ref(false);
  let detailRequestVersion = 0;
  let manifestRequestVersion = 0;
  let refreshPromise: Promise<void> | null = null;

  function refresh(): Promise<void> {
    if (refreshPromise) return refreshPromise;
    refreshPromise = refreshItems().finally(() => { refreshPromise = null; });
    return refreshPromise;
  }

  async function refreshItems(): Promise<void> {
    loading.value = true;
    error.value = "";
    try {
      const response = await listDatasets();
      items.value = response.items.map((item) => ({
        ...item,
        dataset_name: item.dataset_id === BUILTIN_DATASET_ID ? BUILTIN_DATASET_NAME : item.dataset_name || item.dataset_id,
      }));
      loadedFromBackend.value = true;
      if (!items.value.some((item) => item.dataset_id === selectedId.value)) {
        select("");
      } else if (selectedId.value) {
        void loadDetails(selectedId.value).catch(() => undefined);
        void loadManifest(selectedId.value).catch(() => undefined);
      }
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause);
    } finally {
      loading.value = false;
    }
  }

  async function registerCompleted(datasetId: string): Promise<void> {
    await refresh();
    const completed = await getDataset(datasetId);
    items.value = [{ ...completed }, ...items.value.filter(item => item.dataset_id !== datasetId)];
    loadedFromBackend.value = true;
  }

  async function importFile(selection: { path: string; name: string }): Promise<void> {
    importing.value = true;
    error.value = "";
    try {
      const imported = await importTabularDataset({
        source_path: selection.path,
        dataset_name: selection.name.replace(/\.[^.]+$/, ""),
        target_name: "coupling_efficiency",
        random_seed: 42,
      });
      const summary: DatasetSummary = {
        ...imported,
        dataset_name: imported.dataset_name || selection.name,
      };
      items.value = [summary, ...items.value.filter((item) => item.dataset_id !== summary.dataset_id)];
      selectedId.value = summary.dataset_id;
      loadedFromBackend.value = true;
      details.value = { ...imported, dataset_name: summary.dataset_name };
      void loadManifest(summary.dataset_id).catch(() => undefined);
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause);
      throw cause;
    } finally {
      importing.value = false;
    }
  }

  function select(datasetId: string): void {
    const nextId = items.value.some((item) => item.dataset_id === datasetId) ? datasetId : "";
    selectedId.value = nextId;
    detailRequestVersion += 1;
    manifestRequestVersion += 1;
    detailError.value = "";
    manifestError.value = "";
    if (!nextId) {
      details.value = null;
      manifest.value = null;
      detailLoading.value = false;
      manifestLoading.value = false;
      return;
    }
    details.value = null;
    manifest.value = null;
    void loadDetails(nextId).catch(() => undefined);
    void loadManifest(nextId).catch(() => undefined);
  }

  async function loadDetails(datasetId = selectedId.value): Promise<DatasetDetails> {
    if (!datasetId) throw new Error("请先选择数据集。");
    const version = ++detailRequestVersion;
    detailLoading.value = true;
    detailError.value = "";
    try {
      const response = await getDataset(datasetId);
      if (version === detailRequestVersion && selectedId.value === datasetId) {
        details.value = response;
      }
      return response;
    } catch (cause) {
      if (version === detailRequestVersion) {
        detailError.value = cause instanceof Error ? cause.message : String(cause);
      }
      throw cause;
    } finally {
      if (version === detailRequestVersion) detailLoading.value = false;
    }
  }

  async function loadManifest(datasetId = selectedId.value): Promise<DatasetManifest> {
    if (!datasetId) throw new Error("请先选择数据集。");
    const version = ++manifestRequestVersion;
    manifestLoading.value = true;
    manifestError.value = "";
    try {
      const response = await getDatasetManifest(datasetId);
      if (version === manifestRequestVersion && selectedId.value === datasetId) {
        manifest.value = response;
      }
      return response;
    } catch (cause) {
      if (version === manifestRequestVersion) {
        manifestError.value = cause instanceof Error ? cause.message : String(cause);
      }
      throw cause;
    } finally {
      if (version === manifestRequestVersion) manifestLoading.value = false;
    }
  }

  return {
    items, selectedId, details, manifest, loading, detailLoading, manifestLoading, importing,
    error, detailError, manifestError, loadedFromBackend, refresh, registerCompleted, importFile, select, loadDetails, loadManifest,
  };
});
