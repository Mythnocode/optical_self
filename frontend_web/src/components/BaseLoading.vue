<script setup lang="ts">
withDefaults(defineProps<{ label?: string; compact?: boolean }>(), {
  label: "正在加载…",
  compact: false,
});
</script>

<template>
  <div class="loading-state" :class="{ compact }" role="status" aria-live="polite">
    <span class="loading-spinner" aria-hidden="true"></span>
    <span>{{ label }}</span>
  </div>
</template>
