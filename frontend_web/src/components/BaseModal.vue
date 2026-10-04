<script setup lang="ts">
withDefaults(defineProps<{ open: boolean; title: string; description?: string }>(), {
  description: "",
});
const emit = defineEmits<{ close: []; confirm: [] }>();
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" @click.self="emit('close')">
      <section class="modal-card" role="dialog" aria-modal="true" :aria-label="title">
        <button class="icon-button modal-x" type="button" aria-label="关闭窗口" @click="emit('close')">×</button>
        <div class="modal-eyebrow">确认操作</div>
        <h2>{{ title }}</h2>
        <p>{{ description }}</p>
        <div class="modal-actions">
          <button class="button button-quiet" type="button" @click="emit('close')">取消</button>
          <button class="button button-danger" type="button" @click="emit('confirm')">确认删除</button>
        </div>
      </section>
    </div>
  </Teleport>
</template>
