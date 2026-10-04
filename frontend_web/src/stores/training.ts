import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";
import { getJobResult } from "../api/jobs.js";
import {
  submitBiLSTMTraining,
  submitJointTraining,
  type BiLSTMTrainingPayload,
  type JointTrainingPayload,
} from "../api/training.js";
import { useJobsStore } from "./jobs.js";
import { useModelsStore } from "./models.js";
import { getStructureModelDetails, type ModelRecord } from "../api/models.js";

export const useTrainingStore = defineStore("training", () => {
  const jobs = useJobsStore();
  const models = useModelsStore();
  const activeJobId = ref(localStorage.getItem("optical.training.job") ?? "");
  const submitting = ref(false);
  const jobResultLoading = ref(false);
  const modelLoading = ref(false);
  const submitError = ref("");
  const jobResultError = ref("");
  const modelError = ref("");
  const jobResult = ref<Record<string, unknown> | null>(null);
  const modelResult = ref<Record<string, unknown> | null>(null);
  const viewedModelId = ref(localStorage.getItem("optical.training.model") ?? "");
  let modelRequestVersion = 0;
  const result = computed(() => viewedModelId.value ? modelResult.value : jobResult.value);
  const resultLoading = computed(() => viewedModelId.value ? modelLoading.value : jobResultLoading.value);
  const resultError = computed(() => viewedModelId.value ? modelError.value : jobResultError.value);
  const job = computed(() => activeJobId.value ? jobs.jobs[activeJobId.value] ?? null : null);
  const resultJob = computed(() => viewedModelId.value
    ? (modelResult.value ? { job_id: viewedModelId.value, status: "completed" as const, progress: 1 } : null)
    : job.value);
  watch(activeJobId, (id) => localStorage.setItem("optical.training.job", id));
  watch(viewedModelId, (id) => localStorage.setItem("optical.training.model", id));
  watch([viewedModelId, () => models.records], ([id]) => {
    const saved = models.records.find((item) => item.model_id === id);
    if (saved) void readModel(saved);
    else if (id && models.loaded && !models.loading && !models.error) {
      modelRequestVersion++;
      modelResult.value = null;
      modelLoading.value = false;
      modelError.value = "所选模型不在当前后端的模型库中，请选择其他模型。";
    }
  }, { immediate: true });
  watch([activeJobId, () => job.value?.status], ([id, status]) => {
    if (id && status === "completed") void loadResult(id);
  }, { immediate: true });
  if (activeJobId.value) void jobs.track(activeJobId.value);

  async function submitJoint(payload: JointTrainingPayload): Promise<void> {
    await submit(() => submitJointTraining(payload), "training");
  }

  async function submitBiLSTM(payload: BiLSTMTrainingPayload): Promise<void> {
    await submit(() => submitBiLSTMTraining(payload), "bilstm_structure_training");
  }

  async function openJob(jobId: string): Promise<void> {
    if (!jobId || submitting.value) return;
    submitError.value = "";
    clearModelView();
    jobResultError.value = "";
    if (activeJobId.value !== jobId) {
      jobResult.value = null;
      jobResultLoading.value = false;
      activeJobId.value = jobId;
    }
    await jobs.track(jobId);
    if (job.value?.status === "completed" && !jobResult.value && !jobResultLoading.value) await loadResult(jobId);
  }

  function viewModel(modelId: string): void {
    submitError.value = "";
    if (viewedModelId.value === modelId) {
      const saved = models.records.find((item) => item.model_id === modelId);
      if (saved) void readModel(saved);
    } else viewedModelId.value = modelId;
  }

  async function readModel(saved: ModelRecord): Promise<void> {
    const version = ++modelRequestVersion;
    modelResult.value = null;
    modelError.value = "";
    modelLoading.value = true;
    try {
      const body = models.isSequenceModel(saved) ? await getStructureModelDetails(saved.model_id) : { ...saved };
      if (version === modelRequestVersion && viewedModelId.value === saved.model_id) modelResult.value = body;
    } catch (cause) {
      if (version === modelRequestVersion) modelError.value = cause instanceof Error ? cause.message : String(cause);
    } finally {
      if (version === modelRequestVersion) modelLoading.value = false;
    }
  }

  function clearModelView(): void {
    modelRequestVersion++;
    viewedModelId.value = "";
    modelResult.value = null;
    modelError.value = "";
    modelLoading.value = false;
  }

  async function submit(request: () => Promise<string>, jobType: string): Promise<void> {
    submitting.value = true;
    submitError.value = "";
    jobResultError.value = "";
    jobResult.value = null;
    try {
      const jobId = await request();
      activeJobId.value = jobId;
      clearModelView();
      jobResult.value = null;
      jobResultLoading.value = false;
      await jobs.trackSubmittedJob(jobId, jobType);
    } catch (cause) {
      submitError.value = cause instanceof Error ? cause.message : String(cause);
      throw cause;
    } finally {
      submitting.value = false;
    }
  }

  async function loadResult(jobId = activeJobId.value): Promise<void> {
    if (!jobId) return;
    jobResultLoading.value = true;
    jobResultError.value = "";
    try {
      const raw = await getJobResult<unknown>(jobId);
      const body = asRecord(raw);
      const nested = asRecord(body.result);
      if (jobId !== activeJobId.value) return;
      jobResult.value = Object.keys(nested).length ? nested : body;
      await useModelsStore().refresh();
    } catch (cause) {
      if (jobId === activeJobId.value) jobResultError.value = cause instanceof Error ? cause.message : String(cause);
    } finally {
      if (jobId === activeJobId.value) jobResultLoading.value = false;
    }
  }

  function clearResult(): void {
    jobResult.value = null;
    jobResultError.value = "";
    clearModelView();
  }

  return {
    activeJobId, job, resultJob, viewedModelId, submitting, resultLoading, submitError, resultError, result,
    submitJoint, submitBiLSTM, openJob, viewModel, loadResult, clearResult,
  };
});

function asRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
