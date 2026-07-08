# JOSS paper — draft & submission checklist

This directory holds a **draft** [Journal of Open Source Software
(JOSS)](https://joss.theoj.org/) paper for pydvma:

- `paper.md` — the paper itself (JOSS Markdown + YAML frontmatter).
- `paper.bib` — the bibliography (BibTeX).

**Nothing here has been submitted.** This is groundwork for Tore to
review, finish, and submit when ready. JOSS papers are short (a summary
plus a statement of need — the current draft is ~640 words of body
text) and describe software that is already released and open.

## What needs Tore before submission

### 1. ORCID (required)

Both `paper.md` (the `orcid:` field) and `CITATION.cff` (a commented
`orcid:` line) contain a flagged placeholder `0000-0000-0000-0000`.
Replace both with your real ORCID (register free at
<https://orcid.org/> if you don't have one). JOSS requires a valid ORCID
for the submitting author.

### 2. Zenodo release DOI (required)

JOSS requires an archived, versioned release with a DOI. Enable the
GitHub–Zenodo integration and cut a release:

- **Connect the repo:** sign in at <https://zenodo.org/> with GitHub,
  open *Account → GitHub*, and toggle the `torebutlin/pydvma` switch to
  **On**. (Zenodo then watches the repo for new releases.)
- **Cut a GitHub release:** tag and publish a release (e.g. `v2.0.0`) on
  GitHub. Zenodo automatically archives that tag and mints a DOI; the
  *concept DOI* (the one ending in the lowest number) always resolves to
  the latest version and is the one to cite.
- **Record the DOI:** add it to `CITATION.cff` (uncomment the `doi:` /
  `identifiers:` block), to the JOSS submission form, and mention it on
  the docs [Support & citation page](../docs/about/support.md).

### 3. Submit to JOSS

Submit at **<https://joss.theoj.org/papers/new>**: point it at the
GitHub repo, the release version, and the archive (Zenodo) DOI. Review
happens openly on GitHub. Full author guidance:
<https://joss.readthedocs.io/en/latest/submitting.html>.

## What reviewers will check (already in good shape)

JOSS review is a checklist against the public repository. The following
are **already true** for pydvma and need no new work:

- **Open-source licence** — BSD 3-Clause (`LICENSE`).
- **Public issue tracker** — <https://github.com/torebutlin/pydvma/issues>.
- **Documentation** — installation, usage and API docs at
  <https://torebutlin.github.io/pydvma/>.
- **Automated tests** — the `tests/` suite (a reviewer will want a short
  note on how to run it; `pytest` from the repo root).
- **A statement of need and functionality** — drafted in `paper.md`.

## Before finalising the prose

- Confirm the author/affiliation line and acknowledgements (add named
  contributors, and any funding/grant acknowledgement — there is a
  `TODO` marker in the Acknowledgements section of `paper.md`).
- Re-read the Functionality section against what actually ships at
  submission time so nothing is over- or under-claimed.
- Optional: build a local PDF preview of the paper with the JOSS Docker
  image or the `openjournals/inara` action to see the rendered layout
  before submitting.
