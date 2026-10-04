import { editorValues, retainEditorValues, surfaceRegistry } from './surface-registry.js';
import legacyDefault from "./default-simulation.json";
import type { CustomMaterial } from './materials.js';

export interface SurfaceSnapshot {
  index: number;
  surface_type: string;
  radius_mm: number | null;
  distance_to_next_mm: number;
  material_before: string;
  material_after: string;
  clear_aperture_mm: number | null;
  conic: number;
  asphere_a2: number;
  asphere_coefficients: number[];
  coating_layers: Array<Record<string, unknown>>;
  mechanical_diameter_mm: number | null;
  enabled: boolean;
  metadata: Record<string, unknown>;
  [key: string]: unknown;
}

export type AnalysisSettings = typeof legacyDefault.project.analysis_settings & Record<string, unknown>;
export type ProjectSnapshot = Omit<typeof legacyDefault.project, "surfaces" | "analysis_settings"> & { surfaces: SurfaceSnapshot[]; analysis_settings: AnalysisSettings };
export interface SimulationUiState {
  research_profile?: Record<string,unknown>;
  custom_materials?: CustomMaterial[];
  source_split: boolean; source_na_split: boolean; fiber_split: boolean; fiber_na_split: boolean;
  source_waist_um: number; source_position_mm: number; source_m2: number;
  source_axes?: Record<string, number>; fiber_mfd_y_um?: number;
  fiber_kind?: string; fiber_model?: string; fiber_core_sm_um?: number; fiber_core_mm_um?: number;
  fiber_tilt_x_urad: number; fiber_tilt_y_urad: number; image_distance_mm: number;
  observation?: { enabled: boolean; mode: string; surface_index: number; offset_mm: number; pitch_um: number; pixels_x: number; pixels_y: number };
  imported_field?: { real: number[][]; imag: number[][]; path: string; shape: number[]; source_format: string; interpretation: string; wavelength_nm?: number };
  imported_field_ref?: { id: string; path: string; shape: number[]; wavelength_nm?: number };
}
export type SimulationRequest = Omit<typeof legacyDefault, "project" | "options"> & {
  schema_version?: string; project: ProjectSnapshot; options: Record<string, unknown>; frontend_state?: SimulationUiState;
};
export type SurfaceField = "name" | "radius" | "thickness" | "material" | "aperture" | "conic" | "a4" | "a6" | "a8" | "normalization";
export const surfaceTypes: Record<string, string> = Object.fromEntries(surfaceRegistry.map(spec => [spec.key, spec.name]));

export function clone<T>(value: T): T { return JSON.parse(JSON.stringify(value)) as T; }
export function defaultRequest(): SimulationRequest { return clone(legacyDefault) as SimulationRequest; }
export function surfaceId(surface: SurfaceSnapshot): string { return String(surface.metadata.surface_id); }
export function surfaceName(surface: SurfaceSnapshot): string { return String(surface.metadata.name || `S${surface.index + 1}`); }
export function fieldValue(surface: SurfaceSnapshot, field: SurfaceField): string | number {
  const values = { name: surfaceName(surface), radius: surface.radius_mm ?? 0, thickness: surface.distance_to_next_mm,
    material: editorValues(surface).material, aperture: editorValues(surface).semi_aperture_mm, conic: surface.conic,
    a4: surface.asphere_coefficients[0] ?? 0, a6: surface.asphere_coefficients[1] ?? 0, a8: surface.asphere_coefficients[2] ?? 0,
    normalization: Number((surface.metadata.type_parameters as Record<string, unknown>)?.normalization_radius_mm ?? 1) };
  return values[field];
}

export function editSurface(surface: SurfaceSnapshot, field: SurfaceField, text: string): void {
  retainEditorValues(surface);
  if (field === "name") { surface.metadata.name = text.trim() || `S${surface.index + 1}`; return; }
  if (field === "material") { surface.material_after = text.trim() || "AIR"; editorValues(surface).material = surface.material_after; return; }
  if (!text.trim()) throw new Error("请输入数值。");
  const value = Number(text);
  if (!Number.isFinite(value)) throw new Error("请输入有限数值。");
  if (field === "thickness" && value < 0) throw new Error("厚度不能小于 0。");
  if (field === "aperture" && value <= 0) throw new Error("半口径必须大于 0。");
  if (field === "radius") surface.radius_mm = Math.abs(value) < 1e-15 ? null : value;
  if (field === "thickness") surface.distance_to_next_mm = value;
  if (field === "aperture") {
    editorValues(surface).semi_aperture_mm = value;
    const params = surface.metadata.type_parameters as Record<string, unknown> | undefined;
    surface.clear_aperture_mm = Number(params?._clear_aperture_mm) > 0 ? Number(params!._clear_aperture_mm) / 2 : value;
  }
  if (field === "conic") surface.conic = value;
  if (field === "normalization") {
    if (value <= 0) throw new Error("归一化半径必须大于 0。");
    surface.metadata.type_parameters = { ...(surface.metadata.type_parameters as object), normalization_radius_mm: value };
  }
  if (["a4", "a6", "a8"].includes(field)) {
    if (Math.abs(value) > 1) throw new Error("非球面系数须在 -1 至 1 之间。");
    const index = ["a4", "a6", "a8"].indexOf(field);
    while (surface.asphere_coefficients.length <= index) surface.asphere_coefficients.push(0);
    surface.asphere_coefficients[index] = value;
    while (surface.asphere_coefficients.length && Math.abs(surface.asphere_coefficients.at(-1)!) < 1e-30) surface.asphere_coefficients.pop();
    surface.metadata.type_parameters = { ...(surface.metadata.type_parameters as object), [field]: value };
    delete (surface.metadata.type_parameters as Record<string, unknown>).asphere_coefficients;
  }
}

/** Rebuild sequential media after insertions, removals and material edits. */
export function normalizeSurfaces(project: ProjectSnapshot): void {
  let medium = "AIR";
  project.surfaces.forEach((surface, index) => {
    retainEditorValues(surface);
    surface.index = index;
    surface.material_after = editorValues(surface).material;
    surface.material_before = medium;
    if (["mirror", "stop", "coordinate_break", "detector"].includes(surface.surface_type)) surface.material_after = medium;
    medium = surface.material_after;
  });
}

export function newSurface(group: string, elementId: string, name: string, radius: number, thickness: number, material: string, aperture = 3): SurfaceSnapshot {
  const surface = clone(defaultRequest().project.surfaces[0]);
  Object.assign(surface, { surface_type: "spherical", radius_mm: radius || null, distance_to_next_mm: thickness,
    material_after: material, clear_aperture_mm: aperture, conic: 0, asphere_coefficients: [], coating_layers: [], mechanical_diameter_mm: 2 * aperture });
  surface.metadata = { name, group_id: group, element_id: elementId, surface_id: `surface-${crypto.randomUUID()}`,
    frontend_surface_type: "球面", coating_preset: "无", note: "", type_parameters: {} };
  return surface;
}

export function lensGroups(project: ProjectSnapshot): SurfaceSnapshot[][] {
  const groups = new Map<string, SurfaceSnapshot[]>();
  for (const surface of project.surfaces) {
    const key = String(surface.metadata.group_id || surface.metadata.element_id || surfaceId(surface));
    const group = groups.get(key) ?? [];
    group.push(surface); groups.set(key, group);
  }
  return [...groups.values()];
}

export function readSavedRequest(text: string): SimulationRequest {
  const request = JSON.parse(text) as SimulationRequest;
  if (request.project?.schema_version !== "2.0" || !Array.isArray(request.project.surfaces) || !Array.isArray(request.analyses)
    || !request.project.source || !request.project.analysis_settings || !request.options) throw new Error("项目文件格式不受支持。");
  const ids = new Set<string>();
  for (const surface of request.project.surfaces) {
    if (!surface.metadata || typeof surface.metadata.surface_id !== 'string' || !surface.metadata.surface_id.trim() || ids.has(surfaceId(surface))
      || !Number.isFinite(surface.distance_to_next_mm) || surface.distance_to_next_mm < 0
      || !(surface.clear_aperture_mm! > 0) || !Number.isFinite(surface.conic)
      || (surface.radius_mm !== null && !Number.isFinite(surface.radius_mm))
      || !Array.isArray(surface.asphere_coefficients) || !surface.asphere_coefficients.every(Number.isFinite)
      || !Array.isArray(surface.coating_layers) || typeof surface.material_after !== "string") throw new Error("项目包含无效表面数据。");
    ids.add(surfaceId(surface));
  }
  return request;
}

/** The JS hash identifies an immutable payload; the engine owns physical computation. */
export async function fingerprint(project: ProjectSnapshot): Promise<string> {
  const snapshot = clone(project);
  delete (snapshot as Partial<ProjectSnapshot>).fingerprint;
  const canonical = (value: unknown): unknown => Array.isArray(value) ? value.map(canonical)
    : value && typeof value === "object" ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, canonical(item)])) : value;
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(canonical(snapshot))));
  return `web-${Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("").slice(0, 16)}`;
}
