<script setup lang="ts">
withDefaults(defineProps<{ message: string; tone?: "info" | "success" | "warning" | "error" }>(), {
  tone: "info",
});
const emit = defineEmits<{ close: [] }>();
</script>

<template>
  <div v-if="message" class="toast" :class="`toast-${tone}`" role="status" aria-live="polite">
    <span class="toast-indicator" aria-hidden="true"></span>
    <span class="toast-message">{{ message }}</span>
    <button class="icon-button toast-close" type="button" aria-label="关闭提示" @click="emit('close')">×</button>
  </div>
</template>
