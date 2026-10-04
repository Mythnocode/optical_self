import { defineStore } from "pinia";
import { computed, ref, shallowRef, watch } from "vue";
import { getJobResult, submitSimulation } from "../api/jobs.js";
import { clone, defaultRequest, editSurface, fieldValue, fingerprint, lensGroups, newSurface, normalizeSurfaces, readSavedRequest, surfaceId, type SurfaceField, type SurfaceSnapshot } from "../domain/simulation-project.js";
import { useJobsStore } from "./jobs.js";
import { auxiliaryWavelengths, computationRequest, requestOptions, synchronizeRequest, uiState } from "../domain/simulation-options.js";
import type { AnalysisSettings } from "../domain/simulation-project.js";
import type { SimulationUiState } from "../domain/simulation-project.js";
import { apiRequest } from "../api/http.js";
import { cacheField, projectSettings, restoreField } from "../domain/complex-field-cache.js";
import { airNames, type CustomMaterial } from '../domain/materials.js';
import { parseProjectFile } from '../domain/project-files.js';

import { applySurfaceType, canonicalProject, parameters, parseParameter, surfaceRegistry, surfaceSpec } from '../domain/surface-registry.js';

const PROJECT_KEY = "optical.simulation.project.v1";
const JOB_KEY = "optical.simulation.job.v1";
const CONTEXT_KEY = 'optical.simulation.context.v1';
export const useSimulationStore = defineStore("simulation", () => {
  const jobs = useJobsStore();
  const error = ref("");
  const copyStatus = ref('');
  function newProject() {
    const initial = defaultRequest();
    // WorkbenchShell's initial calculation selection differs from SourceFormState's preset.
    initial.project.analysis_settings.requested_analyses = ["raytrace", "spot", "coupling", "psf"];
    synchronizeRequest(initial); return initial;
  }
  function restore() {
    try { const saved = localStorage.getItem(PROJECT_KEY); return saved ? readSavedRequest(saved) : newProject(); }
    catch { error.value = "保存的项目无法读取，已载入默认系统。"; return newProject(); }
  }
  const request = ref(restore());
  const contextId = ref(localStorage.getItem(CONTEXT_KEY) || crypto.randomUUID());
  localStorage.setItem(CONTEXT_KEY, contextId.value);
  uiState(request.value);
  const project = computed(() => request.value.project);
  const revision = ref(0);
  const selectedId = ref(project.value.surfaces[0] ? surfaceId(project.value.surfaces[0]) : "");
  const groups = computed(() => lensGroups(project.value));
  const customMaterials = computed(() => request.value.frontend_state?.custom_materials ?? []);
  function upsertCustomMaterial(material: CustomMaterial): void {
    const name = material.name.trim(); if(airNames.includes(name.toUpperCase()))return;
    const updated=clone(request.value), ui=uiState(updated);
    ui.custom_materials=[...(ui.custom_materials??[]).filter(item=>item.name.trim()!==name),{...clone(material),name}];
    request.value=updated;
  }
  const selectedIndex = computed(() => project.value.surfaces.findIndex((surface) => surfaceId(surface) === selectedId.value));
  const importing = ref(false), canUndo = ref(false), canRedo = ref(false);
  type SurfaceEdit = { surfaces: typeof project.value.surfaces; selected: string; signature: string };
  function surfaceEdit(): SurfaceEdit {
    const surfaces = clone(project.value.surfaces);
    return { surfaces, selected: selectedId.value, signature: JSON.stringify(surfaces) };
  }
  let currentEdit = surfaceEdit(), historyPending = false, historyApplying = false;
  const previousEdits: SurfaceEdit[] = [], followingEdits: SurfaceEdit[] = [];
  function flushHistory(): void {
    if (!historyPending) return;
    historyPending = false;
    const next = surfaceEdit();
    if (next.signature === currentEdit.signature) return;
    previousEdits.push(currentEdit); if (previousEdits.length > 50) previousEdits.shift();
    currentEdit = next; followingEdits.length = 0;
    canUndo.value = Boolean(previousEdits.length); canRedo.value = false;
  }
  watch(() => project.value.surfaces, () => {
    if (historyApplying || historyPending) return;
    historyPending = true; queueMicrotask(flushHistory);
  }, { deep: true, flush: 'sync' });
  function restoreEdit(direction: 'undo' | 'redo'): void {
    if (importing.value) return;
    flushHistory();
    const source = direction === 'undo' ? previousEdits : followingEdits;
    const destination = direction === 'undo' ? followingEdits : previousEdits;
    const edit = source.pop(); if (!edit) return;
    destination.push(currentEdit); historyApplying = true;
    try {
      project.value.surfaces = clone(edit.surfaces);
      selectedId.value = project.value.surfaces.some(row => surfaceId(row) === edit.selected) ? edit.selected : project.value.surfaces[0] ? surfaceId(project.value.surfaces[0]) : '';
      currentEdit = surfaceEdit(); error.value = '';
    } finally { historyApplying = false; }
    canUndo.value = Boolean(previousEdits.length); canRedo.value = Boolean(followingEdits.length);
  }
  const undo = () => restoreEdit('undo'), redo = () => restoreEdit('redo');
  const submitting = ref(false);
  const resultLoading = ref(false);
  const result = shallowRef<Record<string, unknown> | null>(null);
  const activeJobId = ref("");
  const submittedProject = ref("");
  const submittedSnapshot = shallowRef<typeof request.value.project | null>(null);
  const submittedRequest = shallowRef<typeof request.value | null>(null);
  const submittedContextId = ref('');
  try { const saved = JSON.parse(localStorage.getItem(JOB_KEY) || "{}"); activeJobId.value = saved.id || ""; submittedProject.value = saved.project || ""; submittedSnapshot.value = saved.snapshot || null; submittedRequest.value = saved.request || null; submittedContextId.value = saved.contextId || (saved.project === calculationSignature() ? contextId.value : ''); } catch { /* Invalid saved job is discarded. */ }
  const job = computed(() => jobs.jobs[activeJobId.value] ?? null);
  const busy = computed(() => submitting.value || Boolean(job.value && !["completed", "failed", "cancelled"].includes(job.value.status)));
  function calculationSignature(): string {
    const settings = projectSettings(request.value);
    return JSON.stringify({ project: settings.project, options: settings.options, analyses: settings.analyses, precision: settings.precision,
      imported_field_id: settings.project.receiver.mode_model === "imported" ? settings.frontend_state?.imported_field_ref?.id : undefined });
  }
  const resultStale = computed(() => Boolean(submittedProject.value && submittedProject.value !== calculationSignature()));
  function fileSignature(): string { return JSON.stringify(projectSettings(request.value)); }
  const savedSignature = ref(fileSignature());
  const dirty = computed(() => savedSignature.value !== fileSignature());
  watch(request, () => {
    revision.value++;
    try { localStorage.setItem(PROJECT_KEY, JSON.stringify(projectSettings(request.value))); }
    catch { error.value = "本机存储空间不足，请将项目保存到文件。"; }
  }, { deep: true, flush: "sync" });
  watch([activeJobId, () => job.value?.status], ([id, status]) => {
    if (id && status === "completed") void loadResult(id);
    if (id && status === "failed") {
      const failure = job.value?.error;
      error.value = typeof failure === "string" ? failure : failure?.message || "计算失败，请查看任务中心。";
    }
  }, { immediate: true });
  if (activeJobId.value) void jobs.track(activeJobId.value);
  const observation = computed(() => request.value.frontend_state!.observation ?? { enabled: true, mode: "surface", surface_index: 0, offset_mm: 0, pitch_um: 5, pixels_x: 1024, pixels_y: 1024 });
  function setObservation(key: string, value: number | string | boolean) {
    request.value.frontend_state!.observation = { ...observation.value, [key]: value };
  }

  function parameter(path: string): number | string | boolean {
    const [section, key] = path.split(".");
    const ui = uiState(request.value);
    if (section === "ui") return (ui as unknown as Record<string, number | string | boolean>)[key];
    if (section === "source" && key in ui.source_axes!) return ui.source_axes![key];
    if (path === "receiver.mode_field_diameter_y_um") return ui.fiber_mfd_y_um!;
    if (section === "environment") return Number(request.value.options[key]);
    return (project.value[section as "source" | "receiver" | "analysis_settings"] as unknown as Record<string, number | string | boolean>)[key];
  }
  function setParameter(path: string, value: number | string | boolean): void {
    const updated = clone(request.value), p = updated.project, s = p.source, r = p.receiver, ui = uiState(updated);
    const [section, key] = path.split(".");
    if (section === "ui") {
      (ui as unknown as Record<string, unknown>)[key] = value;
      if (key === "source_split" && value) Object.assign(s, ui.source_axes);
      if (key === "source_split" && !value) {
        s.waist_x_mm = s.waist_y_mm = ui.source_waist_um * .001;
        s.waist_position_x_mm = s.waist_position_y_mm = ui.source_position_mm;
        s.beam_quality_m2_x = s.beam_quality_m2_y = ui.source_m2;
      }
      if (key === "source_waist_um" && !ui.source_split) s.waist_x_mm = s.waist_y_mm = Number(value) * .001;
      if (key === "source_position_mm" && !ui.source_split) s.waist_position_x_mm = s.waist_position_y_mm = Number(value);
      if (key === "source_m2" && !ui.source_split) s.beam_quality_m2_x = s.beam_quality_m2_y = Number(value);
      if (key === "source_na_split" && !value) s.object_na_y = s.object_na_x;
      if (key === "fiber_split") {
        if (!value) ui.fiber_mfd_y_um = r.mode_field_diameter_x_um;
        r.mode_field_diameter_y_um = ui.fiber_mfd_y_um!;
      }
      if (key === "fiber_na_split" && !value) r.na_y = r.na_x;
      if (key === "fiber_tilt_x_urad") r.tilt_x_deg = Number(value) * 1e-6 * (180 / Math.PI);
      if (key === "fiber_tilt_y_urad") r.tilt_y_deg = Number(value) * 1e-6 * (180 / Math.PI);
      if (key === "image_distance_mm") p.image_distance_mm = Math.max(Number(value), 1e-9);
      if (key === "fiber_kind" || key === "fiber_model") {
        if (ui.fiber_kind === "user_mode") ui.fiber_model = "imported";
        r.mode_model = ui.fiber_kind === "multimode_fiber" ? "gaussian" : ui.fiber_model!;
        r.receiver_type = r.mode_model === "imported" ? "user_mode" : ui.fiber_kind!;
        r.core_diameter_um = ui.fiber_kind === "multimode_fiber" ? ui.fiber_core_mm_um! : ui.fiber_core_sm_um!;
      }
    } else if (section === "system") {
      (p as unknown as Record<string, unknown>)[key] = value;
    } else if (section === "environment") updated.options[key] = value;
    else {
      if (path === "source.wavelength_nm") s.spectral_wavelengths_nm = s.spectral_wavelengths_nm.filter(wavelength => Math.abs(wavelength - s.wavelength_nm) > 1e-9);
      if (section === "source" && key in ui.source_axes!) {
        ui.source_axes![key] = Number(value);
        if (ui.source_split) (s as unknown as Record<string, unknown>)[key] = value;
      } else if (path === "receiver.mode_field_diameter_y_um") {
        ui.fiber_mfd_y_um = Number(value);
        if (ui.fiber_split) r.mode_field_diameter_y_um = Number(value);
      } else (p[section as "source" | "receiver" | "analysis_settings"] as unknown as Record<string, unknown>)[key] = value;
      if (path === "source.object_na_x" && !ui.source_na_split) s.object_na_y = Number(value);
      if (path === "receiver.mode_field_diameter_x_um" && !ui.fiber_split) ui.fiber_mfd_y_um = r.mode_field_diameter_y_um = Number(value);
      if (path === "receiver.na_x" && !ui.fiber_na_split) r.na_y = Number(value);
      if (path === "receiver.core_diameter_um") {
        if (ui.fiber_kind === "multimode_fiber") ui.fiber_core_mm_um = Number(value); else ui.fiber_core_sm_um = Number(value);
      }
    }
    synchronizeRequest(updated); request.value = updated; error.value = "";
  }
  function setAuxiliary(text: string): void {
    const updated = clone(request.value);
    updated.project.source.spectral_wavelengths_nm = [updated.project.source.wavelength_nm, ...auxiliaryWavelengths(text, updated.project.source.wavelength_nm)];
    synchronizeRequest(updated); request.value = updated;
  }
  function applySettings(settings: AnalysisSettings): void {
    const updated = clone(request.value);
    updated.project.analysis_settings = clone(settings);
    const analyses = [...settings.requested_analyses];
    if (settings.calc_high_precision_coupling && !analyses.includes("coupling")) analyses.push("coupling");
    updated.project.analysis_settings.requested_analyses = analyses.length ? analyses : ["raytrace"];
    synchronizeRequest(updated); request.value = updated; error.value = "";
  }
  const fieldLoading = ref(false), fieldError = ref("");
  function rejectField(cause: unknown): void {
    const updated = clone(request.value);
    delete uiState(updated).imported_field;
    delete uiState(updated).imported_field_ref;
    const hybrid = updated.options.hybrid as Record<string, unknown> | undefined;
    if (hybrid) { delete hybrid.imported_mode_values; delete hybrid.imported_mode_source; }
    synchronizeRequest(updated); request.value = updated;
    fieldError.value = cause instanceof Error ? cause.message : String(cause);
  }
  async function importField(selection: { source_path: string } | { filename: string; contents_base64: string }): Promise<void> {
    const grid = project.value.analysis_settings.calc_grid_size;
    fieldLoading.value = true; fieldError.value = "";
    try {
      const response = await apiRequest<NonNullable<SimulationUiState['imported_field']>>("/api/v1/simulation/import-complex-field", {
        method: "POST", body: { ...selection, expected_grid_size: grid }, timeoutMs: 120000,
      });
      if (project.value.analysis_settings.calc_grid_size !== grid) throw new Error("接收面网格已变化，请重新选择复场文件。");
      const reference = await cacheField(response.data);
      if (project.value.analysis_settings.calc_grid_size !== grid) throw new Error("接收面网格已变化，请重新选择复场文件。");
      const updated = clone(request.value);
      uiState(updated).imported_field = response.data;
      uiState(updated).imported_field_ref = reference;
      synchronizeRequest(updated); request.value = updated;
    } catch (cause) {
      // A failed selection invalidates the prior field, matching the original selector.
      rejectField(cause);
    } finally { fieldLoading.value = false; }
  }

  const fieldRestoration = (async () => {
    const state = uiState(request.value), reference = state.imported_field_ref;
    if (!reference && !state.imported_field) return;
    fieldLoading.value = true;
    try {
      const field = state.imported_field ?? await restoreField(reference!);
      const cached = state.imported_field ? await cacheField(field) : reference!;
      const updated = clone(request.value);
      uiState(updated).imported_field = field; uiState(updated).imported_field_ref = cached;
      synchronizeRequest(updated); request.value = updated;
    } catch (cause) { rejectField(cause); }
    finally { fieldLoading.value = false; }
  })();

  function change(field: SurfaceField, text: string): boolean {
    const surface = project.value.surfaces[selectedIndex.value];
    if (!surface) return false;
    try {
      const updated = clone(surface);
      editSurface(updated, field, text);
      project.value.surfaces.splice(selectedIndex.value, 1, updated);
      normalizeSurfaces(project.value); error.value = ""; return true;
    } catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause); return false; }
  }
  function nextGroup(prefix = "L"): string {
    const used = new Set(project.value.surfaces.map((surface) => String(surface.metadata.group_id)));
    let index = 1; while (used.has(`${prefix}${index}`)) index++; return `${prefix}${index}`;
  }
  function editProperty(surface: SurfaceSnapshot, rowIndex: number, key: string, value: string | boolean, resetParameters = true): void {
    if (["group_id", "note"].includes(key)) {
      surface.metadata[key] = String(value).trim() || (key === "group_id" ? `S${rowIndex + 1}` : "");
    } else if (key === "enabled") surface.enabled = Boolean(value);
    else if (["roughness_rms_nm", "mechanical_diameter_mm"].includes(key)) {
      const number = Number(value);
      if (!String(value).trim() || !Number.isFinite(number) || number < (key === "mechanical_diameter_mm" ? 0.0001 : 0)) throw new Error("请输入有效的非负数值。");
      surface[key] = number;
    } else if (key === "clear_diameter") {
      const number = Number(value);
      if (!String(value).trim() || !Number.isFinite(number) || number < 1e-6 || number > 2e9) throw new Error("请输入有效的通光直径。");
      parameters(surface)._clear_aperture_mm = number;
      surface.clear_aperture_mm = number / 2;
    } else if (key === "coating_preset") surface.metadata.coating_preset = String(value).trim() || "无";
    else if (key === "aperture_type") parameters(surface)._aperture_type = value;
    else if (key === "surface_type") applySurfaceType(surface, String(value), resetParameters);
    else {
      const spec = surfaceSpec(surface).parameters.find(item => item.key === key);
      if (!spec) throw new Error("该表面没有此参数。");
      parameters(surface)[key] = parseParameter(value, spec);
      if (["a4", "a6", "a8"].includes(key)) {
        delete parameters(surface).asphere_coefficients;
        surface.asphere_coefficients = ["a4", "a6", "a8"].map(name => Number(parameters(surface)[name] ?? 0));
      }
    }
  }
  function changeProperty(key: string, value: string | boolean, resetParameters = true): void {
    const selected = project.value.surfaces[selectedIndex.value]; if (!selected) return;
    const surface = clone(selected);
    try {
      editProperty(surface, selectedIndex.value, key, value, resetParameters);
      project.value.surfaces.splice(selectedIndex.value, 1, surface); normalizeSurfaces(project.value); error.value = '';
    } catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause); }
  }
  function pasteCells(startId: string, fields: string[], values: string[][]): boolean {
    const first = project.value.surfaces.findIndex(surface => surfaceId(surface) === startId);
    try {
      if (first < 0 || !values.length || values.length > 4096 || first + values.length > project.value.surfaces.length
        || values.some(row => row.length > fields.length)) throw new Error('粘贴范围超出当前表格。');
      const updated = clone(project.value);
      values.forEach((row, offset) => row.forEach((text, column) => {
        const surface = updated.surfaces[first + offset], field = fields[column];
        if (['name', 'radius', 'thickness', 'material', 'aperture'].includes(field)) editSurface(surface, field as SurfaceField, text);
        else if (field === 'surface_type') editProperty(surface, first + offset, field, surfaceRegistry.find(item => item.name === text.trim())?.key ?? 'user_defined', false);
        else editProperty(surface, first + offset, field, text);
      }));
      normalizeSurfaces(updated); project.value.surfaces = updated.surfaces; error.value = ''; return true;
    } catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause); return false; }
  }
  function insert(surfaces: typeof project.value.surfaces): void {
    const index = selectedIndex.value < 0 ? project.value.surfaces.length : selectedIndex.value + 1;
    project.value.surfaces.splice(index, 0, ...surfaces); normalizeSurfaces(project.value);
    selectedId.value = surfaceId(surfaces[0]); error.value = "";
  }
  function add(kind: "lens" | "internal" | "surface"): void {
    const selected = project.value.surfaces[selectedIndex.value];
    if (kind === "internal" && selected) {
      const group = String(selected.metadata.group_id);
      const count = project.value.surfaces.filter((surface) => surface.metadata.group_id === group).length;
      insert([newSurface(group, String(selected.metadata.element_id), `${group} 内部面 ${count}`, 30, 1, "N-BK7", selected.clear_aperture_mm ?? 3)]);
    } else {
      const group = nextGroup(kind === "lens" ? "L" : "S"); const element = `element-${crypto.randomUUID()}`;
      insert(kind === "lens" ? [newSurface(group, element, `${group} 前表面`, 20, 2, "N-BK7"), newSurface(group, element, `${group} 后表面`, -20, 3, "AIR")]
        : [newSurface(group, element, `${group} 球面`, 50, 1, "N-BK7", 5)]);
    }
  }
  function addSpecial(key: string): void {
    const spec = surfaceRegistry.find(item => item.key === key); if (!spec) return;
    const group = nextGroup(spec.group_prefix);
    const surface = newSurface(group, `element-${crypto.randomUUID()}`, `${group} ${spec.name}`, 50, 1, key === "mirror" ? "MIRROR" : "N-BK7", 5);
    applySurfaceType(surface, key); insert([surface]);
  }
  function remove(): void {
    const index = selectedIndex.value; if (index < 0) return;
    project.value.surfaces.splice(index, 1); normalizeSurfaces(project.value);
    selectedId.value = project.value.surfaces[Math.min(index, project.value.surfaces.length - 1)]?.metadata.surface_id as string || "";
    error.value = "";
  }
  function duplicate(group = false): void {
    const selected = project.value.surfaces[selectedIndex.value]; if (!selected) return;
    const copies = clone(group ? project.value.surfaces.filter((surface) => surface.metadata.group_id === selected.metadata.group_id) : [selected]);
    const oldGroup = String(selected.metadata.group_id); const newGroup = nextGroup(group ? oldGroup.replace(/[^a-z]/gi, "") || "G" : surfaceSpec(selected).group_prefix);
    const element = `element-${crypto.randomUUID()}`;
    copies.forEach((surface) => { Object.assign(surface.metadata, { group_id: newGroup, element_id: element, surface_id: `surface-${crypto.randomUUID()}`,
      name: group ? String(surface.metadata.name).replace(oldGroup, newGroup) : `${newGroup} ${String(surface.metadata.frontend_surface_type)} 副本` }); });
    insert(copies);
  }
  function applyOptimizationCandidate(changes: Record<string, number>): boolean {
    const updated = clone(request.value);
    let changed = false;
    for (const [path, value] of Object.entries(changes)) {
      if (!Number.isFinite(value)) throw new Error('候选方案包含无效数值。');
      const surface = /^surfaces\[(\d+)\]\.(radius_mm|distance_to_next_mm|semi_aperture_mm|conic)$/.exec(path);
      if (surface) {
        const row = updated.project.surfaces[Number(surface[1])];
        if (!row) throw new Error('候选方案与当前镜头结构不匹配。');
        const field = {radius_mm:'radius',distance_to_next_mm:'thickness',semi_aperture_mm:'aperture',conic:'conic'}[surface[2]] as SurfaceField;
        if (Number(fieldValue(row, field)) === value) continue;
        editSurface(row, field, String(value));
        changed = true;
      } else if (['receiver.axial_offset_z_um','receiver.offset_x_um','receiver.offset_y_um'].includes(path)) {
        const receiver = updated.project.receiver as unknown as Record<string,unknown>,key = path.split('.')[1];
        if (receiver[key] === value) continue;
        receiver[key] = value; changed = true;
      } else throw new Error('候选方案包含不支持的参数。');
    }
    if (!changed) return false;
    normalizeSurfaces(updated.project);
    synchronizeRequest(updated);
    request.value = updated; error.value = ''; return true;
  }
  async function compute(): Promise<void> {
    if (busy.value) return;
    if (!project.value.surfaces.length) { error.value = "请先添加光学表面。"; return; }
    submitting.value = true; error.value = "";
    try {
      await fieldRestoration;
      if (fieldLoading.value) throw new Error("复场正在读取，请稍后开始计算。");
        const signature = calculationSignature();
        const capturedContextId = contextId.value;
      const capturedFrontend = request.value.frontend_state ? clone(projectSettings(request.value).frontend_state!) : undefined;
      const payload = computationRequest(request.value);
      payload.project = await canonicalProject(payload.project);
      payload.project.fingerprint = await fingerprint(payload.project);
      payload.request_id = `sim-${crypto.randomUUID().slice(0, 8)}`;
      const id = await submitSimulation(payload);
      submittedProject.value = signature; activeJobId.value = id; result.value = null;
      submittedSnapshot.value = clone(payload.project);
        submittedRequest.value = {...clone(payload),frontend_state:capturedFrontend};
        submittedContextId.value = capturedContextId;
        localStorage.setItem(JOB_KEY, JSON.stringify({ id, project: signature, snapshot: submittedSnapshot.value, request: projectSettings(submittedRequest.value), contextId: capturedContextId }));
      await jobs.trackSubmittedJob(id, "simulation");
    } catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause); }
    finally { submitting.value = false; }
  }
  async function teachingRequest(requiredAnalyses?:string[]):Promise<typeof request.value>{
    await fieldRestoration;
    if(fieldLoading.value)throw new Error('复场正在读取，请稍后更新教学台。');
    const capturedFrontend = request.value.frontend_state ? clone(projectSettings(request.value).frontend_state!) : undefined;
    const payload=computationRequest(request.value);
    if(requiredAnalyses)payload.options=requestOptions({...request.value,analyses:requiredAnalyses,frontend_state:clone(request.value.frontend_state)});
    payload.project=await canonicalProject(payload.project);
    payload.project.fingerprint=await fingerprint(payload.project);
    payload.frontend_state=capturedFrontend;
    return payload;
  }
  async function teachingEditorProject():Promise<typeof request.value.project>{
    return canonicalProject(clone(project.value));
  }
  async function prepareTeachingRequest(candidate:typeof request.value):Promise<typeof request.value>{
    await fieldRestoration;
    const payload=clone(candidate),hybrid=payload.options.hybrid as Record<string,unknown>|undefined;
    if(payload.project.receiver.mode_model==='imported' && !hybrid?.imported_mode_values){
      const reference=payload.frontend_state?.imported_field_ref;
      if(!reference)throw new Error('教学工程快照缺少复场记录，请从仿真重新计算。');
      const field=await restoreField(reference);
      payload.options.hybrid={...hybrid,imported_mode_values:{real:field.real,imag:field.imag},imported_mode_source:field.path};
    }
    return payload;
  }
  function applyTeachingPublish(changes:Record<string,number>,snapshot:Record<string,unknown>):boolean{
    const updated=clone(request.value),p=updated.project,ui=uiState(updated);let applied=false;
    for(const [path,value] of Object.entries(changes)){
      if(!Number.isFinite(value) || value<=0)throw new Error('教学同步参数无效。');
      if(path==='source.wavelength_nm'){applied ||= p.source.wavelength_nm!==value;p.source.wavelength_nm=value;}
      else if(path==='receiver.mode_field_diameter_x_um'){
        applied ||= p.receiver.mode_field_diameter_x_um!==value;p.receiver.mode_field_diameter_x_um=value;
        ui.fiber_mfd_y_um=p.receiver.mode_field_diameter_y_um;ui.fiber_split=p.receiver.mode_field_diameter_x_um!==p.receiver.mode_field_diameter_y_um;
      }
      else throw new Error('不支持的教学同步参数。');
    }
    ui.research_profile={...ui.research_profile,active_snapshot_source:'teaching',teaching_snapshot:clone(snapshot)};
    // Native ProjectContext changes these two declared fields atomically; it
    // preserves the existing spectral list, weights and numerical options.
    request.value=updated;return applied;
  }
  async function loadResult(id = activeJobId.value): Promise<void> {
    resultLoading.value = true;
    try { const body = await getJobResult<Record<string, unknown>>(id); if (id === activeJobId.value) result.value = body; }
    catch (cause) { if (id === activeJobId.value) error.value = cause instanceof Error ? cause.message : String(cause); }
    finally { if (id === activeJobId.value) resultLoading.value = false; }
  }
  async function projectContents(): Promise<string> {
    await fieldRestoration;
    if (fieldLoading.value) throw new Error("复场正在读取，请稍后保存。");
    // Export embeds the field once so the project can be moved to another machine.
    return JSON.stringify({ ...projectSettings(request.value), frontend_state: request.value.frontend_state }, null,
      request.value.frontend_state?.imported_field ? undefined : 2);
  }
  async function copyProject(): Promise<void> {
    copyStatus.value = '';
    try {
      await fieldRestoration;
      await navigator.clipboard.writeText(JSON.stringify(projectSettings(request.value), null, 2));
      error.value = ''; copyStatus.value = '已复制项目参数。';
    }
    catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause); }
  }
  async function save(): Promise<void> {
    try {
      const contents = await projectContents();
      const signature = fileSignature();
      if (window.opticalDesktop) {
        const saved = await window.opticalDesktop.saveTextFile({ suggestedName: "optical-project.json", contents });
        if (saved.canceled) return;
        savedSignature.value = signature;
      }
      else {
        const url = URL.createObjectURL(new Blob([contents], { type: "application/json" }));
        const anchor = document.createElement("a"); anchor.href = url; anchor.download = "optical-project.json"; anchor.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
      error.value = "";
    } catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause); }
  }
  async function importProject(contents: string): Promise<boolean> {
    if (importing.value || fieldLoading.value) { error.value = '正在读取项目或复场，请稍后再打开。'; return false; }
    importing.value = true; error.value = '';
    const initialRevision = revision.value;
    try {
      await fieldRestoration;
      const candidate = parseProjectFile(contents);
      await apiRequest('/api/v1/simulation/projects/validate', { method: 'POST', body: candidate, timeoutMs: 120000 });
      if (revision.value !== initialRevision) throw new Error('读取期间项目已被修改，请重新打开文件。');
      const state = uiState(candidate);
      // Portable exports embed arrays; compact copies can reuse a matching local cache.
      if (!state.imported_field && state.imported_field_ref) state.imported_field = await restoreField(state.imported_field_ref);
      else if (state.imported_field) state.imported_field_ref = await cacheField(state.imported_field);
      synchronizeRequest(candidate);
      historyApplying = true;
      try {
        request.value = candidate;
        contextId.value = crypto.randomUUID();
        localStorage.setItem(CONTEXT_KEY, contextId.value);
        selectedId.value = candidate.project.surfaces[0] ? surfaceId(candidate.project.surfaces[0]) : '';
        historyPending = false; previousEdits.length = followingEdits.length = 0;
        currentEdit = surfaceEdit(); canUndo.value = canRedo.value = false;
      } finally { historyApplying = false; }
      savedSignature.value = fileSignature(); fieldError.value = ''; return true;
    } catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause); return false; }
    finally { importing.value = false; }
  }
  const teachingSubmittedRequest = computed(() => submittedRequest.value && submittedContextId.value === contextId.value ? submittedRequest.value : null);
  return { request, project, contextId, submittedSnapshot, teachingSubmittedRequest, revision, groups, customMaterials, upsertCustomMaterial, selectedId, selectedIndex, submitting, resultLoading, result, activeJobId, teachingRequest, teachingEditorProject, prepareTeachingRequest, applyTeachingPublish, applyOptimizationCandidate, calculationSignature,
    job, busy, resultStale, error, copyStatus, dirty, importing, canUndo, canRedo, undo, redo, importProject, copyProject, observation, setObservation, fieldLoading, fieldError, importField, rejectField, parameter, setParameter, setAuxiliary, applySettings, change, changeProperty, pasteCells, add, addSpecial, remove, duplicate, compute, loadResult, save };
});
