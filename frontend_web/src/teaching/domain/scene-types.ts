import type { ComponentKind } from "./component-catalog.js";

export interface TeachingPose {
  x_mm: number;
  y_mm: number;
  z_mm: number;
  yaw_rad: number;
  pitch_rad: number;
  roll_rad: number;
}

export type ParameterValue = string | number | boolean | null;

export interface TeachingComponent {
  component_id: string;
  kind: ComponentKind;
  label: string;
  enabled: boolean;
  pose: TeachingPose;
  params: Record<string, ParameterValue>;
  category?: string;
  asset_key?: string;
}

export interface TeachingScene {
  schema_version: 2;
  scene_id: string;
  revision: number;
  reference: { axis_height_mm: number; render_units_per_mm: number; [key: string]: unknown };
  baseline_enabled: boolean;
  baseline_x_mm: number;
  components: TeachingComponent[];
  selected_component_id: string | null;
  active_result_revision: number | null;
  results: Record<string, Record<string, unknown>>;
}

export interface TeachingPreview {
  source: 'geometry_preview';
  scene_revision: number;
  rays: { start_teaching_mm: [number, number, number]; end_teaching_mm: [number, number, number]; power_fraction: number }[];
  metrics: Record<string, unknown>;
}

export interface TeachingPrimitive {
  shape: 'ellipse' | 'rect' | 'text';
  bounds: [number, number, number, number];
  fill: number[];
  stroke?: number[] | null;
  width?: number;
  radius?: number;
  text?: string;
  font_size?: number;
}
export interface TeachingCanvasPresentation {
  scale: number;
  scene_bounds: [number, number, number, number];
  fit_bounds: [number, number, number, number];
  board: [number, number, number, number];
  holes: [number, number][];
  components: { component_id: string; x: number; y: number; rotation: number; primitives: TeachingPrimitive[]; selected_primitives: TeachingPrimitive[]; hover_primitives: TeachingPrimitive[] }[];
}
