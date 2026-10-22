import { expect, test } from 'vitest';
import {
  extensionOf, isAbsolutePath, joinPath, serverDir, withExtension, type ServerDirDeps,
} from '../../src/lib/files/workdir';

test('isAbsolutePath knows Windows and POSIX paths', () => {
  expect(isAbsolutePath('C:\\Users\\tb267\\3C6')).toBe(true);
  expect(isAbsolutePath('c:/data')).toBe(true);
  expect(isAbsolutePath('\\\\server\\share')).toBe(true);
  expect(isAbsolutePath('/home/tb267')).toBe(true);
  expect(isAbsolutePath('run1.dvma')).toBe(false);
  expect(isAbsolutePath('sub/run1.dvma')).toBe(false);
});

test('joinPath puts a name in a folder, without doubling the separator', () => {
  expect(joinPath('C:\\Users\\tb267\\3C6', 'run.dvma', '\\')).toBe('C:\\Users\\tb267\\3C6\\run.dvma');
  expect(joinPath('C:\\', 'run.dvma', '\\')).toBe('C:\\run.dvma');
  expect(joinPath('/home/tb267', 'run.dvma', '/')).toBe('/home/tb267/run.dvma');
  expect(joinPath('/', 'run.dvma', '/')).toBe('/run.dvma');
  expect(joinPath('/home/tb267', '/tmp/x.dvma', '/')).toBe('/tmp/x.dvma');   // already absolute
});

test('withExtension and extensionOf keep the file type when the user drops it', () => {
  expect(extensionOf('pydvma_2026-10-22_1430.dvma')).toBe('.dvma');
  expect(extensionOf('noext')).toBe('');
  expect(withExtension('run1', '.dvma')).toBe('run1.dvma');
  expect(withExtension('run1.DVMA', '.dvma')).toBe('run1.DVMA');
  expect(withExtension('fig', '')).toBe('fig');
});

/** A fake server folder: a map of path → bytes, and scripted dialog answers. */
function harness(answers: { save?: string | null; open?: string | null; replace?: boolean }) {
  const disk = new Map<string, Uint8Array>();
  const asked: string[] = [];
  const deps: ServerDirDeps = {
    info: { dir: '/nb', name: 'nb', sep: '/' },
    async save(path, bytes, overwrite) {
      const exists = disk.has(path);
      if (exists && !overwrite) return { path, saved: false, exists: true };
      disk.set(path, bytes);
      return { path, saved: true, exists };
    },
    async read(path) {
      const b = disk.get(path);
      if (!b) throw new Error('no such file');
      return { name: path.split('/').pop()!, bytes: b };
    },
    async askSave(suggested) { asked.push(`save:${suggested}`); return answers.save ?? null; },
    async askOpen() { asked.push('open'); return answers.open ?? null; },
    confirmReplace() { asked.push('replace?'); return answers.replace ?? false; },
  };
  return { dir: serverDir(deps), disk, asked };
}

test('save asks where, then writes there', async () => {
  const h = harness({ save: '/elsewhere/run.dvma' });
  expect(h.dir.kind).toBe('server');
  expect(h.dir.name).toBe('nb');
  expect(h.dir.path).toBe('/nb');
  const where = await h.dir.save('run.dvma', Uint8Array.from([1]));
  expect(where).toBe('/elsewhere/run.dvma');
  expect(h.asked).toEqual(['save:run.dvma']);
  expect(h.disk.has('/elsewhere/run.dvma')).toBe(true);
});

test('a cancelled dialog saves nothing and reports null', async () => {
  const h = harness({ save: null });
  expect(await h.dir.save('run.dvma', Uint8Array.from([1]))).toBeNull();
  expect(h.disk.size).toBe(0);
});

test('an existing file is replaced only when the user agrees', async () => {
  const no = harness({ save: '/nb/run.dvma', replace: false });
  no.disk.set('/nb/run.dvma', Uint8Array.from([9]));
  expect(await no.dir.save('run.dvma', Uint8Array.from([1]))).toBeNull();
  expect(Array.from(no.disk.get('/nb/run.dvma')!)).toEqual([9]);

  const yes = harness({ save: '/nb/run.dvma', replace: true });
  yes.disk.set('/nb/run.dvma', Uint8Array.from([9]));
  expect(await yes.dir.save('run.dvma', Uint8Array.from([1]))).toBe('/nb/run.dvma');
  expect(Array.from(yes.disk.get('/nb/run.dvma')!)).toEqual([1]);
  expect(yes.asked).toEqual(['save:run.dvma', 'replace?']);
});

test('open asks which file and reads it; cancel gives null', async () => {
  const h = harness({ open: '/nb/a.dvma' });
  h.disk.set('/nb/a.dvma', Uint8Array.from([7]));
  const got = await h.dir.open();
  expect(got?.name).toBe('a.dvma');
  expect(Array.from(got!.bytes)).toEqual([7]);
  expect(await harness({ open: null }).dir.open()).toBeNull();
});
