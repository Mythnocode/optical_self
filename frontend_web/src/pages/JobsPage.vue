<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import BaseToast from "../components/BaseToast.vue";
import type { JobStatus, JobState, JobResultSummary } from "../api/jobs.js";
import { useJobsStore } from "../stores/jobs.js";
import { useTrainingStore } from "../stores/training.js";

const PAGE_SIZE = 20;
const router = useRouter();
const store = useJobsStore();
const statusFilter = ref("");
const typeFilter = ref("");
const page = ref(0);
const selectedId = ref("");
const resultSummary = ref<JobResultSummary | null>(null);
const summaryLoading = ref(false);
const summaryError = ref("");
const actionError = ref("");
const busyAction = ref<Record<string, "cancel" | "retry">>({});
let refreshTimer: number | null = null;
let summaryRequestVersion = 0;
let stopBackendStatus: (() => void) | undefined;

const visibleJobs = computed(() => store.visibleJobIds
  .map((id) => store.jobs[id])
  .filter((job): job is JobStatus => Boolean(job)));
const selectedJob = computed(() => selectedId.value ? store.jobs[selectedId.value] : undefined);
const canGoNext = computed(() => visibleJobs.value.length === PAGE_SIZE);
const summaryMetrics = computed(() => {
  const summary = resultSummary.value;
  const metrics = isRecord(summary?.metrics) ? summary.metrics : {};
  return Object.entries(metrics).filter(([, value]) => isSummaryValue(value));
});
const summaryFields = computed(() => {
  const summary = resultSummary.value;
  if (!summary) return [];
  return Object.entries(summary).filter(([key, value]) =>
    !["metrics", "available_sections", "available_analysis_views", "job_timings_ms", "result_version", "bundle_version"].includes(key)
    && isSummaryValue(value));
});
const resultSections = computed(() => {
  const keys = ["available_sections", "available_analysis_views"];
  return [...new Set(keys.flatMap((key) => {
    const value = resultSummary.value?.[key];
    return Array.isArray(value) ? value.map(String) : [];
  }))];
});

watch([statusFilter, typeFilter], () => {
  page.value = 0;
  void loadPage();
});

watch(
  [selectedId, () => selectedJob.value?.status, () => selectedJob.value?.result_available],
  () => void loadSelectedSummary(),
);

onMounted(() => {
  void loadPage();
  refreshTimer = window.setInterval(() => {
    if (!store.error && !store.loading) void loadPage();
  }, 10_000);
  stopBackendStatus = window.opticalDesktop?.onBackendStatus((status) => {
    if (status.state === "connected") void loadPage();
  });
});

onBeforeUnmount(() => {
  if (refreshTimer !== null) window.clearInterval(refreshTimer);
  stopBackendStatus?.();
});

async function loadPage(): Promise<void> {
  const query = {
    limit: PAGE_SIZE,
    offset: page.value * PAGE_SIZE,
    ...(statusFilter.value ? { status: statusFilter.value } : {}),
    ...(typeFilter.value ? { jobType: typeFilter.value } : {}),
  };
  await store.refresh(query);
}

async function loadSelectedSummary(): Promise<void> {
  const requestVersion = ++summaryRequestVersion;
  resultSummary.value = null;
  summaryError.value = "";
  summaryLoading.value = false;
  let job = selectedJob.value;
  if (!job || job.status !== "completed" || !job.result_available) return;
  summaryLoading.value = true;
  try {
    job = await store.refreshOne(job.job_id) ?? job;
    if (requestVersion !== summaryRequestVersion || job.status !== "completed" || !job.result_available) return;
    resultSummary.value = await store.resultSummary(job.job_id);
  } catch (cause) {
    if (requestVersion === summaryRequestVersion) summaryError.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    if (requestVersion === summaryRequestVersion) summaryLoading.value = false;
  }
}

function openJob(job: JobStatus): void {
  selectedId.value = selectedId.value === job.job_id ? "" : job.job_id;
  actionError.value = "";
}

function canOpenTrainingResult(job: JobStatus): boolean {
  return Boolean(job.result_available) && ["training", "bilstm_structure_training"].includes(String(job.job_type));
}

async function openTrainingResult(job: JobStatus): Promise<void> {
  await useTrainingStore().openJob(job.job_id);
  await router.push({ name: "workbench", params: { module: "model", kind: "train_result" } });
}

async function cancelJob(job: JobStatus): Promise<void> {
  busyAction.value = { ...busyAction.value, [job.job_id]: "cancel" };
  actionError.value = "";
  try {
    await store.cancel(job.job_id);
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    delete busyAction.value[job.job_id];
  }
}

async function retryJob(job: JobStatus): Promise<void> {
  busyAction.value = { ...busyAction.value, [job.job_id]: "retry" };
  actionError.value = "";
  try {
    const newJobId = await store.retry(job.job_id);
    selectedId.value = newJobId;
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    delete busyAction.value[job.job_id];
  }
}

function selectPage(next: number): void {
  page.value = Math.max(0, next);
  selectedId.value = "";
  void loadPage();
}

function jobTitle(job: JobStatus): string {
  const type = jobTypeLabel(String(job.job_type ?? ""));
  return `${type}任务`;
}

function jobTypeLabel(value: string): string {
  const labels: Record<string, string> = {
    simulation: "正式仿真",
    teaching: "教学计算",
    dataset: "数据集生成",
    headless_dataset: "批量数据集",
    training: "模型训练",
    bilstm_structure_training: "BiLSTM 训练",
    optimization: "优化",
    scan: "参数扫描",
    tolerance: "公差分析",
    verification: "模型验证",
    explainability: "模型解释",
  };
  return labels[value] ?? (value || "后台");
}

function stateLabel(state: JobState): string {
  return ({ queued: "排队中", running: "运行中", completed: "已完成", failed: "失败", cancelled: "已取消" } as Record<string, string>)[state] ?? String(state);
}

function percent(job: JobStatus): number {
  if (job.status === "completed") return 100;
  const raw = Number(job.progress ?? 0);
  const value = raw > 1 ? raw : raw * 100;
  return Math.max(0, Math.min(job.status === "queued" || job.status === "running" ? 99 : 100, Math.round(value)));
}

function progressText(job: JobStatus): string {
  const description = stageLabel(job.stage) || stateLabel(job.status);
  if (job.status !== "queued" && job.status !== "running") return description;
  const count = Number(job.total_items ?? 0) > 1
    ? ` · ${Number(job.completed_items ?? 0)}/${Number(job.total_items)} 项`
    : "";
  return `${description} · ${percent(job)}%${count}`;
}

function stageLabel(stage: unknown): string {
  const value = String(stage ?? "");
  const stages: Record<string, string> = {
    completed: "任务已完成",
    failed: "任务失败",
    cancelled: "任务已取消",
    queued: "等待执行",
    running: "正在运行",
    submitting: "正在提交",
    "queue.waiting": "正在等待计算资源",
    "worker.starting": "正在启动计算",
    "worker.initializing": "正在初始化计算 Worker",
    "worker.ready": "计算 Worker 已就绪",
    "result.persisting": "正在保存结果",
    "result.materializing": "正在整理结果",
    "result.local_ready": "正式结果已生成，正在完成存档",
    "result.loading": "正在加载结果",
    "optical_engine.compile": "正在校验并编译光学输入",
    "optical_engine.compiled": "光学输入编译完成",
    "optical_engine.graph_ready": "计算任务图已建立",
    "optical_engine.trace.running": "正在进行光线追迹",
    "optical_engine.trace.completed": "光线追迹完成",
    "optical_engine.finalizing": "正在整理正式计算结果",
    "worker.exited": "计算 Worker 意外退出",
    "backend.restarted": "后端重启，任务已中断",
  };
  return stages[value] ?? value;
}

function formatDate(value: unknown): string {
  if (!value) return "—";
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date);
}

function displayError(error: JobStatus["error"]): string {
  if (typeof error === "string") return error;
  const messages: Record<string, string> = {
    BACKEND_RESTARTED: "后端在任务完成前发生了重启，本次任务没有产生正式结果。可以重新运行该任务。",
    JOB_RESULT_NOT_AVAILABLE: "该任务没有可用的正式结果。",
    QUEUE_TIMEOUT: "任务排队时间异常，长时间没有获得执行资源。",
    WORKER_STALLED: "任务长时间没有新的工作进度，Worker 可能失去响应。",
    WORKER_EXITED: "执行任务的 Worker 意外退出，本次任务未完成。",
    WORKER_START_FAILED: "Worker 启动失败，本次任务没有开始计算。",
    TIMEOUT: "任务运行超过允许时间，已停止。",
    RESULT_PERSIST_FAILED: "计算已结束，但结果保存失败。",
  };
  return (error?.code && messages[error.code]) || error?.message || "任务失败。请查看错误码并决定是否重试。";
}

function canCancel(job: JobStatus): boolean {
  return job.status === "queued" || job.status === "running";
}

function canRetry(job: JobStatus): boolean {
  return Boolean(job.retry_available) && (job.status === "failed" || job.status === "cancelled");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isSummaryValue(value: unknown): boolean {
  return value === null || ["string", "number", "boolean"].includes(typeof value);
}

function summaryLabel(value: string): string {
  const labels: Record<string, string> = {
    analysis: "分析类型", request_id: "请求编号", status: "结果状态", converged: "已收敛",
    wavelength_nm: "波长（nm）", coupling_efficiency: "耦合效率", coupling_loss_db: "耦合损耗（dB）",
    rms_spot_radius_um: "RMS 光斑半径（μm）", strehl_estimate_marechal: "Strehl 估计值",
  };
  return labels[value] ?? value.replaceAll("_", " ");
}

function summaryValue(value: unknown): string {
  if (value === null) return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") return Number.isFinite(value) ? new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 6 }).format(value) : String(value);
  return String(value);
}
</script>

<template>
  <section class="jobs-page">
    <header class="jobs-heading">
      <div>
        <span class="jobs-eyebrow">实验与数据</span>
        <h1>任务中心</h1>
        <p>查看仿真、扫描、优化、训练与解释任务的实时状态和正式结果。</p>
      </div>
      <div class="jobs-heading-actions">
        <button class="button" type="button" @click="void router.push('/')">返回首页</button>
        <button class="button button-primary" type="button" :disabled="store.loading" @click="loadPage">{{ store.loading ? "刷新中…" : "刷新任务" }}</button>
      </div>
    </header>

    <section class="jobs-overview" aria-label="任务统计">
      <div><span>已载入任务</span><strong>{{ store.totalCount }}</strong></div>
      <div><span>正在运行</span><strong>{{ store.activeCount }}</strong></div>
      <div><span>本页结果可用</span><strong>{{ visibleJobs.filter((job) => job.result_available).length }}</strong></div>
    </section>

    <section class="jobs-list-panel" aria-label="后台任务列表">
      <div class="jobs-toolbar">
        <div class="jobs-filters">
          <label>状态
            <select v-model="statusFilter" aria-label="按任务状态筛选">
              <option value="">全部状态</option><option value="queued">排队中</option><option value="running">运行中</option>
              <option value="completed">已完成</option><option value="failed">失败</option><option value="cancelled">已取消</option>
            </select>
          </label>
          <label>类型
            <select v-model="typeFilter" aria-label="按任务类型筛选">
              <option value="">全部类型</option>
              <option value="simulation">正式仿真</option><option value="dataset">数据集生成</option>
              <option value="headless_dataset">批量数据集</option><option value="training">模型训练</option>
              <option value="bilstm_structure_training">BiLSTM 训练</option><option value="optimization">优化</option>
              <option value="scan">参数扫描</option><option value="tolerance">公差分析</option>
              <option value="verification">模型验证</option>
              <option value="explainability">模型解释</option>
            </select>
          </label>
        </div>
        <span class="jobs-page-count">第 {{ page + 1 }} 页 · {{ visibleJobs.length }} 项</span>
      </div>

      <div v-if="store.error" class="jobs-error" role="alert">{{ store.error }}</div>
      <div v-if="actionError" class="jobs-error" role="alert">{{ actionError }}</div>

      <div class="jobs-table-scroll">
        <table class="jobs-table">
          <thead><tr><th>任务</th><th>状态与进度</th><th>创建时间</th><th>结果</th><th>操作</th></tr></thead>
          <tbody>
            <template v-for="job in visibleJobs" :key="job.job_id">
              <tr class="jobs-row" :class="{ selected: selectedId === job.job_id }" @click="openJob(job)">
                <td>
                  <strong>{{ jobTitle(job) }}</strong>
                  <span class="jobs-id" :title="job.job_id">{{ job.job_id }}</span>
                  <span v-if="job.retry_of" class="jobs-retry-origin">由失败任务重试</span>
                </td>
                <td>
                  <span class="job-status" :class="`job-status-${job.status}`">{{ stateLabel(job.status) }}</span>
                  <div class="job-progress-track"><span :class="`progress-${job.status}`" :style="{ width: `${percent(job)}%` }"></span></div>
                  <small class="job-stage">{{ progressText(job) }}</small>
                </td>
                <td>{{ formatDate(job.created_at) }}</td>
                <td>
                  <span v-if="job.result_available" class="job-result-ready">正式结果可用</span>
                  <span v-else-if="job.partial_result_available" class="job-result-partial">只有中间结果</span>
                  <span v-else class="job-result-none">暂无正式结果</span>
                  <small v-if="job.status === 'failed'" class="job-error-code">{{ typeof job.error === 'object' && job.error ? job.error.code : '' }}</small>
                </td>
                <td class="jobs-actions" @click.stop>
                  <button v-if="canCancel(job)" class="button button-danger button-compact" type="button" :disabled="Boolean(busyAction[job.job_id])" @click="cancelJob(job)">{{ busyAction[job.job_id] === 'cancel' ? '取消中…' : '取消' }}</button>
                  <button v-else-if="canRetry(job)" class="button button-compact" type="button" :disabled="Boolean(busyAction[job.job_id])" @click="retryJob(job)">{{ busyAction[job.job_id] === 'retry' ? '提交中…' : '重新运行' }}</button>
                  <button v-if="job.result_available" class="button button-compact" type="button" @click="openJob(job)">查看摘要</button>
                  <button v-if="canOpenTrainingResult(job)" class="button button-compact" type="button" @click="openTrainingResult(job)">查看训练图表</button>
                  <span v-if="!canCancel(job) && !canRetry(job) && !job.result_available" class="jobs-no-action">—</span>
                </td>
              </tr>
              <tr v-if="selectedId === job.job_id" class="jobs-detail-row">
                <td colspan="5">
                  <section class="jobs-result-detail" :aria-label="`${jobTitle(job)}详情`">
                    <div class="jobs-detail-heading"><h2>{{ job.status === 'completed' ? '结果摘要' : '任务详情' }}</h2><span>完整任务编号：{{ job.job_id }}</span></div>
                    <p v-if="job.status === 'failed' || job.status === 'cancelled'" class="jobs-detail-error">{{ displayError(job.error) }}</p>
                    <p v-if="summaryLoading" class="jobs-detail-empty">正在读取结果摘要…</p>
                    <p v-else-if="summaryError" class="jobs-detail-error">{{ summaryError }}</p>
                    <template v-else-if="resultSummary">
                      <div v-if="summaryMetrics.length" class="jobs-metric-grid">
                        <div v-for="[key, value] in summaryMetrics" :key="key"><span>{{ summaryLabel(key) }}</span><strong>{{ summaryValue(value) }}</strong></div>
                      </div>
                      <dl v-if="summaryFields.length" class="jobs-summary-fields">
                        <div v-for="[key, value] in summaryFields" :key="key"><dt>{{ summaryLabel(key) }}</dt><dd>{{ summaryValue(value) }}</dd></div>
                      </dl>
                      <div v-if="resultSections.length" class="jobs-analysis-sections"><span>可用分析结果</span><i v-for="name in resultSections" :key="name">{{ name }}</i></div>
                      <p v-if="!summaryMetrics.length && !summaryFields.length && !resultSections.length" class="jobs-detail-empty">该任务没有返回可展示的摘要字段。</p>
                    </template>
                    <p v-else-if="job.status === 'completed' && !job.result_available" class="jobs-detail-empty">任务已完成，但没有可用的正式结果。</p>
                    <p v-else class="jobs-detail-empty">{{ stageLabel(job.stage) || '任务正在排队或运行。' }}</p>
                    <div class="jobs-detail-meta"><span>错误码：{{ typeof job.error === 'object' && job.error ? job.error.code || '—' : '—' }}</span><span>阶段：{{ stageLabel(job.stage) || '—' }}</span><span>结果版本：{{ job.result_version ?? '—' }}</span></div>
                  </section>
                </td>
              </tr>
            </template>
            <tr v-if="!visibleJobs.length"><td colspan="5" class="jobs-empty">{{ store.loading ? '正在读取任务…' : '当前筛选条件下没有任务' }}</td></tr>
          </tbody>
        </table>
      </div>

      <footer class="jobs-pagination">
        <button class="button" type="button" :disabled="page === 0 || store.loading" @click="selectPage(page - 1)">上一页</button>
        <span>第 {{ page + 1 }} 页</span>
        <button class="button" type="button" :disabled="!canGoNext || store.loading" @click="selectPage(page + 1)">下一页</button>
      </footer>
    </section>
  </section>
  <BaseToast v-if="actionError" :message="actionError" tone="error" @close="actionError = ''" />
</template>
