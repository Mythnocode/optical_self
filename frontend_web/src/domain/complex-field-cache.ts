import type { SimulationRequest, SimulationUiState } from "./simulation-project.js";

export type ComplexField = NonNullable<SimulationUiState['imported_field']>;
export type ComplexFieldReference = { id: string; path: string; shape: number[]; wavelength_nm?: number };

function retainedFieldIds(): Set<string> {
  const ids = new Set<string>();
  function visit(value: unknown): void {
    if (!value || typeof value !== 'object') return;
    const object = value as Record<string, unknown>;
    const reference = object.imported_field_ref as Partial<ComplexFieldReference> | undefined;
    if (typeof reference?.id === 'string') ids.add(reference.id);
    for (const nested of Object.values(object)) if (nested && typeof nested === 'object') visit(nested);
  }
  for (const key of ['optical.simulation.project.v1', 'optical.simulation.job.v1', 'optical.teaching.engineering.v1', 'optical.teaching.analysis.v1']) {
    try { visit(JSON.parse(localStorage.getItem(key) ?? 'null')); } catch { /* Unreadable records have no retained field. */ }
  }
  return ids;
}

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const opening = indexedDB.open("optical.simulation.fields.v1", 1);
    opening.onupgradeneeded = () => opening.result.createObjectStore("fields");
    opening.onerror = () => reject(opening.error);
    opening.onsuccess = () => resolve(opening.result);
  });
}

export async function cacheField(field: ComplexField): Promise<ComplexFieldReference> {
  const reference = { id: crypto.randomUUID(), path: field.path, shape: [...field.shape], wavelength_nm: field.wavelength_nm };
  const db = await database();
  try {
    const retained = retainedFieldIds(); retained.add(reference.id);
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction("fields", "readwrite");
      const fields = transaction.objectStore("fields");
      // Keep the editor, last submitted request and live Teaching snapshots.
      // Replacing an editor field must not remove a captured calculation's input.
      const scanning = fields.openCursor();
      scanning.onsuccess = () => {
        const cursor = scanning.result;
        if (!cursor) return;
        if (!retained.has((cursor.value as {id:string}).id)) cursor.delete();
        cursor.continue();
      };
      fields.put({ id: reference.id, field: JSON.parse(JSON.stringify(field)) }, reference.id);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error ?? new Error("复场保存已中断。"));
    });
    return reference;
  } finally { db.close(); }
}

export async function restoreField(reference: ComplexFieldReference): Promise<ComplexField> {
  const db = await database();
  try {
    const saved = await new Promise<{ id: string; field: ComplexField } | undefined>((resolve, reject) => {
      const fields = db.transaction("fields").objectStore("fields");
      const reading = fields.get(reference.id);
      reading.onsuccess = () => {
        if (reading.result) { resolve(reading.result); return; }
        // Existing caches used one slot; migrate lazily without losing it.
        const legacy = fields.get('current');
        legacy.onsuccess = () => resolve(legacy.result);
        legacy.onerror = () => reject(legacy.error);
      };
      reading.onerror = () => reject(reading.error);
    });
    if (!saved || saved.id !== reference.id) throw new Error("保存的复场数据不可用，请重新选择复场文件。");
    return saved.field;
  } finally { db.close(); }
}

/** Local settings and result signatures retain the field identity, without its arrays. */
export function projectSettings(request: SimulationRequest): SimulationRequest {
  const ui = request.frontend_state;
  if (!ui?.imported_field_ref) return request;
  const state = { ...ui }; delete state.imported_field;
  const hybrid = request.options.hybrid as Record<string, unknown> | undefined;
  const options = { ...request.options };
  if (hybrid) {
    const compact = { ...hybrid }; delete compact.imported_mode_values;
    options.hybrid = compact;
  }
  return { ...request, frontend_state: state, options };
}
