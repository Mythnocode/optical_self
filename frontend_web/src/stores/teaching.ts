import { defineStore, acceptHMRUpdate } from 'pinia';
import { computed, ref, watch, onScopeDispose } from 'vue';
import { apiRequest } from '../api/http.js';
import { isComponentKind, type ComponentKind } from '../teaching/domain/component-catalog.js';
import type { TeachingPose, TeachingScene, TeachingPreview, TeachingCanvasPresentation } from '../teaching/domain/scene-types.js';
import emptyScene from '../teaching/domain/empty-scene.json';
import { PROJECT_FILE_LIMIT } from '../domain/project-files.js';
import { sceneCalculationSignature, type TeachingPhysicsResult } from '../teaching/domain/analysis-types.js';
import type { SimulationRequest } from '../domain/simulation-project.js';

const STORAGE_KEY = 'optical.teaching.scene.v2';
function clone<T>(value: T): T { return JSON.parse(JSON.stringify(value)) as T; }
function checkScene(scene: TeachingScene): void {
  if (scene.schema_version !== 2 || !Array.isArray(scene.components) || !scene.reference
    || !Number.isFinite(scene.reference.axis_height_mm) || scene.components.some(item => !isComponentKind(item.kind))) throw new Error('教学场景格式或器件类型不受支持。');
}

export const useTeachingStore = defineStore('teaching', () => {
  const scene = ref<TeachingScene>(clone(emptyScene) as TeachingScene);
  const busy = ref(false), initialized = ref(false), error = ref(''), copyStatus = ref('');
  const undoStack = ref<TeachingScene[]>([]), redoStack = ref<TeachingScene[]>([]);
  const savedSignature = ref(JSON.stringify(scene.value));
  const dragging = ref(false);
  const setupWarnings = ref<string[]>([]), preview = ref<TeachingPreview | null>(null), inspectionError = ref('');
  const inspectedKey=ref('');
  const inspectionCurrent=computed(()=>inspectedKey.value===sceneCalculationSignature(scene.value));
  const canvas2d = ref<TeachingCanvasPresentation | null>(null);
  const baseline_x_mm = computed(() => scene.value.baseline_x_mm);
  let inspectTimer: ReturnType<typeof setTimeout> | undefined, inspectController: AbortController | undefined, inspectGeneration = 0;
  let initializePromise: Promise<void> | undefined, dragBefore: TeachingScene | undefined;
  const components = computed(() => scene.value.components);
  const revision = computed(() => scene.value.revision);
  const axis_height_mm = computed(() => scene.value.reference.axis_height_mm);
  const baseline_enabled = computed(() => scene.value.baseline_enabled);
  const selected_component_id = computed({ get: () => scene.value.selected_component_id, set: value => { scene.value.selected_component_id = value; } });
  const selectedComponent = computed(() => components.value.find(item => item.component_id === selected_component_id.value) ?? null);
  const canUndo = computed(() => !busy.value && !dragging.value && undoStack.value.length > 0);
  const canRedo = computed(() => !busy.value && !dragging.value && redoStack.value.length > 0);
  const dirty = computed(() => JSON.stringify(scene.value) !== savedSignature.value);
  watch(scene, value => {
    if (!initialized.value || dragging.value) return;
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(value)); }
    catch { error.value = '教学场景未能写入本机缓存，请保存场景文件。'; }
  }, { deep: true });
  watch(() => JSON.stringify([initialized.value, scene.value.revision, scene.value.components, scene.value.reference]), () => {
    const generation = ++inspectGeneration;
    clearTimeout(inspectTimer); inspectController?.abort(); preview.value = null;
    if (!initialized.value) return;
    inspectTimer = setTimeout(() => { void inspectScene(generation); }, dragging.value ? 80 : 0);
  });
  async function inspectScene(generation: number): Promise<boolean> {
    inspectController = new AbortController();
    const sourceScene=sceneSnapshot();
    try {
      const response = await apiRequest<{ warnings: string[]; preview: TeachingPreview; canvas2d: TeachingCanvasPresentation; geometry: Record<string, unknown> }>('/api/v1/teaching/scenes/inspect', { method: 'POST', body: sourceScene, signal: inspectController.signal });
      if (generation !== inspectGeneration) return false;
      setupWarnings.value = response.data.warnings; preview.value = response.data.preview; canvas2d.value = response.data.canvas2d;
      inspectedKey.value=sceneCalculationSignature(sourceScene);
      if(response.data.geometry){scene.value.results.geometry=response.data.geometry;scene.value.active_result_revision=scene.value.revision;}
      inspectionError.value = ''; return true;
    } catch (cause) { if (generation === inspectGeneration) { setupWarnings.value = []; inspectionError.value = message(cause); } return false; }
  }
  async function refreshPreview(): Promise<boolean> {
    await initialize(); if (busy.value || dragging.value) return false;
    clearTimeout(inspectTimer); inspectController?.abort();
    return inspectScene(++inspectGeneration);
  }
  onScopeDispose(() => { clearTimeout(inspectTimer); inspectGeneration++; inspectController?.abort(); });

  async function normalize(candidate: unknown): Promise<TeachingScene> {
    const response = await apiRequest<{ scene: TeachingScene }>('/api/v1/teaching/scenes/normalize', { method: 'POST', body: candidate });
    checkScene(response.data.scene); return response.data.scene;
  }
  function initialize(): Promise<void> {
    if (initializePromise) return initializePromise;
    initializePromise = (async () => {
      busy.value = true;
      try {
        const stored = localStorage.getItem(STORAGE_KEY);
        scene.value = stored ? await normalize(JSON.parse(stored)) : clone(emptyScene) as TeachingScene;
        savedSignature.value = JSON.stringify(scene.value); initialized.value = true;
      } catch (cause) {
        error.value = message(cause); initialized.value = true;
        try { const unreadable = localStorage.getItem(STORAGE_KEY); if (unreadable) localStorage.setItem(`${STORAGE_KEY}.recovery`, unreadable); } catch { /* Original cache remains untouched. */ }
      }
      finally { busy.value = false; }
    })();
    return initializePromise;
  }
  function record(before: TeachingScene): void {
    undoStack.value.push(clone(before)); if (undoStack.value.length > 50) undoStack.value.shift(); redoStack.value = [];
  }
  async function edit(action: string, values: Record<string, unknown> = {}, before = sceneSnapshot()): Promise<boolean> {
    if (busy.value || !initialized.value) return false;
    busy.value = true; error.value = '';
    try {
      const response = await apiRequest<{ scene: TeachingScene }>('/api/v1/teaching/scenes/edit', { method: 'POST', body: { scene: before, action, ...values } });
      checkScene(response.data.scene); record(before); scene.value = response.data.scene; return true;
    } catch (cause) { scene.value = before; error.value = message(cause); return false; }
    finally { busy.value = false; }
  }
  async function addComponent(kind: ComponentKind, pose?: TeachingPose): Promise<boolean> { return edit('add', { kind, ...(pose ? {pose} : {}) }); }
  function selectComponent(id: string | null): void {
    if (busy.value || dragBefore) return;
    selected_component_id.value = components.value.some(item => item.component_id === id) ? id : null;
  }
  function beginDrag(): void { if (!busy.value && !dragBefore) { dragBefore = sceneSnapshot(); dragging.value = true; } }
  function cancelDrag(): void { if (dragBefore) scene.value = dragBefore; dragBefore = undefined; dragging.value = false; }
  function updatePose(id: string, pose: TeachingPose): void {
    if (!Object.values(pose).every(Number.isFinite) || busy.value) return;
    if (dragBefore) {
      const component = components.value.find(item => item.component_id === id);
      if (component) {
        component.pose = clone(pose);
        for(const result of Object.values(scene.value.results))result.stale=true;
        scene.value.active_result_revision=null;
      }
    } else void edit('pose', { component_id: id, pose });
  }
  async function endDrag(): Promise<void> {
    const before = dragBefore; dragBefore = undefined; dragging.value = false;
    if (!before) return;
    const changed = components.value.find(item => JSON.stringify(item.pose) !== JSON.stringify(before.components.find(old => old.component_id === item.component_id)?.pose));
    if (changed) await edit('pose', { component_id: changed.component_id, pose: clone(changed.pose) }, before);
  }
  async function removeSelected(): Promise<boolean> { return selected_component_id.value ? edit('remove', { component_id: selected_component_id.value }) : false; }
  async function clearScene(): Promise<boolean> { return components.value.length ? edit('clear') : false; }
  async function applyScheme(count: number): Promise<boolean> { return edit('scheme', { lens_count: count }); }
  async function updateParams(id: string, params: Record<string, unknown>): Promise<boolean> { return edit('params', { component_id: id, params }); }
  async function setEnabled(id: string, enabled: boolean): Promise<boolean> { return edit('enabled', { component_id: id, enabled }); }
  async function setBaseline(enabled: boolean, x?: number): Promise<boolean> { return edit('baseline', { enabled, baseline_x_mm: x }); }
  function sceneSnapshot(): TeachingScene { return clone(scene.value); }
  async function synchronizeFrom(simulation:SimulationRequest,inherit_contract:boolean,isCurrent:()=>boolean,editor_project?:SimulationRequest['project']):Promise<{engineering_request:SimulationRequest|null;status:string}|null>{
    await initialize();if(busy.value || dragging.value)return null;
    const before=sceneCalculationSignature(scene.value);busy.value=true;error.value='';
    try{
      const response=await apiRequest<{scene:TeachingScene;engineering_request:SimulationRequest|null;status:string}>('/api/v1/teaching/scenes/from-simulation',{method:'POST',body:{scene:sceneSnapshot(),simulation,inherit_contract,editor_project},timeoutMs:120000});
      if(!isCurrent() || sceneCalculationSignature(scene.value)!==before)throw new Error('同步期间工程已修改，请重新更新教学台。');
      checkScene(response.data.scene);scene.value=response.data.scene;undoStack.value=[];redoStack.value=[];
      return {engineering_request:response.data.engineering_request,status:response.data.status};
    }catch(cause){error.value=message(cause);return null;}finally{busy.value=false;}
  }
  async function applyFormalResult(jobId: string,engineering_request:SimulationRequest|null=null,isCurrent:()=>boolean=()=>true): Promise<TeachingPhysicsResult | null> {
    const before=sceneSnapshot(), signature=sceneCalculationSignature(before);
    const response=await apiRequest<{scene:TeachingScene;physics:TeachingPhysicsResult}>(`/api/v1/teaching/jobs/${encodeURIComponent(jobId)}/apply`,{method:'POST',body:{scene:before,engineering_request}});
    if(sceneCalculationSignature(scene.value)!==signature || !isCurrent())return null;
    checkScene(response.data.scene);
    for(const [kind,result] of Object.entries(response.data.scene.results))if(kind!=='geometry')scene.value.results[kind]=result;
    scene.value.active_result_revision=response.data.scene.active_result_revision;
    return response.data.physics;
  }
  function undo(): void {
    if (!canUndo.value) return;
    redoStack.value.push(sceneSnapshot()); scene.value = undoStack.value.pop()!; error.value = '';
  }
  function redo(): void {
    if (!canRedo.value) return;
    undoStack.value.push(sceneSnapshot()); scene.value = redoStack.value.pop()!; error.value = '';
  }
  async function loadScene(candidate: unknown): Promise<boolean> {
    await initialize(); if (busy.value || dragBefore) return false;
    busy.value = true; error.value = '';
    try {
      const replacement = await normalize(candidate);
      scene.value = replacement; undoStack.value = []; redoStack.value = [];
      initialized.value = true; savedSignature.value = JSON.stringify(scene.value); return true;
    } catch (cause) { error.value = message(cause); return false; }
    finally { busy.value = false; }
  }
  async function importScene(contents: string): Promise<boolean> {
    try {
      if (new TextEncoder().encode(contents).byteLength > PROJECT_FILE_LIMIT) throw new Error('教学场景文件超过 64 MiB。');
      return await loadScene(JSON.parse(contents.replace(/^\uFEFF/, '')));
    } catch (cause) { error.value = message(cause); return false; }
  }
  async function save(): Promise<void> {
    await initialize(); if (busy.value || dragBefore || !initialized.value) return;
    busy.value = true; error.value = '';
    try {
      const snapshot = sceneSnapshot(), contents = JSON.stringify(snapshot, null, 2);
      if (window.opticalDesktop) {
        const result = await window.opticalDesktop.saveTextFile({ suggestedName: 'teaching-scene.json', contents });
        if (!result.canceled) savedSignature.value = JSON.stringify(snapshot);
      } else {
        const url = URL.createObjectURL(new Blob([contents], { type: 'application/json' }));
        const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'teaching-scene.json'; anchor.click();
        window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
      }
    } catch (cause) { error.value = message(cause); }
    finally { busy.value = false; }
  }
  async function copyProject(): Promise<void> {
    await initialize(); if (busy.value || dragBefore) return;
    error.value = ''; copyStatus.value = '';
    try { await navigator.clipboard.writeText(JSON.stringify(sceneSnapshot(), null, 2)); copyStatus.value = '已复制教学场景。'; }
    catch (cause) { error.value = message(cause); }
  }
  return { components, revision, axis_height_mm, baseline_enabled, baseline_x_mm, selected_component_id, selectedComponent, busy, dragging, error, copyStatus, dirty, canUndo, canRedo, setupWarnings, preview, canvas2d, inspectionError,
    inspectionCurrent, initialize, refreshPreview, applyFormalResult, synchronizeFrom, addComponent, selectComponent, updatePose, beginDrag, endDrag, cancelDrag, removeSelected, clearScene, applyScheme, updateParams, setEnabled, setBaseline, sceneSnapshot, loadScene, importScene, save, copyProject, undo, redo };
});
function message(cause: unknown): string { return cause instanceof Error ? cause.message : String(cause); }
if (import.meta.hot) import.meta.hot.accept(acceptHMRUpdate(useTeachingStore, import.meta.hot));
