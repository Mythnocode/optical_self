import catalog from './component-catalog.json';

export type AssetAnchor = "output_face" | "input_face" | "center" | "top" | "bottom";

export interface ComponentDefinition {
  label: string;
  asset: string;
  housingMm: readonly [number, number, number];
  anchor: AssetAnchor;
  defaultParams: Record<string, string | number | boolean | null>;
}

export const COMPONENT_CATALOG = catalog as unknown as Record<keyof typeof catalog, ComponentDefinition>;

export type ComponentKind = keyof typeof COMPONENT_CATALOG;

export function isComponentKind(kind: string): kind is ComponentKind {
  return Object.hasOwn(COMPONENT_CATALOG, kind);
}
