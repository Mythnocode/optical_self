export interface CustomMaterial {
  name: string; model: 'constant' | 'cauchy' | 'sellmeier'; custom: boolean;
  n?: number; k?: number; a?: number; b_um2?: number; c_um4?: number;
  b1?: number; b2?: number; b3?: number; c1_um2?: number; c2_um2?: number; c3_um2?: number;
}
export interface MaterialRecord extends Omit<CustomMaterial,'n'|'model'> {
  n?: number | null; model?: CustomMaterial['model'];
  canonical: string; wavelength_nm: number; source?: string; type?: string;
  index_text: string; wavelength_text: string; detail_pairs: [string,string][];
}
export interface MaterialLibrary { records: MaterialRecord[]; used: MaterialRecord[] }
export const airNames = ['', 'AIR', 'VACUUM', 'NONE', '真空'];
