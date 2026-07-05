import type { NpyArray } from '../codec/npy';

export type DataKind = 'TimeData' | 'FreqData' | 'CrossSpecData' | 'TfData'
  | 'SonoData' | 'ModalData' | 'MetaData';

/**
 * Persisted UI state per item (Plan 2 persistence, additive to manifest).
 *
 * Stored as a `ui` key on each manifest item entry, alongside `kind`,
 * `arrays`, `meta`, and `settings`. Python's `container.load` ignores
 * unknown manifest keys, so this is backwards-compatible — a `.dvma`
 * written with `ui` opens in older pydvma without error. Conversely,
 * a `.dvma` without `ui` loads fine here (all fields optional).
 *
 * - `channel_labels`: sparse map `{ "0": "hammer", "2": "accel" }`;
 *   keys are channel indices (stringified), values are custom labels.
 *   Missing entries use the default `ch_${i}`.
 * - `analysis`: per-view analysis settings that were active for this
 *   set at save time. Partial — missing keys take `defaults()` on load.
 */
export interface DvmaItemUi {
  channel_labels?: Record<string, string>;
  analysis?: {
    freq?: { window?: string; mode?: 'fft' | 'psd' | 'csd'; nFrames?: number };
    tf?: { chIn?: number; window?: string; averaging?: 'none' | 'within' | 'across'; nFrames?: number };
    sono?: { nFft?: number; dynRangeDb?: number };
  };
}

export interface DvmaItem {
  kind: DataKind;
  arrays: Record<string, NpyArray>;          // e.g. time_axis, time_data
  /** Decoded READ view of the item metadata (manifest tags resolved to
   *  plain strings / numbers / lists). NOTE the write contract: when
   *  `metaRaw` is present, writeDvma serializes `metaRaw` and IGNORES
   *  any direct edits made here — mutate metadata via `setItemMeta`,
   *  which keeps both views consistent. */
  meta: Record<string, unknown>;
  /** Original tagged manifest meta (verbatim), kept so writeDvma can
   *  round-trip `__uuid__` / `__datetime__` / `__array__` / `__float__`
   *  tags losslessly back to python. Present on items read from a
   *  .dvma file. JS-authored items must LEAVE THIS UNSET — their plain
   *  `meta` is written directly (writeDvma finite-checks whichever
   *  view it serializes). Do NOT delete this
   *  wholesale to "apply" `meta` edits: python would then reload the
   *  tagged values (datetime / uuid / ndarray) as plain strings and
   *  lists. Use `setItemMeta` instead. */
  metaRaw?: Record<string, unknown>;
  settings: Record<string, unknown> | null;
  /** Persisted UI state: custom channel labels and per-set analysis
   *  settings. Additive; absent on files written by older pydvma or
   *  before any UI customisation. See `DvmaItemUi`. */
  ui?: DvmaItemUi;
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

/**
 * Set one metadata key on `item`, keeping the decoded `meta` view and
 * the tagged `metaRaw` write view consistent: sets `meta[key]` and,
 * when `metaRaw` is present, `metaRaw[key]` too. `value` must be a
 * plain JSON-safe value (strings, finite numbers, booleans, null,
 * arrays/objects of those) — it is written untagged, which python's
 * _decode_value accepts as-is. Lossless for the edited key; tags on
 * all untouched keys are preserved.
 */
export function setItemMeta(item: DvmaItem, key: string, value: unknown): void {
  if (key === '__proto__') throw new Error('invalid meta key "__proto__"');
  item.meta[key] = value;
  if (item.metaRaw) item.metaRaw[key] = value;
}
