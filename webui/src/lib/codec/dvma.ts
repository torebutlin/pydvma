// .dvma container codec — zip of manifest.json + arrays/NNNN_field.npy
// members, mirroring pydvma/container.py (format 'dvma-dataset',
// format_version 1). The manifest schema, not any class layout, is the
// contract; python's container.load must accept everything writeDvma emits.
import { unzipSync, zipSync } from 'fflate';
import { parseNpy, serializeNpy, type NpyArray } from './npy';
import type { DataKind, DvmaDataset, DvmaItem } from '../model/dataset';

const FORMAT_NAME = 'dvma-dataset';
const FORMAT_VERSION = 1;

// The seven kinds container.py knows (_KIND_CLASSES). An unknown kind
// means the file was written by a newer pydvma — refuse rather than
// misread, mirroring container.load's ValueError.
const KNOWN_KINDS: ReadonlySet<string> = new Set<DataKind>([
  'TimeData', 'FreqData', 'CrossSpecData', 'TfData',
  'SonoData', 'ModalData', 'MetaData',
]);

/**
 * Decode one tagged manifest value, mirroring container.py _decode_value.
 * Tags: {__uuid__} and {__datetime__} stay as plain strings (JS has no
 * uuid/datetime scalar worth the dependency), {__array__} becomes a
 * (possibly nested) number list, {__float__: 'inf'|'-inf'|'nan'} becomes
 * the non-finite number (unknown tokens throw). Plain dicts and lists
 * decode recursively.
 */
function decodeValue(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(decodeValue);
  if (v && typeof v === 'object') {
    const o = v as Record<string, unknown>;
    if ('__uuid__' in o) return o.__uuid__;             // keep as string
    if ('__datetime__' in o) return o.__datetime__;     // keep as ISO string
    if ('__array__' in o) return decodeValue(o.__array__); // small numeric list
    if ('__float__' in o) {                             // strict-JSON escape hatch
      const f = o.__float__;
      if (f === 'nan') return NaN;
      if (f === 'inf') return Infinity;
      if (f === '-inf') return -Infinity;
      throw new Error(`unknown __float__ token ${JSON.stringify(f)}`);
    }
    const out: Record<string, unknown> = {};
    for (const [k, val] of Object.entries(o)) {
      if (k === '__proto__') continue;                  // prototype-pollution guard
      out[k] = decodeValue(val);
    }
    return out;
  }
  return v;
}

/**
 * Parse a .dvma container (zip bytes) into a DvmaDataset.
 *
 * Each item keeps two views of its metadata: `meta` (tags decoded to
 * plain JS values, for the UI) and `metaRaw` (the manifest entry
 * verbatim, so writeDvma can round-trip uuid/datetime/array/float tags
 * losslessly back to python — see the mutation contract on DvmaItem).
 * `settings` is passed through verbatim (tags included) for the same
 * reason. Rejects non-zip input, missing or invalid manifests, unknown
 * data kinds, and format_versions newer than this reader.
 */
export function readDvma(bytes: Uint8Array): DvmaDataset {
  let files: Record<string, Uint8Array>;
  try {
    files = unzipSync(bytes);
  } catch (e) {
    throw new Error(`not a .dvma container (unzip failed: ${(e as Error).message})`);
  }
  const manifestRaw = files['manifest.json'];
  if (!manifestRaw) throw new Error('no manifest.json — not a .dvma container');
  let manifest: {
    format?: string;
    format_version?: number;
    pydvma_version?: string;
    items?: unknown;
  };
  try {
    manifest = JSON.parse(new TextDecoder().decode(manifestRaw));
  } catch (e) {
    throw new Error(`not a valid .dvma container (manifest.json is not JSON: ${(e as Error).message})`);
  }
  if (manifest.format !== FORMAT_NAME) throw new Error(`unexpected format ${manifest.format}`);
  if (typeof manifest.format_version !== 'number' || manifest.format_version > FORMAT_VERSION)
    throw new Error(`dvma-dataset format_version ${manifest.format_version} is newer than this reader (reads up to ${FORMAT_VERSION})`);
  if (!Array.isArray(manifest.items)) throw new Error('manifest has no items array');
  const items: DvmaItem[] = manifest.items.map((entry: {
    kind: DataKind;
    arrays?: Record<string, string>;
    meta?: Record<string, unknown>;
    settings?: Record<string, unknown> | null;
  }, i: number) => {
    const kind = entry.kind;
    if (!KNOWN_KINDS.has(kind))
      throw new Error(`item ${i} has unknown data kind ${JSON.stringify(kind)} — written by a newer pydvma?`);
    const arrays: Record<string, NpyArray> = {};
    for (const [field, member] of Object.entries(entry.arrays ?? {})) {
      if (!Object.hasOwn(files, member))
        throw new Error(`manifest references missing member ${member}`);
      try {
        arrays[field] = parseNpy(files[member]);
      } catch (e) {
        throw new Error(`while reading ${member} (item ${i}, ${kind}.${field}): ${(e as Error).message}`);
      }
    }
    const metaRaw: Record<string, unknown> = {};
    const meta: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(entry.meta ?? {})) {
      if (k === '__proto__') continue;                  // prototype-pollution guard
      metaRaw[k] = v;
      meta[k] = decodeValue(v);
    }
    return { kind, arrays, meta, metaRaw, settings: entry.settings ?? null };
  });
  return {
    formatVersion: manifest.format_version,
    // absent only in hand-built manifests (container.save always writes
    // it); '' rather than undefined keeps the DvmaDataset type simple
    pydvmaVersion: manifest.pydvma_version ?? '',
    items,
  };
}

/**
 * Serialize a DvmaDataset back to .dvma container bytes.
 *
 * Member naming matches container.save: one running index per ITEM
 * (arrays/0007_time_axis.npy), zero-padded to 4 digits. Metadata is
 * written from `metaRaw` when present (lossless: original tags kept
 * verbatim), falling back to the decoded `meta` for items authored in
 * JS — plain strings/numbers/lists, which python's _decode_value
 * accepts as-is. The manifest must stay strict JSON (python reads it
 * with the default parser), and JSON.stringify silently turns
 * NaN/Infinity into null — so whatever metadata/settings are about to
 * be serialized are ALWAYS finite-checked and rejected rather than
 * corrupted. (Python-written values pass trivially: their manifest
 * came through json.dumps(allow_nan=False) and __float__ tag values
 * are strings; the check catches bare non-finite numbers injected
 * later, e.g. via setItemMeta.)
 */
export function writeDvma(ds: DvmaDataset): Uint8Array {
  const files: Record<string, Uint8Array> = {};
  const manifest = {
    format: FORMAT_NAME, format_version: FORMAT_VERSION,
    pydvma_version: ds.pydvmaVersion, storage: 'npy',
    items: [] as unknown[],
  };
  ds.items.forEach((item, index) => {
    const arrays: Record<string, string> = {};
    for (const [field, arr] of Object.entries(item.arrays)) {
      const member = `arrays/${String(index).padStart(4, '0')}_${field}.npy`;
      files[member] = serializeNpy(arr);
      arrays[field] = member;
    }
    const meta = item.metaRaw ?? item.meta;
    assertFiniteJson(meta, `items[${index}].meta`);
    assertFiniteJson(item.settings, `items[${index}].settings`);  // null-safe
    manifest.items.push({ kind: item.kind, arrays, meta, settings: item.settings });
  });
  files['manifest.json'] = new TextEncoder().encode(JSON.stringify(manifest, null, 1));
  return zipSync(files, { level: 6 });
}

/** Throw if a value about to be JSON.stringify'd contains a bare
 *  non-finite number (which stringify would silently null out). */
function assertFiniteJson(v: unknown, path: string): void {
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) throw new Error(`${path} contains non-finite number ${v}; tag it as {"__float__": ...} in metaRaw`);
    return;
  }
  if (Array.isArray(v)) { v.forEach((x, i) => assertFiniteJson(x, `${path}[${i}]`)); return; }
  if (v && typeof v === 'object') {
    for (const [k, x] of Object.entries(v)) assertFiniteJson(x, `${path}.${k}`);
  }
}
