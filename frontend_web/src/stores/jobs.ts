import { defineStore } from "pinia";
import { computed, ref } from "vue";
import {
  cancelJob as cancelJobRequest,
  getJobResultSummary,
  getJobStatus,
  JobSocket,
  listJobs,
  retryJob as retryJobRequest,
  submitSimulation,
  type JobEvent,
  type JobListQuery,
  type JobResultSummary,
  type JobStatus,
  type JobTerminalState,
} from "../api/jobs.js";

const TERMINAL_STATES = new Set<JobTerminalState>(["completed", "failed", "cancelled"]);

export const useJobsStore = defineStore("jobs", () => {
  const jobs = ref<Record<string, JobStatus>>({});
  const visibleJobIds = ref<string[]>([]);
  const loading = ref(false);
  const error = ref("");
  const activeCount = computed(() => Object.values(jobs.value).filter((job) => !TERMINAL_STATES.has(job.status as JobTerminalState)).length);
  const totalCount = computed(() => Object.keys(jobs.value).length);
  let socket: JobSocket | null = null;
  let pollTimer: number | null = null;
  let refreshVersion = 0;

  async function refresh(options: JobListQuery = {}): Promise<void> {
    const version = ++refreshVersion;
    loading.value = true;
    error.value = "";
    try {
      const items = await listJobs({ limit: 40, ...options });
      if (version !== refreshVersion) return;
      visibleJobIds.value = items.map((item) => item.job_id);
      for (const item of items) {
        merge(item);
        if (!TERMINAL_STATES.has(item.status as JobTerminalState)) {
          track(item.job_id);
        }
      }
    } catch (cause) {
      if (version === refreshVersion) {
        error.value = cause instanceof Error ? cause.message : String(cause);
      }
    } finally {
      if (version === refreshVersion) loading.value = false;
    }
  }

  async function submit(payload: unknown): Promise<string> {
    const jobId = await submitSimulation(payload);
    merge({ job_id: jobId, status: "queued", progress: 0, stage: "queued" });
    track(jobId);
    return jobId;
  }

  async function track(jobId: string): Promise<void> {
    if (!jobId) {
      return;
    }
    if (!socket) {
      socket = new JobSocket(onEvent);
    }
    socket.subscribe(jobId);
    startPolling();
    await refreshOne(jobId);
  }

  async function trackSubmittedJob(jobId: string, jobType: string): Promise<void> {
    if (!jobId) throw new Error("任务编号为空。");
    merge({ job_id: jobId, job_type: jobType, status: "queued", progress: 0, stage: "queued" });
    visibleJobIds.value = [jobId, ...visibleJobIds.value.filter((id) => id !== jobId)];
    await track(jobId);
  }

  async function cancel(jobId: string): Promise<void> {
    await cancelJobRequest(jobId);
    await refreshOne(jobId);
  }

  async function retry(jobId: string): Promise<string> {
    const retried = await retryJobRequest(jobId);
    merge(retried);
    visibleJobIds.value = [retried.job_id, ...visibleJobIds.value.filter((id) => id !== retried.job_id)];
    track(retried.job_id);
    return retried.job_id;
  }

  async function resultSummary(jobId: string): Promise<JobResultSummary> {
    return getJobResultSummary(jobId);
  }

  function stopTracking(jobId: string): void {
    socket?.unsubscribe(jobId);
    if (Object.values(jobs.value).every((job) => TERMINAL_STATES.has(job.status as JobTerminalState))) {
      stopPolling();
    }
  }

  function dispose(): void {
    socket?.dispose();
    socket = null;
    stopPolling();
  }

  async function refreshOne(jobId: string): Promise<JobStatus | null> {
    try {
      const item = await getJobStatus(jobId);
      merge(item);
      return item;
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause);
      return null;
    }
  }

  function onEvent(event: JobEvent): void {
    if (!event.job_id) {
      return;
    }
    const current = jobs.value[event.job_id];
    if (current && TERMINAL_STATES.has(current.status as JobTerminalState)) {
      return;
    }
    if (current && (event.result_version ?? 0) < (current.result_version ?? 0)) {
      return;
    }
    merge({
      ...(current ?? { job_id: event.job_id, status: event.type }),
      status: isTerminal(event.type) ? event.type : (event.status ?? event.type),
      progress: event.progress ?? current?.progress,
      stage: event.stage ?? current?.stage,
      result_version: event.result_version ?? current?.result_version,
      metrics: event.metrics ?? current?.metrics,
      error: event.error ?? current?.error,
    });
  }

  function merge(incoming: JobStatus): void {
    if (!incoming.job_id) {
      return;
    }
    const current = jobs.value[incoming.job_id];
    if (current && TERMINAL_STATES.has(current.status as JobTerminalState) && !TERMINAL_STATES.has(incoming.status as JobTerminalState)) {
      return;
    }
    jobs.value[incoming.job_id] = { ...current, ...incoming };
    if (TERMINAL_STATES.has(incoming.status as JobTerminalState)) {
      socket?.unsubscribe(incoming.job_id);
      if (activeCount.value === 0) {
        stopPolling();
      }
    }
  }

  function startPolling(): void {
    if (pollTimer !== null) {
      return;
    }
    pollTimer = window.setInterval(() => {
      for (const job of Object.values(jobs.value)) {
        if (!TERMINAL_STATES.has(job.status as JobTerminalState)) {
          void refreshOne(job.job_id);
        }
      }
    }, 2_500);
  }

  function stopPolling(): void {
    if (pollTimer !== null) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  return {
    jobs, visibleJobIds, loading, error, activeCount, totalCount,
    refresh, refreshOne, submit, track, trackSubmittedJob, cancel, retry, resultSummary, stopTracking, dispose,
  };
});

function isTerminal(value: string): value is JobTerminalState {
  return TERMINAL_STATES.has(value as JobTerminalState);
}
