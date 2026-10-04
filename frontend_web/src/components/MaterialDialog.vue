<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import { airNames, type CustomMaterial, type MaterialRecord } from '../domain/materials.js';
const props=defineProps<{record?:MaterialRecord;edit?:boolean}>();
const emit=defineEmits<{close:[];save:[material:CustomMaterial]}>();
const nameInput=ref<HTMLInputElement>(),closeButton=ref<HTMLButtonElement>(),invalid=ref('');
let shell:HTMLElement|null=null, previousInert=false, previousFocus:HTMLElement|null=null;
const draft=ref<Record<string,string|number>>({name:props.record?.name??'',model:props.record?.model??'constant',
  n:props.record?.n||1.5,k:props.record?.k??0,a:props.record?.a||1.5,b_um2:props.record?.b_um2??0,c_um4:props.record?.c_um4??0,
  b1:props.record?.b1??0,b2:props.record?.b2??0,b3:props.record?.b3??0,c1_um2:props.record?.c1_um2??0,c2_um2:props.record?.c2_um2??0,c3_um2:props.record?.c3_um2??0});
const numericText=ref(Object.fromEntries(Object.entries(draft.value).filter(([key])=>!['name','model'].includes(key)).map(([key,value])=>[key,Number(value).toFixed(['n','k'].includes(key)?6:8)])));
const fields=computed(()=>draft.value.model==='constant'?[{key:'n',label:'折射率 n',decimals:6,min:1,max:8},{key:'k',label:'消光系数 k',decimals:6,min:0,max:20}]
  :draft.value.model==='cauchy'?[{key:'a',label:'A',decimals:8,min:0,max:20},{key:'b_um2',label:'B / μm²',decimals:8,min:-1e6,max:1e6},{key:'c_um4',label:'C / μm⁴',decimals:8,min:-1e6,max:1e6}]
  :[1,2,3].flatMap(i=>[{key:`b${i}`,label:`B${i}`,decimals:8,min:-1e6,max:1e6},{key:`c${i}_um2`,label:`C${i} / μm²`,decimals:8,min:-1e6,max:1e6}]));
function commit(event:Event,key:string,min:number,max:number,decimals:number) {
  const input=event.target as HTMLInputElement,value=Number(input.value);
  if(!input.value.trim()||!Number.isFinite(value)||value<min||value>max){invalid.value=`请输入 ${min} 至 ${max} 范围内的数值。`;numericText.value[key]=Number(draft.value[key]).toFixed(decimals);return;}
  draft.value[key]=Number(value.toFixed(decimals));numericText.value[key]=Number(draft.value[key]).toFixed(decimals);invalid.value='';
}
async function focus(event:FocusEvent,key:string) {const input=event.target as HTMLInputElement;numericText.value[key]=String(draft.value[key]);await nextTick();input.select();}
function step(key:string,min:number,max:number,decimals:number,direction:number) {
  draft.value[key]=Number(Math.min(max,Math.max(min,Number(draft.value[key])+direction)).toFixed(decimals));numericText.value[key]=Number(draft.value[key]).toFixed(decimals);invalid.value='';
}
function trapTab(event:KeyboardEvent) {
  const frame=event.currentTarget as HTMLElement,items=Array.from(frame.querySelectorAll<HTMLElement>('button:not(:disabled):not([tabindex="-1"]),input,select'));
  const first=items[0],last=items[items.length-1];
  if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
  else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
}
function save() {
  if(invalid.value)return;
  const name=String(draft.value.name).trim();if(airNames.includes(name.toUpperCase())){emit('close');return;}
  const material:CustomMaterial={name,model:draft.value.model as CustomMaterial['model'],custom:true};
  for(const field of fields.value)(material as unknown as Record<string,unknown>)[field.key]=draft.value[field.key];
  emit('save',material);emit('close');
}
function enter(event:KeyboardEvent){if((event.target as HTMLElement).closest('button'))return;event.preventDefault();(event.target as HTMLElement).blur();if(props.edit)save();else emit('close');}
onMounted(async()=>{previousFocus=document.activeElement as HTMLElement; shell=document.querySelector('.app-shell');if(shell){previousInert=shell.inert;shell.inert=true;}await nextTick();(nameInput.value??closeButton.value)?.focus();});
onBeforeUnmount(()=>{if(shell)shell.inert=previousInert;if(previousFocus?.isConnected)previousFocus.focus();});
</script>
<template>
  <Teleport to="body"><div class="material-dialog-overlay" @keydown.esc="emit('close')">
    <section class="material-dialog-frame" role="dialog" aria-modal="true" :aria-label="edit?'自定义材料':`${record?.name??'材料'} · 详细参数`" @keydown.tab="trapTab">
      <header class="material-dialog-title"><span>{{ edit?'自定义材料':`${record?.name??'材料'} · 详细参数` }}</span><button aria-label="关闭材料窗口" @click="emit('close')">×</button></header>
      <div class="material-dialog-content" :class="{editing:edit}" @keydown.enter="enter">
        <template v-if="edit">
          <div class="material-custom-top"><label for="material-name">材料名</label><input id="material-name" ref="nameInput" v-model="draft.name" aria-label="材料名" /><label for="material-model">模型</label><select id="material-model" v-model="draft.model" aria-label="材料模型"><option value="constant">常数折射率</option><option value="cauchy">Cauchy</option><option value="sellmeier">Sellmeier</option></select></div>
          <div class="material-custom-page" :class="String(draft.model)"><label v-for="field in fields" :key="field.key">{{ field.label }}<span class="material-spin"><input :value="numericText[field.key]" @input="numericText[field.key]=($event.target as HTMLInputElement).value" :aria-label="field.label" role="spinbutton" :aria-valuenow="Number(draft[field.key])" :aria-valuemin="field.min" :aria-valuemax="field.max" inputmode="decimal" @focus="focus($event,field.key)" @blur="commit($event,field.key,field.min,field.max,field.decimals)" @keydown.up.prevent="commit($event,field.key,field.min,field.max,field.decimals);step(field.key,field.min,field.max,field.decimals,1)" @keydown.down.prevent="commit($event,field.key,field.min,field.max,field.decimals);step(field.key,field.min,field.max,field.decimals,-1)" /><span class="material-spin-buttons"><button tabindex="-1" type="button" :aria-label="`增加 ${field.label}`" :disabled="Number(draft[field.key])>=field.max" @click="step(field.key,field.min,field.max,field.decimals,1)"></button><button tabindex="-1" type="button" :aria-label="`减少 ${field.label}`" :disabled="Number(draft[field.key])<=field.min" @click="step(field.key,field.min,field.max,field.decimals,-1)"></button></span></span></label></div>
          <p v-if="invalid" class="material-input-error" role="alert">{{ invalid }}</p>
        </template>
        <dl v-else class="material-detail-pairs" :class="record?.custom?record?.model:''"><template v-for="[label,value] in record?.detail_pairs??[]" :key="label"><dt>{{ label }}</dt><dd>{{ value }}</dd></template></dl>
        <footer class="material-dialog-buttons"><template v-if="edit"><button @click="save">OK</button><button @click="emit('close')">Cancel</button></template><button v-else ref="closeButton" class="material-detail-close" @click="emit('close')">Close</button></footer>
      </div>
    </section>
  </div></Teleport>
</template>


