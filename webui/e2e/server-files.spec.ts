import { test, expect, type Page } from '@playwright/test';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import { fileURLToPath } from 'node:url';

/**
 * The served app's working folder (pydvma.savefolder), end to end.
 *
 * A real `dvma.launch` runs in a spawned Python process whose working
 * directory is a fresh "notebook" folder — exactly what a Jupyter kernel
 * gives a notebook — so the app's working folder must default to it. Then:
 * Save Dataset writes there through the file dialog; a replace is asked
 * first; "Choose location…" saves one file elsewhere WITHOUT moving the
 * working folder; the header pill moves it (and the notebook sees the move);
 * Load Data opens in it; an export goes through the same dialog.
 *
 * Lab feedback, 2026-10: in Edge, Save went straight to Downloads with no
 * choice of where. Gated on BRIDGE_E2E like every spec that spawns Python.
 */

const BRIDGE_E2E = !!process.env.BRIDGE_E2E;
// See bridge.spec.ts: `python3` is the MS-Store stub on Windows.
const PYTHON = process.env.PYDVMA_PYTHON ?? 'python3';
// Port claim: see the list in engine-native.spec.ts.
const PORT = Number(process.env.FILES_PORT ?? 8770);
const ORIGIN = `http://127.0.0.1:${PORT}`;
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const DIST_DIR = path.join(REPO_ROOT, 'webui', 'dist');

// `sys.path` gets the repo so the CHECKOUT's pydvma is imported even though
// the process runs in the temporary notebook folder.
const DRIVER = `
import sys
sys.path.insert(0, sys.argv[4])
from pydvma.session import launch
port, ui_dir, session_dir = int(sys.argv[1]), sys.argv[2], sys.argv[3]
s = launch(open_browser=False, port=port, ui_dir=ui_dir, session_dir=session_dir,
           recover=False)
print('READY', flush=True)
for line in sys.stdin:
    if line.strip() == 'dir':
        print('DIR', s.save_dir, flush=True)
`;

let py: ChildProcessWithoutNullStreams | undefined;
let notebookDir = '';
let sessionDir = '';
let lines: string[] = [];

async function upTo(prefix: string, timeoutMs = 20000): Promise<string> {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const i = lines.findIndex((l) => l.startsWith(prefix));
    if (i >= 0) return lines.splice(0, i + 1)[i];
    await new Promise((r) => setTimeout(r, 50));
  }
  throw new Error(`no ${prefix} line; got: ${lines.join(' | ')}`);
}

/** The notebook's view of the working folder (`session.save_dir`). */
async function notebookSaveDir(): Promise<string> {
  py!.stdin.write('dir\n');
  return (await upTo('DIR ')).slice(4);
}

function waitForPort(port: number, timeoutMs = 20000): Promise<void> {
  const t0 = Date.now();
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const sock = net.connect(port, '127.0.0.1');
      sock.once('connect', () => { sock.destroy(); resolve(); });
      sock.once('error', () => {
        sock.destroy();
        if (Date.now() - t0 > timeoutMs) reject(new Error(`port ${port} never opened`));
        else setTimeout(attempt, 200);
      });
    };
    attempt();
  });
}

const dialog = (page: Page) => page.getByTestId('file-dialog');

/** Open the served app with the fixture loaded and the working folder adopted. */
async function open(page: Page) {
  await page.goto(`${ORIGIN}/?fixture=1`);
  await expect(page.getByTestId('tray-card-0')).toBeVisible({ timeout: 20000 });
  await expect(page.getByTestId('workdir-chip')).toContainText(path.basename(notebookDir),
    { timeout: 20000 });
}

/** Header Save Dataset → dialog; type `name`; optionally browse into `folder`; Save. */
async function saveAs(page: Page, name: string, folder?: string) {
  await page.getByRole('button', { name: 'Save Dataset' }).first().click();
  await expect(dialog(page)).toHaveAttribute('data-mode', 'save');
  if (folder) {
    await page.getByTestId('file-dialog-choose').click();
    await page.getByTestId('file-dialog-folder').filter({ hasText: folder }).click();
    await expect(page.getByTestId('file-dialog-target')).toHaveText(path.join(notebookDir, folder));
  }
  await page.getByTestId('file-dialog-name').fill(name);
  await page.getByTestId('file-dialog-confirm').click();
  await expect(dialog(page)).toHaveCount(0);
}

test.describe('served app: the working folder', () => {
  test.skip(!BRIDGE_E2E, 'set BRIDGE_E2E=1 (needs pydvma + websockets; spawns python3)');
  test.setTimeout(120_000);

  test.beforeAll(async () => {
    if (!BRIDGE_E2E) return;
    notebookDir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'pydvma-notebook-')));
    fs.mkdirSync(path.join(notebookDir, 'sub'));
    sessionDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pydvma-e2e-'));
    lines = [];
    py = spawn(PYTHON, ['-c', DRIVER, String(PORT), DIST_DIR, sessionDir, REPO_ROOT],
      { cwd: notebookDir, stdio: 'pipe' });
    let buf = '';
    py.stdout.on('data', (d: Buffer) => {
      buf += d.toString();
      const parts = buf.split('\n');
      buf = parts.pop() ?? '';
      lines.push(...parts.map((l) => l.trim()).filter(Boolean));
    });
    py.stderr.on('data', (d: Buffer) => process.stderr.write(`[launch] ${d}`));
    await upTo('READY', 30000);
    await waitForPort(PORT);
  });

  test.afterAll(async () => {
    py?.kill();
    for (const d of [notebookDir, sessionDir]) {
      if (d) fs.rmSync(d, { recursive: true, force: true });
    }
  });

  test('defaults to the notebook folder; Save writes there and asks before replacing', async ({ page }) => {
    expect(await notebookSaveDir()).toBe(notebookDir);
    await open(page);

    // The dialog opens on the working folder with a .dvma name proposed.
    await page.getByRole('button', { name: 'Save Dataset' }).first().click();
    await expect(dialog(page)).toBeVisible();
    await expect(page.getByTestId('file-dialog-target')).toHaveText(notebookDir);
    await expect(page.getByTestId('file-dialog-name')).toHaveValue(/^pydvma_.*\.dvma$/);
    await expect(page.getByTestId('file-dialog-nav')).toHaveCount(0);   // collapsed by default
    await page.getByTestId('file-dialog-cancel').click();
    await expect(dialog(page)).toHaveCount(0);

    // Save as "run1" (the extension is put back).
    await saveAs(page, 'run1');
    await expect(page.getByTestId('toast').filter({ hasText: 'Saved' }))
      .toContainText(path.join(notebookDir, 'run1.dvma'));
    const first = fs.statSync(path.join(notebookDir, 'run1.dvma'));
    expect(first.size).toBeGreaterThan(1000);

    // Same name again: the dialog warns, and the browser asks before replacing.
    await page.getByRole('button', { name: 'Save Dataset' }).first().click();
    await page.getByTestId('file-dialog-name').fill('run1');
    await expect(page.getByTestId('file-dialog-replace')).toBeVisible();
    page.once('dialog', (d) => { expect(d.message()).toContain('run1.dvma'); void d.dismiss(); });
    await page.getByTestId('file-dialog-confirm').click();
    await expect(dialog(page)).toHaveCount(0);
    expect(fs.statSync(path.join(notebookDir, 'run1.dvma')).mtimeMs).toBe(first.mtimeMs);
  });

  test('Choose location saves one file elsewhere without moving the working folder', async ({ page }) => {
    await open(page);
    await saveAs(page, 'run2', 'sub');
    // The dialog closes before the server has written the file: wait for the
    // Saved message, as the first test does. Reading the disk at once lost the
    // race mid-suite, and the failed test's closing page then abandoned the
    // write, so the next test found no run2.dvma to load.
    await expect(page.getByTestId('toast').filter({ hasText: 'Saved' }))
      .toContainText(path.join(notebookDir, 'sub', 'run2.dvma'));
    expect(fs.existsSync(path.join(notebookDir, 'sub', 'run2.dvma'))).toBe(true);
    await expect(page.getByTestId('workdir-chip')).toContainText(path.basename(notebookDir));
    expect(await notebookSaveDir()).toBe(notebookDir);

    // The next save opens on the working folder again, not on "sub".
    await page.getByRole('button', { name: 'Save Dataset' }).first().click();
    await expect(page.getByTestId('file-dialog-target')).toHaveText(notebookDir);
    await page.getByTestId('file-dialog-cancel').click();
  });

  test('the name takes typing key by key; Save Figure saves through the same dialog', async ({ page }) => {
    await open(page);
    const nameBox = page.getByTestId('file-dialog-name');

    // Lab report (2026-10-26): each typed letter replaced the one before
    // (the dialog re-selected the name on every keystroke). `fill` sets the
    // whole value at once, so type key by key the way a person does.
    await page.getByRole('button', { name: 'Save Dataset' }).first().click();
    await nameBox.pressSequentially('beam');
    await expect(nameBox).toHaveValue('beam.dvma');
    await page.getByTestId('file-dialog-cancel').click();

    // The top bar's Save Figure opens the same dialog, on the working folder,
    // and stays on the current view (it used to switch to the Export stage).
    await page.getByRole('button', { name: 'Save Figure' }).click();
    await expect(dialog(page)).toHaveAttribute('data-mode', 'save');
    await expect(page.getByTestId('file-dialog-target')).toHaveText(notebookDir);
    await expect(nameBox).toHaveValue(/^pydvma_figure_.*\.png$/);
    await nameBox.pressSequentially('fig1');
    await expect(nameBox).toHaveValue('fig1.png');
    await page.getByTestId('file-dialog-confirm').click();
    await expect(page.getByTestId('toast').filter({ hasText: 'fig1.png' }))
      .toContainText(path.join(notebookDir, 'fig1.png'), { timeout: 20000 });
    expect(fs.readFileSync(path.join(notebookDir, 'fig1.png')).subarray(1, 4).toString()).toBe('PNG');
    await expect(page.getByRole('region', { name: 'Export stage controls' })).toHaveCount(0);

    // A typed .pdf saves a PDF (not fig2.pdf.png).
    await page.getByRole('button', { name: 'Save Figure' }).click();
    await nameBox.fill('fig2.pdf');
    await page.getByTestId('file-dialog-confirm').click();
    await expect(page.getByTestId('toast').filter({ hasText: 'fig2.pdf' }))
      .toContainText(path.join(notebookDir, 'fig2.pdf'), { timeout: 20000 });
    expect(fs.readFileSync(path.join(notebookDir, 'fig2.pdf')).subarray(0, 4).toString()).toBe('%PDF');

    // PNG and PDF both ticked in the Export stage: ONE dialog, two files.
    await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Export' }).click();
    await page.getByRole('checkbox', { name: 'PDF' }).check();
    await page.getByRole('region', { name: 'Export stage controls' })
      .getByRole('button', { name: 'Export', exact: true }).click();
    await nameBox.fill('fig3');
    await page.getByTestId('file-dialog-confirm').click();
    await expect(page.getByTestId('toast').filter({ hasText: 'fig3.pdf' }))
      .toContainText(path.join(notebookDir, 'fig3.png'), { timeout: 20000 });
    await expect(dialog(page)).toHaveCount(0);
    expect(fs.existsSync(path.join(notebookDir, 'fig3.png'))).toBe(true);
    expect(fs.existsSync(path.join(notebookDir, 'fig3.pdf'))).toBe(true);
  });

  test('the pill moves the working folder; Load and Export open there', async ({ page }) => {
    await open(page);
    await page.getByTestId('workdir-chip').click();
    await expect(dialog(page)).toHaveAttribute('data-mode', 'folder');
    await page.getByTestId('file-dialog-folder').filter({ hasText: 'sub' }).click();
    await page.getByTestId('file-dialog-confirm').click();
    await expect(page.getByTestId('workdir-chip')).toContainText('sub');
    expect(await notebookSaveDir()).toBe(path.join(notebookDir, 'sub'));

    // Load Data opens in the working folder, listing what is there.
    await page.getByRole('button', { name: 'Load Data' }).click();
    await expect(dialog(page)).toHaveAttribute('data-mode', 'open');
    await page.getByTestId('file-dialog-file').filter({ hasText: 'run2.dvma' }).click();
    await page.getByTestId('file-dialog-confirm').click();
    await expect(page.getByTestId('tray-card-1')).toBeVisible({ timeout: 20000 });

    // An export goes through the same dialog, into the working folder.
    await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Export' }).click();
    await page.getByRole('button', { name: 'Export CSV' }).click();
    await expect(dialog(page)).toHaveAttribute('data-mode', 'save');
    await expect(page.getByTestId('file-dialog-target')).toHaveText(path.join(notebookDir, 'sub'));
    await page.getByTestId('file-dialog-confirm').click();
    await expect(page.getByTestId('toast').filter({ hasText: 'Exported CSV' })).toBeVisible({ timeout: 30000 });
    expect(fs.readdirSync(path.join(notebookDir, 'sub')).some((f) => f.endsWith('.csv'))).toBe(true);
  });
});
