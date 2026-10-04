<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId } from "vue";
import { numericMetric, type TrainingPlot } from "../domain/training-results.js";
const props = defineProps<{ plot: TrainingPlot; title: string; metrics: Record<string, unknown> }>();
const host = ref<HTMLDivElement>();
const size = ref({ width: 944, height: 460 });
const clipId = useId().replace(/[^\w-]/g, '') + '-plot';
let observer: ResizeObserver | undefined;
onMounted(() => {
  observer = new ResizeObserver(([entry]) => {
    if (entry && entry.contentRect.width > 0 && entry.contentRect.height > 0) size.value = { width: entry.contentRect.width, height: entry.contentRect.height };
  });
  if (host.value) observer.observe(host.value);
});
onBeforeUnmount(() => observer?.disconnect());
const histogramView = computed(() => props.plot.kind === 'histogram');
const residualView = computed(() => props.plot.kind === 'scatter' && props.plot.zeroLine);
const scatterView = computed(() => props.plot.identityLine);
const box = computed(() => ({ left: size.value.width * (histogramView.value ? .14 : .15), top: size.value.height * .14, width: size.value.width * (histogramView.value ? .825 : .815), height: size.value.height * (histogramView.value ? .64 : .62) }));
function mean(values: number[]): number { return values.reduce((sum, value) => sum + value, 0) / (values.length || 1); }
function quantile(values: number[], fraction: number): number {
  const sorted = [...values].sort((a, b) => a - b);
  const index = (sorted.length - 1) * fraction, low = Math.floor(index), high = Math.ceil(index);
  return sorted.length ? sorted[low] + (sorted[high] - sorted[low]) * (index - low) : 0;
}
const residuals = computed(() => props.plot.points.map((p) => histogramView.value ? p.x : scatterView.value ? p.y-p.x : p.y));
const tolerance = computed(() => { const mae = mean(residuals.value.map(Math.abs)); return mae > Number.EPSILON ? 2*mae : Math.max(1, ...residuals.value.map(Math.abs)) * .02; });
function limits(values: number[], padding: number): [number, number] {
  let low = Infinity, high = -Infinity;
  for (const value of values) { low = Math.min(low, value); high = Math.max(high, value); }
  if (!Number.isFinite(low)) return [0,1];
  const pad = high === low ? Math.max(Math.abs(low)*padding, 1) : (high-low)*padding;
  return [low-pad, high+pad];
}
function bins(values: number[], count: number) {
  const [low, high] = limits(values,0), step = (high-low)/count;
  const result = Array.from({length:count}, (_,i) => ({low:low+i*step, high:low+(i+1)*step, count:0}));
  for (const value of values) result[Math.min(count-1,Math.max(0,Math.floor((value-low)/step)))].count++;
  return result;
}
const histogram = computed(() => histogramView.value ? bins(residuals.value,props.plot.bins ?? 12) : []);
const xRange = computed(() => limits(props.plot.points.flatMap((point) => scatterView.value ? [point.x,point.y] : [point.x]), residualView.value || scatterView.value ? .08 : .05));
const yRange = computed<[number,number]>(() => {
  if (histogramView.value) return [0,Math.max(1,...histogram.value.map((bin) => bin.count))*1.05];
  if (scatterView.value) return xRange.value;
  return limits([...props.plot.points.map((point) => point.y), ...(residualView.value ? [-tolerance.value,tolerance.value] : []), ...(props.plot.reference !== undefined ? [props.plot.reference] : [])],residualView.value ? .08 : .05);
});
const x = (value:number) => box.value.left+(value-xRange.value[0])/(xRange.value[1]-xRange.value[0])*box.value.width;
const y = (value:number) => box.value.top+box.value.height-(value-yRange.value[0])/(yRange.value[1]-yRange.value[0])*box.value.height;
function ticks(range:[number,number], count:number) {
  const raw=(range[1]-range[0])/count, power=10**Math.floor(Math.log10(raw));
  const step=([1,2,2.5,5,10].find((value)=>value>=raw/power) ?? 10)*power;
  const start=Math.ceil(range[0]/step)*step;
  return {step,values:Array.from({length:Math.max(0,Math.floor((range[1]-start)/step+1e-8)+1)},(_,i)=>start+i*step)};
}
const xTicks=computed(()=>ticks(xRange.value,histogramView.value || props.plot.kind==='line' ? 9 : 8));
const yTicks=computed(()=>ticks(yRange.value,histogramView.value || props.plot.kind==='line' ? 9 : 8));
function tickText(value:number,step:number):string { const decimals=Math.max(0,-Math.floor(Math.log10(step)))+(Number.isInteger(step*10**Math.max(0,-Math.floor(Math.log10(step)))) ? 0 : 1); return (Math.abs(value)<step*1e-8 ? 0 : value).toFixed(Math.min(6,decimals)); }
const yLabelOffset=computed(()=>26+7.5*Math.max(1,...yTicks.value.values.map(value=>tickText(value,yTicks.value.step).length)));
const linePath=computed(()=>props.plot.points.map((p,i)=>`${i?'L':'M'}${x(p.x)},${y(p.y)}`).join(' '));
const trend=computed(()=>{
  if (!residualView.value || props.plot.points.length<4) return [];
  const sorted=[...props.plot.points].sort((a,b)=>a.x-b.x), count=Math.min(10,Math.max(4,Math.floor(Math.sqrt(sorted.length))));
  const base=Math.floor(sorted.length/count), extra=sorted.length%count;
  let offset=0;
  return Array.from({length:count},(_,i)=>{ const chunk=sorted.slice(offset,offset+base+(i<extra?1:0)); offset+=chunk.length; return {x:quantile(chunk.map(p=>p.x),.5),y:quantile(chunk.map(p=>p.y),.5),low:quantile(chunk.map(p=>p.y),.1),high:quantile(chunk.map(p=>p.y),.9)}; });
});
const trendLine=computed(()=>trend.value.map((p,i)=>`${i?'L':'M'}${x(p.x)},${y(p.y)}`).join(' '));
const trendBand=computed(()=>[...trend.value.map(p=>`${x(p.x)},${y(p.low)}`),...[...trend.value].reverse().map(p=>`${x(p.x)},${y(p.high)}`)].join(' '));
const diagnosticLines=computed(()=>[
  `R²  ${typeof props.metrics.r2==='number' ? props.metrics.r2.toFixed(4) : '—'}`,
  `MAE  ${numericMetric(props.metrics.mae)}`,
  `Bias  ${mean(residuals.value)>=0?'+':''}${numericMetric(mean(residuals.value),3)}`,
  `P95 |e|  ${numericMetric(quantile(residuals.value.map(Math.abs),.95),3)}`,
  `±2×MAE 内  ${Math.round(mean(residuals.value.map(value=>Math.abs(value)<=tolerance.value?1:0))*100)}%`,
]);
const hasOutliers=computed(()=>residuals.value.some(value=>Math.abs(value)>tolerance.value));
const legend=computed(()=> residualView.value ? [{label:'零残差',color:'#475467',dash:'6 4'},{label:'诊断带  ±2×MAE',color:'#155EEF',dash:'1 3'},{label:'测试样本',color:'#155EEF',dot:true},...(hasOutliers.value?[{label:'超出诊断带',color:'#D97706',dot:true}]:[]),{label:'误差趋势',color:'#008547',dot:true,line:true}]
  :scatterView.value ? [{label:'诊断带  ±2×MAE',color:'#E8EFFF',band:true},{label:'理想线  y=x',color:'#475467',dash:'6 4'},{label:'测试样本',color:'#155EEF',dot:true},...(hasOutliers.value?[{label:'超出 ±2×MAE',color:'#D97706',dot:true}]:[])]
  :histogramView.value ? [{label:'零残差',color:'#475467'},{label:`平均值 ${numericMetric(mean(residuals.value))}`,color:'#155EEF'}]
  :[{label:props.plot.yLabel,color:'#155EEF'},...(props.plot.reference!==undefined?[{label:`测试集 RMSE = ${numericMetric(props.plot.reference)}`,color:'#475467',dash:'6 4'}]:[])]);
const legendWidth=computed(()=> props.plot.kind==='line' ? Math.max(props.plot.yLabel.includes('MSE') ? 218 : 201,201+8*Math.max(0,numericMetric(props.plot.reference).length-5)) : histogramView.value ? 140 : 156);
const legendHeight=computed(()=>legend.value.length*22+4);
const legendPosition=computed(()=>{
  const left=box.value.left+5, right=box.value.left+box.value.width-legendWidth.value-5;
  const top=box.value.top+8, bottom=box.value.top+box.value.height-legendHeight.value-5;
  if (residualView.value) return {x:left,y:bottom};
  if (scatterView.value) return {x:right,y:bottom};
  if (props.plot.kind!=='line') return {x:right,y:top};
  const centerY=box.value.top+(box.value.height-legendHeight.value)/2;
  const centerX=box.value.left+(box.value.width-legendWidth.value)/2;
  const candidates=[{x:right,y:top},{x:left,y:top},{x:left,y:bottom},{x:right,y:bottom},{x:right,y:centerY},{x:left,y:centerY},{x:centerX,y:bottom},{x:centerX,y:top},{x:centerX,y:centerY}];
  const score=(position:{x:number;y:number})=>{
    const inside=(px:number,py:number)=>px>=position.x&&px<=position.x+legendWidth.value&&py>=position.y&&py<=position.y+legendHeight.value;
    let overlap=0;
    for(let i=0;i<props.plot.points.length;i++) {
      const point=props.plot.points[i], previous=props.plot.points[Math.max(0,i-1)];
      for(let step=0;step<=8;step++) if(inside(x(previous.x+(point.x-previous.x)*step/8),y(previous.y+(point.y-previous.y)*step/8))) overlap++;
    }
    if(props.plot.reference!==undefined && inside(position.x+legendWidth.value/2,y(props.plot.reference))) overlap+=10;
    return overlap;
  };
  return candidates.reduce((best,candidate)=>score(candidate)<score(best)?candidate:best,candidates[0]);
});
const diagonalBand=computed(()=>`${x(xRange.value[0])},${y(xRange.value[0]-tolerance.value)} ${x(xRange.value[1])},${y(xRange.value[1]-tolerance.value)} ${x(xRange.value[1])},${y(xRange.value[1]+tolerance.value)} ${x(xRange.value[0])},${y(xRange.value[0]+tolerance.value)}`);
const inset=computed(()=>{
  const values=residuals.value, range=limits(limits([...values,-tolerance.value,tolerance.value],.08),.05);
  const sampleSpread=Math.sqrt(values.reduce((sum,v)=>sum+(v-mean(values))**2,0)/Math.max(1,values.length-1));
  const robust=(quantile(values,.75)-quantile(values,.25))/1.349;
  const bandwidth=Math.max(1.06*Math.max(sampleSpread,robust,Number.EPSILON)*values.length**(-.2),Number.EPSILON);
  const curve=Array.from({length:160},(_,i)=>{const value=range[0]+i/159*(range[1]-range[0]);const density=mean(values.map(v=>Math.exp(-.5*((value-v)/bandwidth)**2)))/(bandwidth*Math.sqrt(2*Math.PI));return {value,density};});
  const bars=bins(values,Math.min(18,Math.max(5,Math.floor(Math.sqrt(values.length))+2)));
  const maxDensity=Math.max(...curve.map(p=>p.density),...bars.map(b=>b.count/values.length/(b.high-b.low)))*1.05;
  const b={left:box.value.left+.69*box.value.width,top:box.value.top+.08*box.value.height,width:box.value.width*.28,height:box.value.height*.35};
  const ix=(density:number)=>b.left+density/(maxDensity||1)*b.width, iy=(value:number)=>b.top+b.height-(value-range[0])/(range[1]-range[0])*b.height;
  return {b,range,ix,iy,curve:curve.map((p,i)=>`${i?'L':'M'}${ix(p.density)},${iy(p.value)}`).join(' '),bars:bars.map(bar=>({x:b.left,y:iy(bar.high),width:ix(bar.count/values.length/(bar.high-bar.low))-b.left,height:iy(bar.low)-iy(bar.high)})),ticks:ticks([0,maxDensity],4),yTicks:ticks(range,5)};
});
const metricText=computed(()=> ['r2','mae','rmse','max_absolute_error'].filter(key=>typeof props.metrics[key]==='number').map(key=>`${({r2:'R²',mae:'MAE',rmse:'RMSE',max_absolute_error:'最大|e|'} as Record<string,string>)[key]}=${key==='r2'?(props.metrics[key] as number).toFixed(4):numericMetric(props.metrics[key])}`).join(' '));
const description=computed(()=>props.plot.kind==='line'?(props.plot.description || `数据点：${props.plot.points.length}　｜　横轴：${props.plot.xLabel}　｜　纵轴：${props.plot.yLabel}　｜　数据来源：训练评估`):`${residualView.value?'测试集残差':scatterView.value?'测试集实测值与预测值对照':'测试集残差分布'} 测试样本 ${props.plot.points.length} ${metricText.value}`);
</script>

<template>
  <div class="training-plot">
    <div ref="host" class="training-plot-canvas"><svg :viewBox="`0 0 ${size.width} ${size.height}`" role="img" :aria-label="`${title}。${description}`">
      <defs><clipPath :id="clipId"><rect :x="box.left" :y="box.top" :width="box.width" :height="box.height" /></clipPath></defs>
      <rect :width="size.width" :height="size.height" fill="#F8FAFC" /><rect :x="box.left" :y="box.top" :width="box.width" :height="box.height" fill="white" />
      <text v-if="histogramView" :x="box.left+box.width/2" :y="box.top-10" text-anchor="middle" class="plot-title">测试集残差分布</text>
      <g :clip-path="`url(#${clipId})`">
        <polygon v-if="scatterView" :points="diagonalBand" fill="#155EEF" fill-opacity=".09" />
        <rect v-if="residualView" :x="box.left" :y="y(tolerance)" :width="box.width" :height="y(-tolerance)-y(tolerance)" fill="#155EEF" fill-opacity=".09" />
        <polygon v-if="trend.length" :points="trendBand" fill="#008547" fill-opacity=".12" />
        <g class="plot-grid"><line v-for="tick in yTicks.values" :key="`y${tick}`" :x1="box.left" :x2="box.left+box.width" :y1="y(tick)" :y2="y(tick)"/><line v-for="tick in xTicks.values" :key="`x${tick}`" :x1="x(tick)" :x2="x(tick)" :y1="box.top" :y2="box.top+box.height" /></g>
        <g v-if="residualView"><line :x1="box.left" :x2="box.left+box.width" :y1="y(0)" :y2="y(0)" stroke="#475467" stroke-width="2" stroke-dasharray="6 4"/><line v-for="value in [-tolerance,tolerance]" :key="value" :x1="box.left" :x2="box.left+box.width" :y1="y(value)" :y2="y(value)" stroke="#155EEF" stroke-dasharray="1 3" stroke-width="1.5"/></g>
        <line v-if="scatterView" :x1="box.left" :y1="box.top+box.height" :x2="box.left+box.width" :y2="box.top" stroke="#475467" stroke-width="2" stroke-dasharray="6 4"/>
        <g v-if="histogramView"><rect v-for="(bin,i) in histogram" :key="i" :x="x(bin.low)" :y="y(bin.count)" :width="x(bin.high)-x(bin.low)" :height="y(0)-y(bin.count)" fill="#155EEF" fill-opacity=".78" stroke="white" stroke-width=".7"/><line :x1="x(0)" :x2="x(0)" :y1="box.top" :y2="box.top+box.height" stroke="#475467" stroke-width="1.6"/><line :x1="x(mean(residuals))" :x2="x(mean(residuals))" :y1="box.top" :y2="box.top+box.height" stroke="#155EEF" stroke-width="2.1"/></g>
        <path v-else-if="plot.kind==='line'" :d="linePath" fill="none" stroke="#155EEF" stroke-width="2.4"/>
        <g v-else><circle v-for="(point,i) in plot.points" :key="i" :cx="x(point.x)" :cy="y(point.y)" :r="Math.abs(residuals[i])>tolerance?4.1:3.6" :fill="Math.abs(residuals[i])>tolerance?'#D97706':'#155EEF'" :fill-opacity="Math.abs(residuals[i])>tolerance?.92:.74" stroke="white" stroke-width=".65"><title>{{ plot.xLabel }}：{{ point.x }}；{{ plot.yLabel }}：{{ point.y }}</title></circle></g>
        <path v-if="trend.length" :d="trendLine" fill="none" stroke="#008547" stroke-width="2.4"/><circle v-for="(point,i) in trend" :key="`t${i}`" :cx="x(point.x)" :cy="y(point.y)" r="2.2" fill="#008547" />
        <line v-if="plot.reference!==undefined" :x1="box.left" :x2="box.left+box.width" :y1="y(plot.reference)" :y2="y(plot.reference)" stroke="#475467" stroke-width="1.6" stroke-dasharray="6 4" />
      </g>
      <rect :x="box.left" :y="box.top" :width="box.width" :height="box.height" fill="none" stroke="#111827" stroke-width="1.8" />
      <g class="plot-tick"><g v-for="tick in xTicks.values" :key="tick"><line :x1="x(tick)" :x2="x(tick)" :y1="box.top+box.height" :y2="box.top+box.height+6" stroke="#111827" stroke-width="1.7"/><text :x="x(tick)" :y="box.top+box.height+22" text-anchor="middle">{{ tickText(tick,xTicks.step) }}</text></g><g v-for="tick in yTicks.values" :key="tick"><line :x1="box.left-6" :x2="box.left" :y1="y(tick)" :y2="y(tick)" stroke="#111827" stroke-width="1.7"/><text :x="box.left-12" :y="y(tick)+5" text-anchor="end">{{ tickText(tick,yTicks.step) }}</text></g></g>
      <text :x="box.left+box.width/2" :y="box.top+box.height+46" text-anchor="middle" class="plot-axis-label">{{ plot.xLabel }}</text><text :transform="`translate(${box.left-yLabelOffset} ${box.top+box.height/2}) rotate(-90)`" text-anchor="middle" class="plot-axis-label">{{ plot.yLabel }}</text>
      <g :transform="`translate(${legendPosition.x} ${legendPosition.y})`" class="plot-legend"><rect :width="legendWidth" :height="legendHeight" fill="white" stroke="#111827" stroke-width="1.2" rx="2"/><g v-for="(item,i) in legend" :key="item.label" :transform="`translate(5 ${15+i*22})`"><rect v-if="'band' in item" x="0" y="-7" width="27" height="10" :fill="item.color"/><line v-else-if="!('dot' in item) || 'line' in item" x1="0" x2="27" y1="-3" y2="-3" :stroke="item.color" stroke-width="2" :stroke-dasharray="'dash' in item ? item.dash : undefined"/><circle v-if="'dot' in item" cx="14" cy="-3" r="3.6" :fill="item.color"/><text x="35" y="1">{{ item.label }}</text></g></g>
      <g v-if="residualView" class="plot-diagnostics"><rect :x="box.left+8" :y="box.top" :width="diagnosticLines.at(-1)?.includes('100%') ? 125 : 118" height="104" fill="white" fill-opacity=".94" stroke="#98A2B3" rx="4"/><text v-for="(line,i) in diagnosticLines" :key="line" :x="box.left+14" :y="box.top+20+i*18.5">{{ line }}</text></g>
      <g v-if="residualView" class="plot-inset"><rect :x="inset.b.left" :y="inset.b.top" :width="inset.b.width" :height="inset.b.height" fill="white"/><rect v-for="(bar,i) in inset.bars" :key="i" v-bind="bar" fill="#155EEF" fill-opacity=".28" stroke="white" stroke-width=".6"/><path :d="`${inset.curve} L${inset.b.left},${inset.b.top} L${inset.b.left},${inset.b.top+inset.b.height} Z`" fill="#155EEF" fill-opacity=".1"/><path :d="inset.curve" fill="none" stroke="#155EEF" stroke-width="1.8"/><line v-for="value in [-tolerance,0,tolerance]" :key="value" :x1="inset.b.left" :x2="inset.b.left+inset.b.width" :y1="inset.iy(value)" :y2="inset.iy(value)" :stroke="value===0?'#475467':'#155EEF'" :stroke-dasharray="value===0?'4 2':'1 2'"/><rect :x="inset.b.left" :y="inset.b.top" :width="inset.b.width" :height="inset.b.height" fill="none" stroke="#111827" stroke-width="1.8"/><text :x="inset.b.left+inset.b.width/2" :y="inset.b.top-4" text-anchor="middle" class="plot-inset-title">残差分布</text><text :x="inset.b.left+inset.b.width/2" :y="inset.b.top+inset.b.height+28" text-anchor="middle">密度</text><text v-for="tick in inset.ticks.values" :key="tick" :x="inset.ix(tick)" :y="inset.b.top+inset.b.height+16" text-anchor="middle">{{ tickText(tick,inset.ticks.step) }}</text><text v-for="value in inset.yTicks.values" :key="value" :x="inset.b.left-7" :y="inset.iy(value)+3" text-anchor="end">{{ tickText(value,inset.yTicks.step) }}</text></g>
    </svg></div>
    <p class="training-plot-description">{{ description }}</p>
  </div>
</template>
