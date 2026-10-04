<script setup lang="ts">
import { computed, ref } from 'vue';
import { useMaterialsStore } from '../stores/materials.js';
import { useSimulationStore } from '../stores/simulation.js';
import type { MaterialRecord } from '../domain/materials.js';
import MaterialDialog from './MaterialDialog.vue';
const materials=useMaterialsStore(),simulation=useSimulationStore();
const search=ref(''),selected=ref(''),dialog=ref<{record?:MaterialRecord;edit:boolean}|null>(null);
const records=computed(()=>materials.data.records.filter(record=>!search.value.trim()||record.name.toLowerCase().includes(search.value.trim().toLowerCase())));
function open(record:MaterialRecord){dialog.value={record,edit:record.custom};}
</script>
<template>
  <section class="material-library-document" aria-label="材料库">
    <div class="material-library-tools"><input v-model="search" placeholder="筛选材料…" aria-label="筛选材料" /><button v-if="search" class="material-search-clear" aria-label="清除材料筛选" @click="search=''">×</button><button class="material-new-custom" @click="dialog={edit:true}">自定义材料</button></div>
    <p v-if="materials.error" class="material-library-error" role="alert">{{ materials.error }} <button @click="materials.refresh">重新读取</button></p>
    <div class="material-library-table-scroll"><table class="material-library-table"><colgroup><col /><col class="material-index-col" /><col class="material-wavelength-col" /><col class="material-more-col" /></colgroup><thead><tr><th>材料名</th><th>折射率</th><th>波长</th><th>更多</th></tr></thead><tbody><tr v-for="record in records" :key="record.canonical" :class="{selected:selected===record.canonical}" @click="selected=record.canonical" @dblclick="open(record)"><td :title="record.name">{{ record.name }}</td><td>{{ record.index_text }}</td><td>{{ record.wavelength_text }}</td><td><button @click.stop="open(record)">更多</button></td></tr></tbody></table><p v-if="materials.loading&&!materials.data.records.length" class="material-library-loading">正在读取材料…</p></div>
    <MaterialDialog v-if="dialog" :record="dialog.record" :edit="dialog.edit" @save="simulation.upsertCustomMaterial" @close="dialog=null" />
  </section>
</template>
