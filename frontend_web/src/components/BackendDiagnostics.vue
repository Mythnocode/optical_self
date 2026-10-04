<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue';
import type { BackendStatus } from '../../../desktop/bridge-contract.js';
import { recentRequestDiagnostics } from '../api/diagnostics.js';

const props = defineProps<{ backend: BackendStatus; connecting: boolean }>();
const emit = defineEmits<{ reconnect: [] }>();
const panel = ref<HTMLDialogElement>();
const notice = ref('');
const desktop = !!window.opticalDesktop;
let closing = false;
onMounted(() => panel.value?.showModal());
onBeforeUnmount(() => { closing = true; panel.value?.close(); });
function keepOpen(): void {
  if (!closing && panel.value && !panel.value.open) panel.value.showModal();
}
function dialogKey(event: KeyboardEvent): void {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); return; }
  if (event.key !== 'Tab' || !panel.value) return;
  const buttons = Array.from(panel.value.querySelectorAll<HTMLButtonElement>('button')).filter(button => !button.disabled);
  const first = buttons[0], last = buttons[buttons.length - 1];
  if (!first || !last) return;
  if (!buttons.includes(document.activeElement as HTMLButtonElement) || (event.shiftKey ? document.activeElement === first : document.activeElement === last)) {
    event.preventDefault(); (event.shiftKey ? last : first).focus();
  }
}

async function copyDiagnostics(): Promise<void> {
  try {
    if (window.opticalDesktop) await window.opticalDesktop.copyDiagnostics();
    else await navigator.clipboard.writeText(JSON.stringify({ time: new Date().toISOString(),
      environment: 'browser-preview', route: location.hash, backend: props.backend,
      recent_requests: recentRequestDiagnostics() }, null, 2));
    notice.value = '诊断信息已复制。';
  } catch { notice.value = '无法复制诊断信息，请检查剪贴板权限。'; }
}
async function openLogs(): Promise<void> {
  try { await window.opticalDesktop?.openBackendLogs(); }
  catch (cause) { notice.value = cause instanceof Error ? cause.message : String(cause); }
}
</script>

<template>
    <dialog ref="panel" class="backend-diagnostics" role="alertdialog" aria-modal="true" aria-labelledby="backend-diagnostics-title" aria-describedby="backend-diagnostics-message" @keydown="dialogKey" @cancel.prevent="keepOpen" @close="keepOpen">
      <h2 id="backend-diagnostics-title">{{ connecting ? '正在重新连接后端' : '后端连接失败' }}</h2>
      <p id="backend-diagnostics-message">{{ backend.message }}</p>
      <div class="backend-diagnostics-actions">
        <button class="primary-button" :disabled="connecting" @click="emit('reconnect')">{{ connecting ? '正在连接…' : '重新连接后端' }}</button>
        <button :disabled="!desktop" :title="desktop ? undefined : '请在桌面应用中打开本机日志'" @click="openLogs">打开日志目录</button>
        <button @click="copyDiagnostics">复制诊断信息</button>
      </div>
      <p class="backend-diagnostics-notice" role="status">{{ notice }}</p>
    </dialog>
</template>

<style scoped>
.backend-diagnostics::backdrop { background: #0f172a33; }
.backend-diagnostics { width: min(600px, calc(100vw - 32px)); padding: 24px; border: 1px solid #d5dbe5; border-radius: 12px; background: #fff; box-shadow: 0 12px 40px #172b4d33; outline: none; }
.backend-diagnostics h2 { margin: 0 0 16px; font-size: 20px; }
.backend-diagnostics p { font-size: 16px; line-height: 1.6; overflow-wrap: anywhere; }
.backend-diagnostics-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 20px; }
.backend-diagnostics-actions button { min-height: 38px; padding: 6px 14px; border: 1px solid #9da7b7; border-radius: 6px; background: #fff; color: #172b4d; cursor: pointer; font: inherit; }
.backend-diagnostics-actions .primary-button { background: #155eef; border-color: #155eef; color: #fff; }
.backend-diagnostics-actions button:disabled { opacity: .55; cursor: default; }
.backend-diagnostics-actions button:focus-visible { outline: 2px solid #155eef; outline-offset: 2px; }
.backend-diagnostics-notice { min-height: 26px; margin-bottom: 0; color: #475467; }
</style>
