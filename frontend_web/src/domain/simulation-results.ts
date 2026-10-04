export type ResultKind = 'ray_layout' | 'layout_3d' | 'spot' | 'coupling' | 'wavefront';
export interface PlotObject { kind: string; z: number; center_x?: number; center_y?: number; radius?: number; width?: number; height?: number; visible?: boolean }
export interface SimulationPlot {
  scene_artists?: Scene3DModel;
  kind: string; message?: string; title?: string; x_label?: string; y_label?: string;
  x?: number[]; y?: number[]; z?: number[][]; contour?: number[][]; contour_level?: number;
  color_map?: string; normalization?: string; equal_aspect?: boolean; airy_radius_um?: number;
  contour_paths?: number[][][];
  scale_label?: string; scale_mode?: string; objects?: PlotObject[];
  rays?: { z: number[]; t?: number[]; y?: number[]; points?: number[][]; role?: string }[];
  surfaces?: { z: number; t_min: number; t_max: number; vertices?: number[][]; surface_index?: number }[];
  x_profiles?: Record<string, number[]>;
  y_profiles?: Record<string, number[]>;
  section_artists?: { surface_segments: number[][][]; surface_colors: string[]; surface_widths: number[]; rim_segments: number[][][]; grouped_rays: Record<string, number[][][]>; scale_visible: boolean };
}
export interface Scene3DPrimitive {
  kind: 'line' | 'line_collection' | 'polygons' | 'text' | 'text_2d';
  order: number; z_order: number; color: number[];
  interactive_hide?: boolean;
  paths?: number[][][]; faces?: number[][][]; edge_color?: number[];
  width?: number; dash?: number[]; surface_id?: string | null;
  hover_text?: string | null;
  point?: number[]; text?: string; size?: number; weight?: string | number;
  horizontal?: string; vertical?: string;
}
export interface Scene3DModel {
  version: number; projection: number[][]; data_view: number[];
  limits: number[][]; box_aspect: number[]; elevation: number; azimuth: number;
  primitives: Scene3DPrimitive[];
}
export interface SimulationPresentation { kind: ResultKind; plot: SimulationPlot; labels: string[]; details: string }
export const emptyLabels: Record<ResultKind, string[]> = {
  ray_layout: ['光线数量：—', '聚焦位置：—'], spot: ['光斑半径：—', '峰值位置：—'],
  coupling: ['系统效率：—', '端面接收效率：—', '总耦合效率：—'],
  wavefront: ['波前 RMS：—', '斯特列尔：—'], layout_3d: ['三维视图'],
};

function percentile(values: number[], fraction: number): number {
  if (!values.length) return 0;
  values.sort((a, b) => a-b);
  // numpy.percentile keeps float32 virtual indices and interpolation for this
  // float32 image buffer; rounding just the final percentile changes edge colors.
  const i = Math.fround((values.length-1)*Math.fround(fraction)), lo = Math.floor(i), hi = Math.ceil(i);
  const gamma = Math.fround(i-lo), difference = Math.fround(values[hi]-values[lo]);
  return gamma < .5 ? Math.fround(values[lo]+Math.fround(difference*gamma))
    : Math.fround(values[hi]-Math.fround(difference*Math.fround(1-gamma)));
}
function roundEven(value: number): number { const lo = Math.floor(value), d = value-lo; return d === .5 ? lo+(lo%2) : Math.round(value); }

/** The original FastHeatmapWidget float32/LUT display policy; no optical calculation. */
export function heatmapPixels(plot: SimulationPlot): ImageData {
  const grid = plot.z ?? [[0]], rows = grid.length, cols = grid[0]?.length || 1;
  const values = Float32Array.from(grid.flat().map(value => value === null ? NaN : value));
  const mode = plot.normalization || 'linear', finite = [...values].filter(Number.isFinite);
  const positive = mode === 'energy' || mode === 'log';
  const usable = positive ? [...values].map(value => Number.isFinite(value) ? Math.max(0,value) : 0) : finite;
  const stride = Math.max(1, Math.floor(usable.length/65536));
  const sample = usable.filter((_,i) => i%stride === 0);
  const lo = positive ? 0 : percentile([...sample], .005);
  let hi = positive ? percentile(sample.filter(value=>value>0),.995) : percentile([...sample],.995);
  if (positive) { let max=0; for(const value of usable) max=Math.max(max,value); hi=Math.max(hi,max*1e-6,1e-12); }
  else if (hi<=lo) hi=lo+1;
  const energy = ['energy','turbo','jet'].includes(plot.color_map || '');
  const phase = ['phase','twilight'].includes(plot.color_map || '');
  const anchors = energy ? [0,.16,.34,.52,.72,.88,1] : [0,.25,.5,.75,1];
  const colors = energy ? [[5,8,72],[0,45,190],[0,190,255],[0,220,90],[255,238,0],[255,65,0],[145,0,0]]
    : phase ? [[48,0,130],[0,185,255],[245,245,40],[245,45,20],[48,0,130]]
      : [[68,1,84],[59,82,139],[33,145,140],[94,201,98],[253,231,37]];
  const lut = Array.from({length:256},(_,index) => {
    const x=index*(1/255), high=Math.max(1,anchors.findIndex(value=>value>=x));
    return colors[high-1].map((value,c)=>Math.floor(value+(colors[high][c]-value)/(anchors[high]-anchors[high-1])*(x-anchors[high-1])));
  });
  const image = new ImageData(cols, rows);
  values.forEach((raw,index) => {
    const value = Number.isFinite(raw) ? raw : 0;
    let scaled: number;
    if (mode==='phase') scaled=Math.fround(Math.fround(Math.fround(Math.atan2(Math.sin(value),Math.cos(value)))+Math.fround(Math.PI))/Math.fround(2*Math.PI));
    else if (positive) scaled=Math.fround(Math.log1p(Math.fround(Math.min(1,Math.max(0,Math.fround(value/Math.fround(hi))))*1000)))/Math.log1p(1000);
    else scaled=Number.isNaN(raw) ? 0 : Math.fround(Math.fround(raw-Math.fround(lo))/Math.fround(hi-lo));
    const rgb=lut[Math.min(255,Math.max(0,roundEven(positive ? scaled*255 : Math.fround(scaled*255))))];
    image.data.set([...rgb,255], index*4);
  });
  return image;
}
