<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import BaseModal from "../components/BaseModal.vue";
import BaseToast from "../components/BaseToast.vue";
import { TeachingRenderer } from "../teaching/three/TeachingRenderer.js";
import { useTeachingStore } from "../stores/teaching.js";
import TeachingInspector from '../components/TeachingInspector.vue';
import TeachingBench2D from '../components/TeachingBench2D.vue';
import TeachingEquipment from '../components/TeachingEquipment.vue';
import TeachingAnalysis from '../components/TeachingAnalysis.vue';
import { useTeachingAnalysisStore } from '../stores/teaching-analysis.js';
import { useTeachingSyncStore } from '../stores/teaching-sync.js';
import { COMPONENT_CATALOG, type ComponentKind } from '../teaching/domain/component-catalog.js';

const store = useTeachingStore();
const analysis = useTeachingAnalysisStore();
const sync = useTeachingSyncStore();
const route = useRoute();
const canvasHost = ref<HTMLElement | null>(null);
const bench2d = ref<InstanceType<typeof TeachingBench2D>>();
const equipment = ref<InstanceType<typeof TeachingEquipment>>();
const renderer = ref<TeachingRenderer | null>(null);
const rendererError = ref("");
const assetIssue = ref("");
const mode = ref<"translate" | "rotate">("translate");
const canvasMode = ref<"二维" | "三维">("三维");
const paletteOpen = ref(false);
const inspectorOpen = ref(false);
const analysisOpen = ref(false);
const schemeMenuOpen = ref(false);
const displayMenuOpen = ref(false);
const statusMessage = ref("光路示意已随拖动更新");
const confirmDelete = ref(false);
const selected = computed(() => store.selectedComponent);
onMounted(async () => {
  window.addEventListener('optical-teaching-compute', primaryCompute);
  await store.initialize();
  void analysis.initialize();
  await nextTick();
  if (!canvasHost.value) {
    return;
  }
  try {
    renderer.value = new TeachingRenderer(canvasHost.value, {
      axisHeightMm: store.axis_height_mm,
      onSelect: (id) => store.selectComponent(id),
      onPoseChange: (id, pose) => store.updatePose(id, pose),
      onDragStart: () => store.beginDrag(),
      onDragEnd: () => { void store.endDrag(); },
      onAssetIssue: (message) => {
        statusMessage.value = message;
      },
    });
    renderer.value.setScene(store.components, store.selected_component_id);
    renderer.value.setPreview(store.preview);
  } catch (cause) {
    rendererError.value = cause instanceof Error ? cause.message : String(cause);
  }
  const requestedTool = String(route.query.tool ?? "");
  if (requestedTool === "equipment") paletteOpen.value = true;
  if (requestedTool === "analysis") analysisOpen.value = true;
  if (requestedTool === "sync_to_simulation") void syncToSimulation();
});

watch(
  [() => store.components, () => store.selected_component_id],
  ([components, selectedId]) => renderer.value?.setScene(components, selectedId),
  { deep: true },
);

watch(() => store.preview, preview => renderer.value?.setPreview(preview));
watch(() => store.axis_height_mm, height => renderer.value?.setAxisHeight(height));
watch(() => store.busy, busy => renderer.value?.setInteractionEnabled(!busy));
onBeforeUnmount(() => { window.removeEventListener('optical-teaching-compute', primaryCompute); void store.endDrag(); renderer.value?.dispose(); });
function primaryCompute(): void { activateTool('calculate'); }

async function dropEquipment(kind:ComponentKind,x:number,y:number):Promise<void> {
  if(!document.elementFromPoint(x,y)?.closest('.teaching-bench-2d,.canvas-host'))return;
  const pose=canvasMode.value==='二维'?bench2d.value?.poseAt(x,y):renderer.value?.poseAt(x,y);
  if(pose && await store.addComponent(kind,pose)) {
    if(canvasMode.value==='三维' && store.selected_component_id)equipment.value?.recordDroppedId(store.selected_component_id);
    statusMessage.value=`已添加 ${COMPONENT_CATALOG[kind].label}`;
  }
}

function closeToast(): void {
  assetIssue.value = "";
}

function activateTool(tool: string): void {
  if (tool === "equipment") {
    paletteOpen.value = !paletteOpen.value;
  } else if (tool === "analysis") {
    analysisOpen.value = !analysisOpen.value;
  } else if (tool === "inspector") {
    inspectorOpen.value = !inspectorOpen.value;
  } else if (tool === "display") {
    displayMenuOpen.value = !displayMenuOpen.value;
  } else if (tool === "calculate") {
    void store.refreshPreview().then(ok => { if (ok) statusMessage.value = '光路示意已更新'; });
  } else if (tool === "sync_to_simulation") {
    void syncToSimulation();
  } else if (tool === "sync_from_simulation") {
    void syncFromSimulation();
  }
}

async function syncToSimulation(): Promise<void> {
  if(await sync.toSimulation())statusMessage.value=sync.status;
  else assetIssue.value=sync.status;
}
async function syncFromSimulation(): Promise<void> {
  if(await sync.fromSimulation()){
    statusMessage.value=sync.status;equipment.value?.resetAddedId();
    await nextTick();bench2d.value?.fitScene();renderer.value?.resetView();
  }else assetIssue.value=sync.status || store.error;
}

async function applyScheme(count: number): Promise<void> {
  if (await (count===4?sync.fourAsphere():store.applyScheme(count))) {
    statusMessage.value = count===4?sync.status:`${count === 1 ? "单透镜" : `${count} 透镜`}方案已加载`;
    equipment.value?.resetAddedId();if(count===4)renderer.value?.resetView();
    schemeMenuOpen.value = false;
    await nextTick(); bench2d.value?.fitScene();
  }else if(count===4)assetIssue.value=sync.status || store.error;
}

function setCanvasMode(event: Event): void {
  const nextMode = (event.target as HTMLSelectElement).value;
  if (nextMode === "二维" || nextMode === "三维") canvasMode.value = nextMode;
  statusMessage.value = '';
}

async function deleteSelected(): Promise<void> {
  if (await store.removeSelected()) confirmDelete.value = false;
}
</script>

<template>
  <section class="teaching-shell">
    <div class="teaching-toolbar">
      <div class="scheme-menu-wrap">
        <button class="teaching-tool-button" type="button" :aria-expanded="schemeMenuOpen" @click="schemeMenuOpen = !schemeMenuOpen">方案⌄</button>
        <div v-if="schemeMenuOpen" class="scheme-menu">
          <button v-for="item in [{ count: 1, label: '单透镜' }, { count: 2, label: '双透镜' }, { count: 3, label: '三透镜' }, { count: 4, label: '四非球面 · 780 nm 高效耦合' }]" :key="item.count" type="button" :disabled="store.busy" @click="applyScheme(item.count)">{{ item.label }}</button>
        </div>
      </div>
      <button class="teaching-tool-button" type="button" :aria-pressed="paletteOpen" @click="activateTool('equipment')">器材库</button>
      <div class="scheme-menu-wrap" @keydown.esc="displayMenuOpen = false"><button class="teaching-tool-button" type="button" :aria-expanded="displayMenuOpen" @click="activateTool('display')">视角</button><div v-if="displayMenuOpen" class="scheme-menu" role="menu" aria-label="视角"><button role="menuitem" @click="renderer?.resetView(); displayMenuOpen = false">重置三维视角</button><button role="menuitem" @click="renderer?.topView(); displayMenuOpen = false">俯视</button><button role="menuitem" @click="bench2d?.fitScene(); displayMenuOpen = false">二维适配画面</button></div></div>
      <button class="teaching-tool-button" data-tool="analysis" type="button" :aria-pressed="analysisOpen" @click="activateTool('analysis')">成像与耦合</button>
      <button class="teaching-tool-button" data-tool="calculate" type="button" @click="activateTool('calculate')">计算</button>
      <button class="teaching-tool-button" data-tool="sync_to_simulation" type="button" @click="activateTool('sync_to_simulation')">同步到仿真</button>
      <button class="teaching-tool-button" data-tool="sync_from_simulation" type="button" @click="activateTool('sync_from_simulation')">从仿真更新</button>
      <span class="teaching-toolbar-spacer"></span>
      <span class="teaching-status">{{ statusMessage }}</span>
      <label class="teaching-toolbar-label" for="teaching-canvas-mode">画布</label>
      <select id="teaching-canvas-mode" :value="canvasMode" @change="setCanvasMode">
        <option>二维</option>
        <option>三维</option>
      </select>
    </div>

    <div class="bench-area">
      <div ref="canvasHost" class="canvas-host" :style="{ visibility: canvasMode === '三维' ? 'visible' : 'hidden' }">
        <div v-if="rendererError" class="canvas-error" role="alert">
          <strong>3D 视口不可用</strong>
          <p>{{ rendererError }}</p>
        </div>
        <div v-else-if="!renderer" class="canvas-loading"><span class="loading-spinner"></span><span>正在加载画布…</span></div>
      </div>

      <TeachingBench2D ref="bench2d" v-show="canvasMode === '二维'" :visible="canvasMode === '二维'" @inspect="inspectorOpen = true" />

      <TeachingEquipment ref="equipment" v-show="paletteOpen" @close="paletteOpen = false" @status="statusMessage = $event" @drop="dropEquipment" />

      <TeachingAnalysis v-show="analysisOpen" @close="analysisOpen = false" />

      <TeachingInspector v-show="inspectorOpen" :visible="inspectorOpen" @close="inspectorOpen = false" @publish="activateTool('sync_to_simulation')" />

      <div class="canvas-actions">
        <button class="canvas-action" type="button" title="成像与耦合" aria-label="成像与耦合" @click="activateTool('analysis')"><img src="/icons/intensity.svg" alt="" /></button>
        <button class="canvas-action" type="button" title="属性" aria-label="属性" @click="activateTool('inspector')"><img src="/icons/properties.svg" alt="" /></button>
      </div>

      <div class="quick-actions" aria-label="画布编辑操作">
        <button class="quick-action" type="button" :disabled="!store.canUndo" title="撤销" @click="store.undo()"><img src="/icons/undo.svg" alt="" />撤销</button>
        <button class="quick-action" type="button" :disabled="!store.canRedo" title="重做" @click="store.redo()"><img src="/icons/redo.svg" alt="" />下一步</button>
        <button class="quick-action" type="button" :disabled="!selected" title="删除当前选中器件" @click="confirmDelete = true"><img src="/icons/delete.svg" alt="" />删除</button>
        <button class="quick-action" type="button" :disabled="!store.components.length || store.busy" title="清空教学台" @click="store.clearScene()"><img src="/icons/reset.svg" alt="" />清空</button>
      </div>
    </div>

    <BaseToast v-if="assetIssue" :message="assetIssue" tone="info" @close="closeToast" />
    <BaseToast v-if="store.inspectionError" :message="store.inspectionError" tone="error" @close="store.inspectionError = ''" />
    <BaseToast v-if="store.error" :message="store.error" tone="error" @close="store.error = ''" />
    <BaseModal
      :open="confirmDelete"
      title="删除当前器件？"
      :description="selected ? `${selected.label} 将从当前场景移除，场景 revision 会递增。` : ''"
      @close="confirmDelete = false"
      @confirm="deleteSelected"
    />
  </section>
</template>
