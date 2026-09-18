"""Verify a built pydvma release against the two build-time traps.

Run from the repo root after `python -m build --sdist --wheel`:

    python scripts/verify_release.py 2.5.0

Trap 1 — the fat wheel must embed THIS version's UI and engine wheel, and
the bundled app JS must reference that same engine-wheel filename. The
classic failure is a stale gitignored `webui/public/pypi`, which makes a
wheel that boots happily while serving the previous version's app.

Trap 2 — every `pydvma/*.py` must be byte-identical across the working
tree, the engine wheel and the fat wheel.
"""
import hashlib
import pathlib
import re
import sys
import zipfile

version = sys.argv[1] if len(sys.argv) > 1 else None
if not version:
    sys.exit('usage: python scripts/verify_release.py <version>')

fat = pathlib.Path('dist') / f'pydvma-{version}-py3-none-any.whl'
eng = pathlib.Path('webui/public/pypi') / f'pydvma-{version}-py3-none-any.whl'
for p in (fat, eng):
    if not p.exists():
        sys.exit(f'MISSING: {p}')

z = zipfile.ZipFile(fat)
names = z.namelist()
failures = []

embedded = [n.split('/')[-1] for n in names
            if n.startswith('pydvma/_webui/pypi/') and n.endswith('.whl')]
idx = [n for n in names if re.match(r'pydvma/_webui/assets/index-.*\.js$', n)]
js = z.read(idx[0]).decode('utf-8', 'replace') if idx else ''
refs = sorted(set(re.findall(r'pydvma-[0-9][^"\'\s]*\.whl', js)))

print('TRAP 1  embedded engine wheels :', embedded)
print('        bundled app js         :', [n.split('/')[-1] for n in idx])
print('        js references          :', refs)
if f'pydvma-{version}-py3-none-any.whl' not in embedded:
    failures.append('fat wheel does not embed this version\'s engine wheel')
if refs != [f'pydvma-{version}-py3-none-any.whl']:
    failures.append(f'bundled JS references {refs}, not this version')

ez = zipfile.ZipFile(eng)
py = sorted(n for n in names
            if n.startswith('pydvma/') and n.endswith('.py') and '/_webui/' not in n)
bad = []
for n in py:
    h_fat = hashlib.sha256(z.read(n)).hexdigest()
    h_tree = hashlib.sha256(pathlib.Path(n).read_bytes()).hexdigest()
    h_eng = hashlib.sha256(ez.read(n)).hexdigest() if n in ez.namelist() else None
    if not (h_fat == h_tree == h_eng):
        bad.append(n)
print('TRAP 2  pydvma/*.py checked    :', len(py))
print('        mismatches             :', bad or 'none')
if bad:
    failures.append(f'{len(bad)} file(s) differ across tree/engine/fat wheel')

meta = z.read(f'pydvma-{version}.dist-info/METADATA').decode()
declared = re.search(r'^Version: (.+)$', meta, re.M).group(1)
print('        wheel METADATA Version :', declared)
if declared != version:
    failures.append(f'wheel declares {declared}, expected {version}')

print()
if failures:
    print('FAILED:')
    for f in failures:
        print('  -', f)
    sys.exit(1)
print(f'OK - pydvma {version} passes both build traps.')
