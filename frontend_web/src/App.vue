<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, provide, readonly, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import type { BackendStatus } from "../../desktop/bridge-contract.js";
import { apiRequest } from "./api/http.js";
import { useJobsStore } from "./stores/jobs.js";
import { useSimulationStore } from "./stores/simulation.js";
import { useTeachingStore } from './stores/teaching.js';
import SimulationSettings from "./components/SimulationSettings.vue";
import BackendDiagnostics from './components/BackendDiagnostics.vue';
import { backendConnectionKey } from './domain/backend-connection.js';
import { PROJECT_FILE_LIMIT } from './domain/project-files.js';

interface HealthInfo {
  status: string;
}

const route = useRoute();
const router = useRouter();
const jobs = useJobsStore();
const simulation = useSimulationStore();
const teaching = useTeachingStore();
const projectTarget = ref<'simulation' | 'teaching'>('simulation');
const settingsOpen = ref(false);
const projectInput = ref<HTMLInputElement>();
const projectMenu = ref(false);
const backend = ref<BackendStatus>({ state: "checking", message: "正在检查 Python 后端…", owned: false });
provide(backendConnectionKey, readonly(backend));
let unsubscribe: (() => void) | undefined;
let jobsLoadRequested = false;
const reconnecting = ref(false);
const diagnosticsVisible = computed(() => reconnecting.value || ['error', 'stopped'].includes(backend.value.state));
let healthTimer: number | undefined;
let probing = false;

const modules = [
  { key: "home", label: "首页", to: "/" },
  { key: "teaching", label: "教学", to: "/teaching-three" },
  { key: "simulation", label: "仿真", to: "/workbench/simulation/lens_data" },
  { key: "model", label: "模型", to: "/workbench/model/dataset" },
  { key: "optimization", label: "优化", to: "/workbench/optimization/opt_vars" },
  { key: "explainability", label: "解释", to: "/workbench/explainability/global_contrib" },
];
const primaryIcons = {
  save: "/icons/save.svg?theme=light",
  compute: "/icons/play.svg?theme=light",
  settings: "/icons/settings.svg?theme=light",
};

const activeModule = computed(() => {
  if (route.name === "tasks") return "";
  if (route.name === "teaching-three") return "teaching";
  if (route.name === "workbench") return String(route.params.module ?? "");
  return "home";
});
watch(() => activeModule.value === 'teaching' ? teaching.dirty : simulation.dirty, dirty => { document.title = `激光耦合仿真系统及智能优化平台${dirty ? ' *' : ''}`; }, { immediate: true });
const documentStore = computed(() => activeModule.value === 'teaching' ? teaching : simulation);

onMounted(async () => {
  window.addEventListener('keydown', taskShortcut);
  const bridge = window.opticalDesktop;
  if (!bridge) {
    try {
      const response = await apiRequest<HealthInfo>("/api/v1/health");
      backend.value = response.data.status === "healthy"
        ? { state: "connected", message: "浏览器预览通过 Vite 代理连接到本机后端。", owned: false }
        : { state: "error", message: "FastAPI 健康检查未通过。", owned: false };
      loadInitialJobs();
    } catch (error) {
      backend.value = {
        state: "error",
        message: error instanceof Error ? error.message : String(error),
        owned: false,
      };
    }
    healthTimer = window.setInterval(() => void probeBrowserBackend(), 5000);
    return;
  }
  let statusEvents = 0;
  unsubscribe = bridge.onBackendStatus((status) => {
    statusEvents += 1;
    backend.value = status;
    if (status.state === 'error') jobsLoadRequested = false;
    loadInitialJobs();
  });
  try {
    const status = await bridge.getBackendStatus();
    if (statusEvents === 0) backend.value = status;
  } catch (error) {
    backend.value = {
      state: "error",
      message: error instanceof Error ? error.message : String(error),
      owned: false,
    };
  }
  loadInitialJobs();
});

onBeforeUnmount(() => { unsubscribe?.(); window.clearInterval(healthTimer); window.removeEventListener('keydown', taskShortcut); });

async function browserHealth(): Promise<BackendStatus> {
  const response = await apiRequest<HealthInfo>('/api/v1/health', { timeoutMs: 2000, retry: false });
  if (response.data.status !== 'healthy') throw new Error('后端健康检查未通过。');
  return { state: 'connected', message: '浏览器预览通过 Vite 代理连接到本机后端。', owned: false };
}
async function probeBrowserBackend(): Promise<void> {
  if (probing || reconnecting.value) return;
  probing = true;
  try { backend.value = await browserHealth(); loadInitialJobs(); }
  catch (cause) { jobsLoadRequested = false; backend.value = { state: 'error', message: cause instanceof Error ? cause.message : String(cause), owned: false }; }
  finally { probing = false; }
}
async function reconnectBackend(): Promise<void> {
  if (reconnecting.value) return;
  reconnecting.value = true; jobsLoadRequested = false;
  backend.value = { ...backend.value, state: 'checking', message: '正在重新连接后端…' };
  try { backend.value = window.opticalDesktop ? await window.opticalDesktop.startBackend() : await browserHealth(); loadInitialJobs(); }
  catch (cause) { backend.value = { state: 'error', message: cause instanceof Error ? cause.message : String(cause), owned: false }; }
  finally { reconnecting.value = false; }
}

function runPrimaryAction(action: "save" | "compute" | "settings"): void {
  if (action === "settings") settingsOpen.value = true;
  if (action === "save") void documentStore.value.save();
  if (action === "compute") {
    if (activeModule.value === 'teaching') { window.dispatchEvent(new Event('optical-teaching-compute')); return; }
    void router.push("/workbench/simulation/lens_data");
    void simulation.compute();
  }
}

function loadInitialJobs(): void {
  if (backend.value.state !== "connected" || jobsLoadRequested) return;
  jobsLoadRequested = true;
  void jobs.refresh({ limit: 40 });
}

function openTasks(): void {
  void router.push("/tasks");
}
function taskShortcut(event: KeyboardEvent): void {
  if (diagnosticsVisible.value) return;
  if(event.ctrlKey && event.shiftKey && event.key.toLowerCase()==='j') { event.preventDefault(); openTasks(); }
  if (!['simulation', 'teaching'].includes(activeModule.value) || !(event.ctrlKey || event.metaKey) || event.altKey) return;
  const key = event.key.toLowerCase();
  if (key === 'o') { event.preventDefault(); void openProject(); }
  else if (key === 's') { event.preventDefault(); void documentStore.value.save(); }
  else if (['z', 'y'].includes(key) && !(event.target instanceof Element && event.target.closest('input, textarea, [contenteditable="true"]'))) {
    event.preventDefault(); if (key === 'y' || event.shiftKey) documentStore.value.redo(); else documentStore.value.undo();
  }
}
async function openProject(): Promise<void> {
  projectMenu.value = false;
  const target = activeModule.value === 'teaching' ? 'teaching' : 'simulation'; projectTarget.value = target;
  if (!window.opticalDesktop) { projectInput.value?.click(); return; }
  try {
    const file = await window.opticalDesktop.openProjectFile();
    if (file && await (target === 'teaching' ? teaching.importScene(file.contents) : simulation.importProject(file.contents))) await router.push(target === 'teaching' ? '/teaching-three' : '/workbench/simulation/lens_data');
  } catch (cause) { (target === 'teaching' ? teaching : simulation).error = cause instanceof Error ? cause.message : String(cause); }
}
async function selectedProject(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement, file = input.files?.[0];
  const target = projectTarget.value;
  try {
    if (!file) return;
    if (file.size > PROJECT_FILE_LIMIT) throw new Error('项目文件超过 64 MiB。');
    if (await (target === 'teaching' ? teaching.importScene(await file.text()) : simulation.importProject(await file.text()))) await router.push(target === 'teaching' ? '/teaching-three' : '/workbench/simulation/lens_data');
  } catch (cause) { (target === 'teaching' ? teaching : simulation).error = cause instanceof Error ? cause.message : String(cause); }
  finally { input.value = ''; }
}
async function copyProject(): Promise<void> {
  projectMenu.value = false;
  if (activeModule.value !== 'teaching') { await simulation.copyProject(); return; }
  await teaching.copyProject();
}
</script>

<template>
  <div class="app-shell" :data-backend="backend.state" :title="backend.message">
    <nav class="primary-bar" aria-label="主导航" :inert="diagnosticsVisible">
      <div class="primary-modules">
        <RouterLink
          v-for="item in modules"
          :key="item.key"
          :to="item.to"
          class="primary-module"
          :class="{ active: activeModule === item.key }"
        >
          {{ item.label }}
        </RouterLink>
      </div>
      <div class="primary-actions" aria-label="常用操作">
        <div class="simulation-menu-host" @contextmenu.prevent="projectMenu = !projectMenu" @keydown.esc="projectMenu = false">
        <button class="primary-action" type="button" title="保存" aria-label="保存" aria-description="右键打开项目菜单；Ctrl+O 打开项目" @click="projectMenu = false; runPrimaryAction('save')">
          <img :src="primaryIcons.save" alt="" />
        </button>
        <div v-if="projectMenu" class="simulation-popup" role="menu" aria-label="项目操作">
          <button role="menuitem" :disabled="activeModule === 'teaching' ? teaching.busy : simulation.importing" @click="openProject">打开项目…　Ctrl+O</button>
          <button role="menuitem" @click="projectMenu = false; documentStore.save()">保存项目…　Ctrl+S</button>
          <button role="menuitem" @click="copyProject">复制项目参数</button>
          <hr />
          <button role="menuitem" :disabled="!documentStore.canUndo" @click="projectMenu = false; documentStore.undo()">{{ activeModule === 'teaching' ? '撤销场景编辑' : '撤销表面编辑' }}　Ctrl+Z</button>
          <button role="menuitem" :disabled="!documentStore.canRedo" @click="projectMenu = false; documentStore.redo()">{{ activeModule === 'teaching' ? '重做场景编辑' : '重做表面编辑' }}　Ctrl+Y</button>
        </div>
        </div>
        <div class="primary-compute-wrap" @contextmenu.prevent="openTasks">
          <button class="primary-action compute-action" type="button" :disabled="simulation.busy || backend.state !== 'connected'" :title="simulation.busy ? '正在计算' : '开始计算'" aria-label="开始计算" aria-description="右键或 Ctrl+Shift+J 打开任务中心" @click="runPrimaryAction('compute')">
            <img :src="primaryIcons.compute" alt="" />
          </button>
        </div>
        <button class="primary-action" type="button" title="设置" aria-label="设置" @click="runPrimaryAction('settings')">
          <img :src="primaryIcons.settings" alt="" />
        </button>
      </div>
      <span class="sr-only" aria-live="polite">Python 后端：{{ backend.state }}</span>
      <span class="sr-only" aria-live="polite">{{ activeModule === 'teaching' ? teaching.copyStatus : simulation.copyStatus }}</span>
    </nav>
    <main class="main-content" :inert="simulation.importing || backend.state !== 'connected'">
      <RouterView />
    </main>
    <SimulationSettings v-if="settingsOpen" @close="settingsOpen = false" />
    <BackendDiagnostics v-if="diagnosticsVisible" :backend="backend" :connecting="reconnecting" @reconnect="reconnectBackend" />
    <input ref="projectInput" type="file" accept=".json,application/json" hidden aria-label="打开光学项目文件" @change="selectedProject" />
    <button class="assistant-floating-button" type="button" title="打开 AI 助手；按住可拖动" aria-label="打开 AI 助手">
      AI
    </button>
  </div>
</template>
