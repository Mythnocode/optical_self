import type { TeachingScene } from './scene-types.js';

export type FormalAnalysis = 'raytrace' | 'spot' | 'field' | 'wavefront' | 'coupling';
export interface TeachingPhysicsResult {
  success: boolean; analysis: FormalAnalysis; scene_revision: number; source: string; status: string;
  metrics: Record<string, unknown>; warnings: string[]; errors: string[]; elapsed_ms: number;
  rays: { start_teaching_mm: [number,number,number]; end_teaching_mm: [number,number,number]; power_fraction: number }[];
  artifacts: Record<string, Record<string, unknown>>;
}
export interface AnalysisPresentation {
  imaging_available: boolean; imaging_summary: string; coupling_pill: string; coupling_detail: string;
  spot: { rings: {radius:number;color:string}[]; caption:string } | null;
}
export function sceneCalculationSignature(scene: TeachingScene): string {
  return JSON.stringify([scene.scene_id,scene.revision,scene.reference,scene.components]);
}
