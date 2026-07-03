import type { NpyArray } from '../codec/npy';

export type DataKind = 'TimeData' | 'FreqData' | 'CrossSpecData' | 'TfData'
  | 'SonoData' | 'ModalData' | 'MetaData';

export interface DvmaItem {
  kind: DataKind;
  arrays: Record<string, NpyArray>;          // e.g. time_axis, time_data
  meta: Record<string, unknown>;             // decoded tagged values
  /** original tagged manifest meta (verbatim), kept so writeDvma can
   *  round-trip uuid/datetime/array/float tags losslessly */
  metaRaw?: Record<string, unknown>;
  settings: Record<string, unknown> | null;
}

export interface DvmaDataset {
  formatVersion: number;
  pydvmaVersion: string;
  items: DvmaItem[];
}

/** number of channels in a TimeData/FreqData/TfData item (2nd dim, or 1) */
export function itemChannels(item: DvmaItem): number {
  const arr = item.arrays.time_data ?? item.arrays.freq_data ?? item.arrays.tf_data;
  return arr && arr.shape.length > 1 ? arr.shape[1] : 1;
}
