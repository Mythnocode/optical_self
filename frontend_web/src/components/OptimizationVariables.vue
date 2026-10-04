<script setup lang="ts">
import {computed} from 'vue';
import {useRouter} from 'vue-router';
import {useOptimizationStore} from '../stores/optimization.js';
import {useSimulationStore} from '../stores/simulation.js';
import {useModelsStore} from '../stores/models.js';
const optimization=useOptimizationStore(),simulation=useSimulationStore(),models=useModelsStore(),router=useRouter(),config=optimization.config;
const objective=computed({get:()=>config.objective==='最小化 RMS 光斑'?'最小化 RMS 光斑':'最大化耦合效率',set:(value:string)=>{config.objective=value;}});
const secondary=computed({get:()=>config.objective==='多目标加权',set:(value:boolean)=>{config.objective=value?'多目标加权':'最大化耦合效率';}});
const current=computed(()=>{const body=(simulation.result?.result??simulation.result) as Record<string,unknown>|null,metrics=body?.metrics as Record<string,unknown>|undefined;const value=metrics?.[objective.value==='最小化 RMS 光斑'?'rms_spot_radius_um':'coupling_efficiency'];return typeof value==='number'&&Number.isFinite(value)?objective.value==='最小化 RMS 光斑'?`${Number(value.toPrecision(4))} μm`:`${(value*100).toFixed(1)}%`:'—';});
async function start(){if(await optimization.start())await router.push('/workbench/optimization/opt_result');}
</script>
<template>
  <div class="optimization-layout">
    <h1>优化</h1>
    <section class="optimization-panel optimization-method-panel" :class="{'has-model-selector':config.evaluation_mode==='surrogate'}"><h2>1. 优化方式</h2>
      <div class="optimization-methods">
        <button class="optimization-method" :class="{selected:config.evaluation_mode==='formal'}" @click="config.evaluation_mode='formal'"><span class="method-radio" :class="{selected:config.evaluation_mode==='formal'}"></span><strong>当前仿真（推荐）</strong><small>基于当前镜头和仿真设置直接搜索。</small></button>
        <button class="optimization-method" :class="{selected:config.evaluation_mode==='surrogate'}" @click="config.evaluation_mode='surrogate'"><span class="method-radio" :class="{selected:config.evaluation_mode==='surrogate'}"></span><strong>训练模型辅助</strong><small>基于已训练的模型快速筛选候选方案。</small></button>
      </div>
      <label v-if="config.evaluation_mode==='surrogate'" class="optimization-model-selector"><span>训练模型</span><select v-model="config.surrogate_model_id" aria-label="优化训练模型"><option v-if="!models.records.length" value="">请先在模型页训练</option><option v-for="model in models.records" :key="model.model_id" :value="model.model_id">{{ model.name||model.model_id }}</option></select></label>
    </section>
    <section class="optimization-panel optimization-goal-panel"><h2>2. 优化目标</h2><div class="optimization-goal-row"><select v-model="objective" aria-label="优化目标"><option value="最大化耦合效率">提高耦合效率</option><option value="最小化 RMS 光斑">减小 RMS 光斑</option></select><span class="optimization-current-value"><span class="optimization-current-card"><small>当前值</small><strong>{{ current }}</strong></span></span><label class="optimization-rms-option"><input v-model="secondary" type="checkbox" />同时减小 RMS 光斑</label></div></section>
    <section class="optimization-panel optimization-range-panel"><h2>3. 参数范围</h2><div class="optimization-range-table"><table><colgroup><col v-if="optimization.rows.length" class="optimization-row-number-column" /><col v-for="i in 4" :key="i" /></colgroup><thead><tr><th v-if="optimization.rows.length" class="optimization-row-number"></th><th>参数</th><th>当前值</th><th>最小值</th><th>最大值</th></tr></thead><tbody><tr v-for="(row,index) in optimization.rows"  :key="row.path"><th class="optimization-row-number">{{ index+1 }}</th><td><input v-model="row.label" :aria-label="`${row.path} 参数`" /></td><td><input v-model="row.current" :aria-label="`${row.path} 当前值`" /></td><td><input v-model="row.lower" :aria-label="`${row.path} 最小值`" /></td><td><input v-model="row.upper" :aria-label="`${row.path} 最大值`" /></td></tr></tbody></table></div></section>
    <p v-if="optimization.error" class="optimization-error" role="alert">{{ optimization.error }}</p>
    <button class="optimization-start-button" :disabled="!optimization.selected.length||optimization.busy||optimization.loading" :title="!optimization.selected.length?'请先在左栏勾选优化变量。':''" @click="start">开始优化</button>
  </div>
</template>
