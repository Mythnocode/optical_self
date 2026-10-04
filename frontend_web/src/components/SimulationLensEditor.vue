<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import SimulationSurfaceProperties from "./SimulationSurfaceProperties.vue";
import { useSimulationStore } from "../stores/simulation.js";
import { useMaterialsStore } from '../stores/materials.js';
import { fieldValue, surfaceId, surfaceName, surfaceTypes, type SurfaceField, type SurfaceSnapshot } from "../domain/simulation-project.js";

import { surfaceRegistry, surfaceSpec, parameterValue, type ParameterSpec } from '../domain/surface-registry.js';

const simulation = useSimulationStore();
const materials = useMaterialsStore();
const materialChoices = computed(() => [...new Set(['AIR', 'MIRROR', ...materials.data.records.map(record => record.canonical), ...simulation.customMaterials.map(record => record.name)])]);
const menu = ref<"add" | "columns" | "">("");
const showType = ref(true);
const showAperture = ref(true);
const propertiesOpen = ref(false);
const propertyTab = ref(0);
const specialMenu = ref(false);
const edit = ref<{ id: string; field: string; value: string } | null>(null);
const editor = ref<HTMLInputElement | null>(null);
const scroll = ref<HTMLDivElement | null>(null), viewportWidth = ref(0);
let resizeObserver: ResizeObserver | undefined;
onMounted(() => {
  resizeObserver = new ResizeObserver(() => { viewportWidth.value = scroll.value?.clientWidth ?? 0; });
  if (scroll.value) resizeObserver.observe(scroll.value);
});
onUnmounted(() => resizeObserver?.disconnect());
const commonColumns: Array<{ field: string; label: string; className?: string; parameter?: ParameterSpec }> = [
  { field: "name", label: "表面名称", className: "surface-name" },
  { field: "radius", label: "曲率半径 R / mm" }, { field: "thickness", label: "厚度 / mm" },
  { field: "material", label: "材料/介质", className: "surface-name" }, { field: "aperture", label: "半口径 / mm" },
];
const extraParameters = computed(() => {
  const extras = new Map<string,ParameterSpec>();
  for (const surface of simulation.project.surfaces) for (const parameter of surfaceSpec(surface).parameters) if (!extras.has(parameter.key)) extras.set(parameter.key, parameter);
  return [...extras.values()];
});
const hiddenColumns = ref(new Set<number>([8]));
watch(() => extraParameters.value.length, size => {
  const count = 8 + size + 1;
  // QHeaderView retains hidden section indexes when the table grows or shrinks.
  hiddenColumns.value = new Set([...hiddenColumns.value].filter(index => index < count).concat(count - 1));
}, { immediate: true, flush: 'sync' });
const columns = computed(() => [...commonColumns, ...extraParameters.value
  .filter((_, index) => !hiddenColumns.value.has(8 + index))
  .map(parameter => ({ field: parameter.key, className: undefined, label: parameter.unit && !parameter.label.includes(parameter.unit) ? `${parameter.label} / ${parameter.unit}` : parameter.label, parameter }))]);
const extraColumns = computed(() => columns.value.filter(column => column.parameter));
const fixedWidth = computed(() => 72 + (showType.value ? 108 : 0) + 135 + 150 + 110 + (showAperture.value ? 112 : 0)
  + extraColumns.value.reduce((total, column) => total + column.parameter!.column_width, 0));
const nameWidth = computed(() => Math.max(120, viewportWidth.value - fixedWidth.value));
function parameterSpec(field: string): ParameterSpec | undefined { return columns.value.find(column => column.field === field)?.parameter; }

watch(() => simulation.selectedId, () => { edit.value = null; }, { flush: "sync" });
function disabled(surface: SurfaceSnapshot, field: string): boolean {
  const parameter = parameterSpec(field);
  return Boolean(parameter && !surfaceSpec(surface).parameters.some(item => item.key === field));
}
function display(surface: SurfaceSnapshot, field: string): string {
  const parameter = parameterSpec(field);
  if (parameter && disabled(surface, field)) return "未使用";
  const value = parameter ? parameterValue(surface, parameter) : fieldValue(surface, field as SurfaceField);
  if (parameter?.kind === 'bool') return value ? '是' : '否';
  return typeof value === "number" ? parameter?.kind === 'int' ? String(value) : value.toFixed(2) : String(value);
}
async function begin(surface: SurfaceSnapshot, field: string): Promise<void> {
  if (disabled(surface, field)) return;
  simulation.selectedId = surfaceId(surface);
  const parameter = parameterSpec(field);
  edit.value = { id: surfaceId(surface), field, value: parameter ? String(parameterValue(surface, parameter)) : field === "surface_type" ? surfaceTypes[surface.surface_type] : String(fieldValue(surface, field as SurfaceField)) };
  await nextTick(); editor.value?.focus(); editor.value?.select();
}
function commit(): void {
  const pending = edit.value; if (!pending) return;
  if (pending.field === "surface_type") { simulation.changeProperty("surface_type", surfaceRegistry.find(item => item.name === pending.value.trim())?.key ?? "user_defined", false); edit.value = null; }
  else if (parameterSpec(pending.field)) { simulation.changeProperty(pending.field, pending.value); if (!simulation.error) edit.value = null; }
  else if (simulation.change(pending.field as SurfaceField, pending.value)) edit.value = null;
}
function keydown(event: KeyboardEvent, surface: SurfaceSnapshot, field: string): void {
  if (event.target instanceof HTMLInputElement) return;
  if (event.key === "Enter" || event.key === "F2") { event.preventDefault(); void begin(surface, field); }
  else if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
    event.preventDefault();
    const cell = event.currentTarget as HTMLElement, row = cell.parentElement!;
    const rows = [...row.parentElement!.children] as HTMLElement[];
    const cells = [...row.querySelectorAll<HTMLElement>('td[tabindex]')];
    let rowIndex = rows.indexOf(row), column = cells.indexOf(cell);
    if (event.key === 'ArrowUp') rowIndex--;
    if (event.key === 'ArrowDown') rowIndex++;
    if (event.key === 'ArrowLeft') column--;
    if (event.key === 'ArrowRight') column++;
    if (event.key === 'Home') { column = 0; if (event.ctrlKey) rowIndex = 0; }
    if (event.key === 'End') { column = cells.length - 1; if (event.ctrlKey) rowIndex = rows.length - 1; }
    rowIndex = Math.max(0, Math.min(rows.length - 1, rowIndex)); column = Math.max(0, Math.min(cells.length - 1, column));
    simulation.selectedId = surfaceId(simulation.project.surfaces[rowIndex]);
    rows[rowIndex].querySelectorAll<HTMLElement>('td[tabindex]')[column]?.focus();
  } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'c' && !window.getSelection()?.toString()) {
    event.preventDefault();
    const parameter = parameterSpec(field);
    const raw = field === 'surface_type' ? surfaceTypes[surface.surface_type] : parameter ? parameterValue(surface, parameter) : fieldValue(surface, field as SurfaceField);
    void navigator.clipboard.writeText(typeof raw === 'boolean' ? raw ? '是' : '否' : String(raw)).catch(cause => { simulation.error = String(cause); });
  }
}
function paste(event: ClipboardEvent, surface: SurfaceSnapshot, field: string): void {
  if ((event.target as HTMLElement).tagName === 'INPUT') return;
  const text = event.clipboardData?.getData('text/plain'); if (text === undefined) return;
  event.preventDefault();
  const visibleFields = columns.value.filter(column => column.field !== 'aperture' || showAperture.value).flatMap(column => column.field === 'name' && showType.value ? ['name', 'surface_type'] : [column.field]);
  const index = visibleFields.indexOf(field);
  const rows = text.replace(/\r\n?/g, '\n').replace(/\n$/, '').split('\n').map(row => row.split('\t'));
  simulation.pasteCells(surfaceId(surface), visibleFields.slice(index), rows);
}
function action(kind: "lens" | "internal" | "surface" | "duplicate" | "group"): void {
  edit.value = null; menu.value = "";
  if (kind === "duplicate" || kind === "group") simulation.duplicate(kind === "group");
  else simulation.add(kind);
  if (kind === 'surface') { propertyTab.value = 2; propertiesOpen.value = true; }
}
function addSpecial(key: string): void {
  edit.value = null; menu.value = ''; specialMenu.value = false; simulation.addSpecial(key);
  propertyTab.value = 2; propertiesOpen.value = true;
}
</script>

<template>
  <div class="simulation-editor-toolbar" @keydown.esc="menu = ''; edit = null">
    <div class="simulation-menu-host">
      <button type="button" class="simulation-command command-add" :aria-expanded="menu === 'add'" @click="menu = menu === 'add' ? '' : 'add'"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>新增<i>⌄</i></button>
      <div v-if="menu === 'add'" class="simulation-popup" role="menu" aria-label="新增表面">
        <button role="menuitem" @click="action('lens')">新增双面透镜</button>
        <button role="menuitem" @click="action('internal')">插入面到当前元件组</button>
        <button role="menuitem" @click="action('surface')">新增独立表面</button>
        <hr />
        <div class="surface-special-menu" @mouseenter="specialMenu = true" @mouseleave="specialMenu = false">
          <button role="menuitem" aria-haspopup="menu" :aria-expanded="specialMenu" @click="specialMenu = true">新增特殊表面<span>›</span></button>
          <div v-if="specialMenu" class="simulation-popup surface-special-popup" role="menu" aria-label="特殊表面">
            <button v-for="type in surfaceRegistry.filter(item => !['spherical','aspheric','plane'].includes(item.key))" :key="type.key" role="menuitem" @click="addSpecial(type.key)">{{ type.name }}</button>
          </div>
        </div>
        <hr />
        <button role="menuitem" :disabled="simulation.selectedIndex < 0" @click="action('duplicate')">复制当前表面</button>
        <button role="menuitem" :disabled="simulation.selectedIndex < 0" @click="action('group')">复制当前元件组</button>
      </div>
    </div>
    <button type="button" class="simulation-command command-delete" :disabled="simulation.selectedIndex < 0" @click="edit = null; simulation.remove()"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5" /></svg>删除面</button>
    <div class="simulation-menu-host">
      <button type="button" class="simulation-command" :aria-expanded="menu === 'columns'" @click="menu = menu === 'columns' ? '' : 'columns'"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6h13M8 12h13M8 18h13"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/></svg>列设置<i>⌄</i></button>
      <div v-if="menu === 'columns'" class="simulation-popup" aria-label="列设置"><label><input v-model="showType" type="checkbox" />表面类型</label><label><input v-model="showAperture" type="checkbox" />半口径</label></div>
    </div>
    <button type="button" class="simulation-command" :disabled="simulation.selectedIndex < 0" @click="propertiesOpen = true; propertyTab = 0; menu = ''">表面属性…</button>
  </div>
  <datalist id="surface-cell-materials"><option v-for="name in materialChoices" :key="name" :value="name" /></datalist>
  <section class="surface-table-panel" aria-label="镜头数据表">
    <div ref="scroll" class="surface-table-scroll">
      <table class="surface-table" :style="{ width: `${fixedWidth + nameWidth}px` }">
        <colgroup><col class="surface-col-number" /><col :style="{ width: `${nameWidth}px` }" /><col v-if="showType" class="surface-col-type" /><col class="surface-col-radius" /><col class="surface-col-thickness" /><col class="surface-col-material" /><col v-if="showAperture" class="surface-col-aperture" /><col v-for="column in extraColumns" :key="column.field" :style="{ width: `${column.parameter!.column_width}px` }" /></colgroup>
        <thead><tr><th>面号</th><template v-for="column in columns" :key="column.field"><th v-if="column.field !== 'aperture' || showAperture">{{ column.label }}</th><th v-if="column.field === 'name' && showType">表面类型</th></template></tr></thead>
        <tbody>
          <tr v-for="surface in simulation.project.surfaces" :key="surfaceId(surface)" :class="{ selected: simulation.selectedId === surfaceId(surface) }" @click="simulation.selectedId = surfaceId(surface)">
            <td>{{ surface.index + 1 }}</td>
            <template v-for="column in columns" :key="column.field">
              <td v-if="column.field !== 'aperture' || showAperture" :class="[column.className, { unused: column.parameter && disabled(surface, column.field) }]" tabindex="0" :aria-label="`${surfaceName(surface)} ${column.label}`" @dblclick="begin(surface, column.field)" @keydown="keydown($event, surface, column.field)" @paste="paste($event, surface, column.field)">
                <input v-if="edit?.id === surfaceId(surface) && edit.field === column.field" :ref="(element) => { editor = element as HTMLInputElement; }" v-model="edit.value" :list="column.field === 'material' ? 'surface-cell-materials' : undefined" class="surface-cell-editor" :aria-label="`编辑 ${column.label}`" @click.stop @keydown.enter.stop.prevent="commit" @keydown.esc.stop.prevent="edit = null" @blur="commit" />
                <template v-else>{{ display(surface, column.field) }}</template>
              </td>
              <td v-if="column.field === 'name' && showType" tabindex="0" :aria-label="`${surfaceName(surface)} 表面类型`" @dblclick="begin(surface, 'surface_type')" @keydown="keydown($event, surface, 'surface_type')" @paste="paste($event, surface, 'surface_type')">
                <input v-if="edit?.id === surfaceId(surface) && edit.field === 'surface_type'" :ref="element => { editor = element as HTMLInputElement; }" v-model="edit.value" class="surface-cell-editor" aria-label="编辑 表面类型" @click.stop @keydown.enter.stop.prevent="commit" @keydown.esc.stop.prevent="edit = null" @blur="commit" />
                <template v-else>{{ surfaceTypes[surface.surface_type] || surface.surface_type }}</template>
              </td>
            </template>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
  <SimulationSurfaceProperties v-if="propertiesOpen" :initial-tab="propertyTab" @close="propertiesOpen = false" />
</template>
