# Contributing

## Scope

SPECTRA mixes a mature `tgarchive` package with newer GUI/orchestration work in
`src/spectra_app`. Prefer incremental changes with explicit verification over
large repository-wide refactors.

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Useful Checks

```bash
python3 -m compileall tgarchive src/spectra_app spectra_app tests setup.py
python3 tests/test_readme_gui.py
python3 tests/test_local_only_gui.py
python3 tests/test_spectra_gui_simplified.py
```

If you touch the launcher or machine-control API, also verify:

```bash
python3 -m spectra_app.spectra_gui_launcher --help
```

## Layout

- `tgarchive/`: primary archiving/discovery package
- `src/spectra_app/`: orchestration and local web interface implementation
- `spectra_app/`: compatibility package for repo-root imports
- `templates/`: launcher HTML templates
- `docs/`: Docusaurus docs source plus legacy compatibility docs
- `tests/`: repository-level smoke/integration scripts

## Change Guidelines

- Keep import-time side effects low.
- Preserve repo-root compatibility paths unless you update all call sites.
- Prefer structured JSON/OpenAPI surfaces over custom AI-specific protocols.
- Do not commit runtime databases, logs, or virtualenv contents.

## Pull Requests

- Explain user-visible behavior changes.
- Include verification commands you ran.
- Call out any remaining gaps, especially dependency-optional paths.
