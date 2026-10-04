<script setup lang="ts">
import { computed, ref, watch } from 'vue';
const props = defineProps<{ modelValue: number; label: string; min: number; max: number; decimals: number; disabled?: boolean; suffix?: string }>();
const emit = defineEmits<{ 'update:modelValue': [number] }>();
const input = ref<HTMLInputElement>(), modified = ref(false);
const display = computed(() => props.modelValue.toFixed(props.decimals) + (props.suffix ?? ''));
const draft = ref(display.value);
watch(display, value => { if (!modified.value) draft.value = value; });
function commit(): void {
  if (!modified.value) return;
  const raw = numericDraft();
  const value = Number(raw);
  if (raw && Number.isFinite(value)) emit('update:modelValue', Math.max(props.min, Math.min(props.max, Number(value.toFixed(props.decimals)))));
  modified.value = false; draft.value = display.value;
}
function increment(direction: number): void {
  const current = modified.value && numericDraft() && Number.isFinite(Number(numericDraft())) ? Number(numericDraft()) : props.modelValue;
  const value = Math.max(props.min, Math.min(props.max, current + direction));
  modified.value = false; draft.value = value.toFixed(props.decimals) + (props.suffix ?? ''); emit('update:modelValue', value);
}
function numericDraft(): string { const value = draft.value.trim(); return props.suffix && value.endsWith(props.suffix.trim()) ? value.slice(0, -props.suffix.trim().length).trim() : value; }
function cancel(): void { modified.value = false; draft.value = display.value; input.value?.blur(); }
</script>
<template>
  <span class="teaching-number"><input ref="input" v-model="draft" :aria-label="label" inputmode="decimal" :disabled="disabled" @input="modified = true" @focus="input?.select()" @blur="commit" @keydown.enter="input?.blur()" @keydown.esc="cancel" @keydown.up.prevent="increment(1)" @keydown.down.prevent="increment(-1)" /><span class="teaching-spin-buttons"><button tabindex="-1" :aria-label="`增加${label}`" :disabled="disabled || modelValue >= max" @mousedown.prevent @click="increment(1)"></button><button tabindex="-1" :aria-label="`减少${label}`" :disabled="disabled || modelValue <= min" @mousedown.prevent @click="increment(-1)"></button></span></span>
</template>
