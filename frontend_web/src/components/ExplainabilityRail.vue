<script setup lang="ts">
import {onMounted} from 'vue';
import {useExplainabilityStore} from '../stores/explainability.js';
import DatasetStateIcon from './DatasetStateIcon.vue';
const explain=useExplainabilityStore();
onMounted(()=>void explain.models.refresh());
</script>
<template>
  <div class="explainability-model-list"><button v-for="model in explain.models.records" :key="model.model_id" title="已训练" @click="explain.selectFromRail(model.model_id)"><span>{{ explain.models.displayName(model) }}</span><span v-if="model.model_id===explain.railSelectedId" class="dataset-selection-check"><DatasetStateIcon /></span></button></div>
  <p v-if="explain.models.error" role="alert" class="explainability-model-error">{{ explain.models.error }}</p>
</template>
