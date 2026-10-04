import registry from './surface-registry.json';
import { apiRequest } from '../api/http.js';
import { clone, type ProjectSnapshot, type SurfaceSnapshot } from './simulation-project.js';

export interface ParameterSpec {
  key: string; label: string; kind: string; default: string | number | boolean;
  unit: string; minimum: number; maximum: number; decimals: number; choices: string[]; helper: string;
  column_width: number;
}
export interface SurfaceSpec {
  key: string; name: string; category: string; group_prefix: string;
  disabled_common_fields: string[]; parameters: ParameterSpec[];
}
export const surfaceRegistry = registry as SurfaceSpec[];
export function surfaceSpec(surface: SurfaceSnapshot): SurfaceSpec {
  return surfaceRegistry.find(item => item.key === surface.surface_type) ?? surfaceRegistry.at(-1)!;
}
export function parameters(surface: SurfaceSnapshot): Record<string, unknown> {
  return (surface.metadata.type_parameters ??= {}) as Record<string, unknown>;
}
/** Presentation values lost by the formal sequential-medium/clear-diameter conversion. */
export function editorValues(surface: SurfaceSnapshot): { material: string; semi_aperture_mm: number } {
  return surface.metadata._editor as { material: string; semi_aperture_mm: number }
    ?? { material: surface.material_after, semi_aperture_mm: surface.clear_aperture_mm ?? 1 };
}
export function retainEditorValues(surface: SurfaceSnapshot): void {
  surface.metadata._editor ??= clone(editorValues(surface));
}
export function applySurfaceType(surface: SurfaceSnapshot, key: string, resetParameters = true): void {
  const spec = surfaceRegistry.find(item => item.key === key);
  if (!spec) throw new Error('未知表面类型。');
  retainEditorValues(surface);
  surface.surface_type = key; surface.metadata.frontend_surface_type = spec.name;
  const params = parameters(surface);
  for (const parameter of spec.parameters) if (resetParameters || !(parameter.key in params)) params[parameter.key] = parameter.default;
  if (spec.disabled_common_fields.includes('radius')) surface.radius_mm = null;
  if (spec.disabled_common_fields.includes('material')) {
    editorValues(surface).material = 'AIR'; surface.material_after = 'AIR';
  }
}
export function parameterValue(surface: SurfaceSnapshot, spec: ParameterSpec): string | number | boolean {
  return (parameters(surface)[spec.key] ?? spec.default) as string | number | boolean;
}
export function parseParameter(text: string | boolean, spec: ParameterSpec): string | number | boolean {
  if (spec.kind === 'bool') return typeof text === 'boolean' ? text : !['否','no','false','0','禁用'].includes(text.trim().toLowerCase());
  const raw = String(text).trim();
  if (spec.kind === 'choice' && !spec.choices.includes(raw)) throw new Error('请选择有效的参数值。');
  if (['int','float'].includes(spec.kind)) {
    if (!raw || !Number.isFinite(Number(raw))) throw new Error('请输入有限数值。');
    return Math.max(spec.minimum, Math.min(spec.maximum, spec.kind === 'int' ? Math.trunc(Number(raw)) : Number(raw)));
  }
  return raw;
}
export async function canonicalProject(project: ProjectSnapshot): Promise<ProjectSnapshot> {
  const snapshot = clone(project);
  const response = await apiRequest<{ surfaces: SurfaceSnapshot[] }>('/api/v1/simulation/surfaces/serialize', { method: 'POST', body: snapshot });
  snapshot.surfaces = response.data.surfaces;
  return snapshot;
}
