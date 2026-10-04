import { clone, readSavedRequest, type SimulationRequest } from './simulation-project.js';
import { uiState } from './simulation-options.js';

export const PROJECT_FILE_LIMIT = 64 * 1024 * 1024;

/** Preserve the original request schema and inactive inspector values. */
export function parseProjectFile(contents: string): SimulationRequest {
  if (new TextEncoder().encode(contents).byteLength > PROJECT_FILE_LIMIT) throw new Error('项目文件超过 64 MiB。');
  const candidate = readSavedRequest(contents.replace(/^\uFEFF/, ''));
  if ((candidate.schema_version ?? '1.0') !== '1.0' || !['preview', 'standard', 'high'].includes(candidate.precision)
    || !candidate.analyses.length || !candidate.analyses.every(item => typeof item === 'string')
    || !candidate.project.receiver || typeof candidate.options !== 'object' || Array.isArray(candidate.options)) throw new Error('项目请求格式不受支持。');
  function finite(value: unknown, depth = 0): void {
    if (depth > 40) throw new Error('项目数据嵌套过深。');
    if (typeof value === 'number' && !Number.isFinite(value)) throw new Error('项目包含无效数值。');
    if (value && typeof value === 'object') for (const child of Object.values(value)) finite(child, depth + 1);
  }
  finite(candidate);
  const stored = candidate.frontend_state;
  if (stored && (typeof stored !== 'object' || Array.isArray(stored))) throw new Error('项目界面状态无效。');
  const base = clone(candidate); delete base.frontend_state;
  const defaults = uiState(base);
  if (stored?.source_axes && (Array.isArray(stored.source_axes) || typeof stored.source_axes !== 'object')) throw new Error('项目光源轴参数无效。');
  for (const [key, value] of Object.entries(defaults)) {
    const provided = (stored as unknown as Record<string, unknown> | undefined)?.[key];
    if (provided !== undefined && (typeof provided !== typeof value || (typeof value === 'number' && !Number.isFinite(provided)))) throw new Error(`项目界面参数 ${key} 无效。`);
  }
  candidate.frontend_state = { ...defaults, ...stored, source_axes: { ...defaults.source_axes, ...stored?.source_axes } };
  for (const value of Object.values(candidate.frontend_state.source_axes!)) if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error('项目光源轴参数无效。');
  const ui = candidate.frontend_state;
  if (!(ui.source_waist_um > 0) || !(ui.source_m2 >= 1) || !(ui.fiber_mfd_y_um! > 0)
    || !(ui.fiber_core_sm_um! > 0) || !(ui.fiber_core_mm_um! > 0)
    || !['single_mode_fiber', 'multimode_fiber', 'user_mode'].includes(ui.fiber_kind!)
    || !['gaussian', 'lp01', 'he11', 'imported'].includes(ui.fiber_model!)) throw new Error('项目光源或光纤界面参数无效。');
  return candidate;
}
