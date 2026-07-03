// .dvma container codec — zip of manifest.json + arrays/NNNN_field.npy
// members, mirroring pydvma/container.py (format 'dvma-dataset',
// format_version 1). The manifest schema, not any class layout, is the
// contract; python's container.load must accept everything writeDvma emits.
import { unzipSync, zipSync } from 'fflate';
import { parseNpy, serializeNpy, type NpyArray } from './npy';
import type { DataKind, DvmaDataset, DvmaItem } from '../model/dataset';

const FORMAT_NAME = 'dvma-dataset';
const FORMAT_VERSION = 1;

/**
 * Decode one tagged manifest value, mirroring container.py _decode_value.
 * Tags: {__uuid__} and {__datetime__} stay as plain strings (JS has no
 * uuid/datetime scalar worth the dependency), {__array__} becomes a
 * (possibly nested) number list, {__float__: 'inf'|'-inf'|'nan'} becomes
 * the non-finite number. Plain dicts and lists decode recursively.
 */
function decodeValue(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(decodeValue);
  if (v && typeof v === 'object') {
    const o = v as Record<string, unknown>;
    if ('__uuid__' in o) return o.__uuid__;             // keep as string
    if ('__datetime__' in o) return o.__datetime__;     // keep as ISO string
    if ('__array__' in o) return decodeValue(o.__array__); // small numeric list
    if ('__float__' in o) {
      const f = o.__float__ as string;                  // strict-JSON escape hatch
      return f === 'nan' ? NaN : f === 'inf' ? Infinity : -Infinity;
    }
    const out: Record<string, unknown> = {};
    for (const [k, val] of Object.entries(o)) out[k] = decodeValue(val);
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
 * losslessly back to python). `settings` is passed through verbatim
 * (tags included) for the same reason.
 */
export function readDvma(bytes: Uint8Array): DvmaDataset {
  const files = unzipSync(bytes);
  const manifestRaw = files['manifest.json'];
  if (!manifestRaw) throw new Error('no manifest.json — not a .dvma container');
  const manifest = JSON.parse(new TextDecoder().decode(manifestRaw));
  if (manifest.format !== FORMAT_NAME) throw new Error(`unexpected format ${manifest.format}`);
  if (typeof manifest.format_version !== 'number' || manifest.format_version > FORMAT_VERSION)
    throw new Error(`dvma-dataset format_version ${manifest.format_version} is newer than this reader (reads up to ${FORMAT_VERSION})`);
  const items: DvmaItem[] = manifest.items.map((entry: {
    kind: DataKind;
    arrays: Record<string, string>;
    meta?: Record<string, unknown>;
    settings?: Record<string, unknown> | null;
  }) => {
    const arrays: Record<string, NpyArray> = {};
    for (const [field, member] of Object.entries(entry.arrays ?? {})) {
      const raw = files[member];
      if (!raw) throw new Error(`manifest references missing member ${member}`);
      arrays[field] = parseNpy(raw);
    }
    const metaRaw = entry.meta ?? {};
    const meta: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(metaRaw)) meta[k] = decodeValue(v);
    return { kind: entry.kind, arrays, meta, metaRaw, settings: entry.settings ?? null };
  });
  return { formatVersion: manifest.format_version, pydvmaVersion: manifest.pydvma_version, items };
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
 * NaN/Infinity into null — so untagged non-finite floats in a
 * fallback `meta` are rejected here rather than corrupted.
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
    if (item.metaRaw === undefined) assertFiniteJson(meta, `items[${index}].meta`);
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
