<script setup lang="ts">
defineProps<{ failed?: boolean }>();
</script>
<template>
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" :stroke-width="failed?1.8:2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="failed?'M6 6l12 12M18 6L6 18':'M5 12l4 4L19 6'" /></svg>
</template>
