<script setup lang="ts">
import {onMounted,watch} from 'vue';
import {useParameterExplanationStore} from '../stores/parameter-explanation.js';
import {useSimulationStore} from '../stores/simulation.js';
const explain=useParameterExplanationStore(),simulation=useSimulationStore();
onMounted(()=>{void explain.models.refresh();void explain.refreshVariables();});
watch(()=>simulation.revision,()=>void explain.refreshVariables());
</script>
<template>
  <input v-model="explain.search" class="rail-search" type="search" placeholder="筛选…" aria-label="筛选解释参数"/>
  <div class="optimization-categories"><button v-for="category in ['全部','L1','L2','L3','L4','光纤']" :key="category" :class="{selected:explain.group===category}" @click="explain.group=category">{{ category }}</button></div>
  <div class="explanation-parameter-list" aria-label="解释参数"><div class="explanation-parameter-items"><button v-for="row in explain.filtered" :key="row.path" :title="row.path" :class="{selected:explain.selectedFeature===row.path}" @click="explain.selectedFeature=row.path">{{ row.label }}</button></div></div>
  <p v-if="explain.variableError" role="alert" class="explainability-model-error">{{ explain.variableError }}</p>
</template>
