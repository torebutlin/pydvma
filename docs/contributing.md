# Contributing to pydvma

Contributions to this project are welcomed! This page provides guidelines for contributing.

## Project Goals

Keep in mind the project aims:

- Simple to use
- Simple to maintain
- Modular architecture
- Work well with Jupyter notebooks
- Suitable for teaching and research

## Reporting Issues

If you find a bug:

1. Check if it's already reported in [GitHub Issues](https://github.com/torebutlin/pydvma/issues)
2. If not, create a new issue with:
   - Clear description of the problem
   - Steps to reproduce
   - Expected vs actual behavior
   - Your environment (OS, Python version, pydvma version)

## Contributing Code

### Bug Fixes and Refinements

For bug fixes and small improvements:

1. Fork the repository
2. Create a branch for your changes
3. Make your changes with clear commit messages
4. Test your changes
5. Create a pull request with a clear description

### Significant Contributions

For larger changes or new features:

1. Open an issue to discuss your proposal first
2. Wait for feedback before starting work
3. Follow the same process as above once approved

## Repository Map

| Path | What it holds |
| ---- | ------------- |
| `pydvma/` | The Python package: `acquisition`, `streams`, `options` (`MySettings`), `analysis`, `modal`, `datastructure`, `file` and `container` (the `.dvma` format), `plotting`, `devices`, `verify`, `testdata`. |
| `pydvma/serve.py`, `engine.py`, `engine_host.py`, `session.py`, `journal.py` | The local bridge behind `pydvma-serve`, the compute operations shared by the browser and the native engine, and `dvma.launch` with its session journal. |
| `webui/` | The web logger: Svelte and TypeScript on Vite. `src/` is the app, `tests/` the vitest suites, `e2e/` the Playwright specs, `scripts/` the vendoring scripts. |
| `tests/` | The pytest suites. |
| `docs/` | This site (MkDocs Material). `docs/api/` pulls docstrings from the source with mkdocstrings. |
| `lite/` | The JupyterLite notebook served at `/lite/`. |
| `scripts/` | Release helpers: `stage_webui.py` and `verify_release.py`. |
| `dev/` | Design notes, hardware check scripts and per-round lab write-ups. |
| `TODO.md`, `CHANGELOG.md` | The roadmap, and the release notes. Add a line under `## Unreleased` in the changelog for any user-visible change. |

`pydvma/_webui/` is a staged copy of the built web app. It is
git-ignored and produced by `scripts/stage_webui.py`; never edit it.

## Development Setup

pydvma needs Python 3.11 or later. The web app needs Node 22.

```bash
git clone https://github.com/torebutlin/pydvma.git
cd pydvma
pip install -e ".[serve,soundcard]"
pip install pytest
```

Use `".[full]"` instead if you also have National Instruments hardware
and `nidaqmx`. The documentation and the web app have their own
dependencies, installed in the sections below.

## Code Style

- Follow PEP 8 guidelines (no linter is enforced)
- Use meaningful variable names
- Write a docstring for every new public function, method and class,
  following the [Docstring Style Guide](contributing-docstrings.md)
- Comment complex logic
- Keep functions focused and modular

## Testing

Every behaviour change should come with a test, or a reason for none.
Run the checks below before you push. **CI runs only the web app checks
and the strict docs build; it does not run pytest.**

### Python

```bash
python -m pytest
```

The tests are in `tests/`. Tests that need a live National Instruments
device skip themselves when `nidaqmx` or the device is absent. To select
the no-hardware subset explicitly:

```bash
python -m pytest -m "not hardware"
```

A few tests need `sounddevice` and `websockets`. Install the
`soundcard` and `serve` extras as shown above, or expect those tests to
fail or skip.

### Web app

Run these from `webui/`, not from the repository root: Playwright run at
the root reports a spurious duplicate-test error.

```bash
cd webui
npm ci
npm run check
npx vitest run
```

`npm run check` is svelte-check plus `tsc` and must report 0 errors and
0 warnings. The end-to-end specs need the vendored pyodide runtime and
the engine wheel, so run `npm run vendor` first (again after any change
to `pydvma/*.py`, which the engine wheel carries). CI runs the specs in
two passes, because the `@engine` specs boot pyodide, fetch numpy and
scipy from the pyodide CDN, and must run one at a time:

```bash
npm run vendor
npx playwright install chromium
npx playwright test --grep-invert @engine
npx playwright test --grep @engine --workers=1
```

The specs that drive a real `pydvma-serve` process are off by default,
and CI leaves them off. Set `BRIDGE_E2E=1` to include them in either
pass:

```bash
BRIDGE_E2E=1 npx playwright test --grep-invert @engine
BRIDGE_E2E=1 npx playwright test --grep @engine --workers=1
```

A change to a file format (the CSV or MATLAB exports, the `.dvma`
container) must pass the Playwright specs as well as vitest: the layout
is pinned in both.

## Documentation

Update documentation when adding features:

- Write docstrings for new public functions
- Update the relevant user guide page
- Add examples if appropriate
- **Add a `::: pydvma.module.name` line to the matching page in
  `docs/api/`.** The API pages list their entries by hand, so a new
  public function does not appear until you add it.
- Add a new page to the `nav:` section of `mkdocs.yml`

Preview and check the site from the repository root. mkdocstrings
imports `pydvma`, so keep the editable install from above:

```bash
pip install mkdocs-material "mkdocstrings[python]" pymdown-extensions
python -m mkdocs serve
```

Before you push, run the same strict build CI runs on every pull
request. It fails on a broken link and on a docstring the parser cannot
read:

```bash
python -m mkdocs build --strict
```

`requirements-docs.txt` lists these packages plus the JupyterLite tools
that the published site build also needs.

## Building a release wheel

The published wheel carries the built web app (in `pydvma/_webui`) and,
inside that, a lean "engine" wheel that the browser loads. Both are
build artefacts that git ignores, so a wheel built without refreshing
them boots happily while serving an out-of-date app. Build in this
order, on the machine that makes the release. First fetch pyodide and
build the engine wheel for this version:

```bash
cd webui && npm ci && npm run vendor && cd ..
```

Then build the app and copy it into `pydvma/_webui`:

```bash
python scripts/stage_webui.py
```

Then build both artefacts. Give both flags: a bare `python -m build`
makes the wheel from the sdist, which leaves the app out.

```bash
python -m build --sdist --wheel
```

Then check the result with `python scripts/verify_release.py <version>`:
the wheel must embed the engine wheel for this version, the bundled app
must name that same file, and every `pydvma/*.py` must match the source
tree. A version bump touches five places: `pyproject.toml`,
`pydvma/datastructure.py`, `CITATION.cff`, `CHANGELOG.md` and
`ENGINE_WHEELS` in `webui/src/lib/stores/engine.ts`. Test a release by
installing the built wheel into a clean virtual environment, never from
the editable checkout.

## Pull Request Guidelines

A good pull request:

- Has a clear title and description
- Explains what changed and why
- References related issues
- Includes tests if applicable, and passes the checks under
  [Testing](#testing)
- Updates documentation if needed, and builds cleanly with
  `python -m mkdocs build --strict`
- Keeps changes focused on one topic

## Questions?

If you have questions about contributing, open an issue or contact the maintainers.

## License

By contributing, you agree that your contributions will be licensed under the BSD 3-Clause License.
