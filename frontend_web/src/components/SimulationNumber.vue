<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { apiRequest } from '../api/http.js';
const props = withDefaults(defineProps<{ modelValue: number; label: string; unit?: string; min?: number; max?: number; step?: number; integer?: boolean; disabled?: boolean; decimals?: number; spinButtons?: boolean }>(), { min: -Infinity, max: Infinity, step: 1 });
const emit = defineEmits<{ 'update:modelValue': [value: number] }>();
const editing = ref(false), draft = ref(""), invalid = ref(false), parsing = ref(false), modified = ref(false);
const inputElement = ref<HTMLInputElement>();
const propertyWidth = ref(140);
const display = computed(() => props.integer ? String(props.modelValue) : props.modelValue.toFixed(2));
const showUnit = computed(() => !!props.unit && (!props.spinButtons || !editing.value || /^\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?\s*$/i.test(draft.value)));
let generation = 0, disposed = false;
onBeforeUnmount(() => { disposed = true; generation++; });
function fitWidth(): void {
  if (!props.spinButtons || props.integer || !inputElement.value) return;
  const canvas = document.createElement('canvas'), context = canvas.getContext('2d');
  if (!context) return;
  context.font = getComputedStyle(inputElement.value).font;
  const text = `${draft.value}${showUnit.value ? ' ' + props.unit : ''}`;
  propertyWidth.value = Math.max(editing.value ? 78 : 140, Math.min(260, Math.ceil(context.measureText(text).width) + 27));
}
onMounted(fitWidth);
watch([draft, editing], fitWidth, { flush: 'post' });
watch(() => props.modelValue, () => { if (!editing.value) draft.value = display.value; }, { immediate: true });
function focus(event: FocusEvent) {
  generation++; parsing.value = false; editing.value = true; modified.value = false; invalid.value = false;
  draft.value = props.spinButtons ? `${display.value}${props.unit ? ' ' + props.unit : ''}` : String(props.modelValue);
  const input = event.target as HTMLInputElement;
  const scrollArea = input.closest<HTMLElement>('.simulation-properties-body');
  let scrollTop = scrollArea?.scrollTop;
  if (scrollArea && props.spinButtons && input.parentElement) {
    const unscrolledBottom = input.parentElement.getBoundingClientRect().bottom + scrollArea.scrollTop;
    if (unscrolledBottom <= scrollArea.getBoundingClientRect().bottom - 8) scrollTop = 0;
  }
  input.value = draft.value; input.select();
  // Selecting the suffix must not recenter the property page in the browser.
  void nextTick(() => { if (scrollArea && scrollTop !== undefined) scrollArea.scrollTop = scrollTop; });
}
async function commit(token: number): Promise<boolean> {
  if (!modified.value) return true;
  const text = draft.value, initialValue = props.modelValue;
  let value = Number(text);
  if (text.trim() && !Number.isFinite(value)) {
    parsing.value = true;
    try {
      const response = await apiRequest<{ value: number }>('/api/v1/simulation/quantities/parse', { method: 'POST', body: { text, target_unit: props.unit ?? '' } });
      value = response.data.value;
    } catch { value = NaN; }
    finally { if (token === generation) parsing.value = false; }
  }
  if (disposed || token !== generation || props.modelValue !== initialValue) return false;
  invalid.value = !text.trim() || !Number.isFinite(value) || value < props.min || value > props.max || (props.integer && !Number.isInteger(value));
  if (invalid.value) return false;
  emit('update:modelValue', props.decimals === undefined ? value : Number(value.toFixed(props.decimals)));
  modified.value = false; await nextTick(); return true;
}
async function blur() {
  const token = ++generation; editing.value = false;
  await commit(token);
  if (!disposed && token === generation) draft.value = display.value;
}
function step(event: KeyboardEvent) {
  if (!['ArrowUp', 'ArrowDown'].includes(event.key)) return;
  event.preventDefault(); void increment(event.key === 'ArrowUp' ? 1 : -1);
}
async function increment(direction: number) {
  const token = ++generation;
  if (!await commit(token) || disposed || token !== generation) return;
  draft.value = String(Math.max(props.min, Math.min(props.max, props.modelValue + direction * props.step)));
  modified.value = true; await commit(token);
  draft.value = editing.value && props.spinButtons ? `${display.value}${props.unit ? ' ' + props.unit : ''}` : editing.value ? String(props.modelValue) : display.value;
}
function cancel(event: KeyboardEvent): void {
  generation++; modified.value = false; draft.value = display.value;
  (event.target as HTMLInputElement).blur();
}
</script>
<template>
  <span class="simulation-number" :style="spinButtons ? { '--number-chars': draft.length, '--property-number-width': `${propertyWidth}px` } : undefined"><input ref="inputElement" v-model="draft" :aria-busy="parsing || undefined" @input="modified = true" :aria-label="label" :title="invalid ? `请输入 ${min} 至 ${max} 范围内的${integer ? '整数' : '数值'}` : undefined" :aria-invalid="invalid || undefined" :disabled="disabled" inputmode="decimal" @focus="focus" @blur="blur" @keydown="step" @keydown.enter="($event.target as HTMLInputElement).blur()" @keydown.esc="cancel" /><span v-if="showUnit" class="simulation-unit" :data-unit="unit">{{ unit }}</span><span v-if="spinButtons" class="surface-spin-buttons"><button type="button" tabindex="-1" :aria-label="`增加${label}`" :disabled="disabled || modelValue >= max" @mousedown.prevent @click="increment(1)"></button><button type="button" tabindex="-1" :aria-label="`减少${label}`" :disabled="disabled || modelValue <= min" @mousedown.prevent @click="increment(-1)"></button></span><slot /></span>
</template>
