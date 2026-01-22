# Repository Guidelines

## Project Structure & Module Organization
- Core orchestration lives in the root (`spectra_app/spectra_orchestrator.py`, `spectra_app/coordination_interface.py`, `spectra_app/agent_optimization_engine.py`).
- Interface assets: `spectra_app/spectra_coordination_gui.py`, `templates/`, `static/`, plus launcher scripts (`scripts/spectra_launch.py`, `spectra.sh`).
- Persistent data: `migrations/`, `scheduler_state.json`, and SQLite artifacts (`spectra.db*`).
- Tests live in `tests/` (`test_*.py`); deeper references sit in `docs/` and `examples/`.

## Build, Test, and Development Commands
- `./spectra.sh [mode]` — default launcher; pass `cli`, `setup`, or `check` for alternate flows.
- `python3 scripts/spectra_launch.py --check` — validates environment, dependencies, and configuration.
- `python3 -m unittest discover -s tests -p "test_*.py"` — executes the regression suite (GUI + orchestration).
- `python3 tests/test_spectra_gui_system.py` — fast sanity check before submitting UI-facing changes.
- `pip install -r requirements.txt` or `pip install -e .` — install full dependency stack or editable package.

## Coding Style & Naming Conventions
- Python 3.11+, 4-space indentation, snake_case modules, PascalCase classes, UPPER_SNAKE_CASE constants.
- Keep type hints on public APIs and docstrings on orchestration entry points.
- Optional tooling lives under “Development & Testing” in `requirements.txt` (`black`, `flake8`, `mypy`); run it before review on shared modules.
- Keep configuration assets (`*.json`, `.service`) declarative and version-controlled.

## Testing Guidelines
- Extend or create `test_<feature>.py` modules alongside touched code; mirror TUI/CLI paths when shipping features.
- Use unittest async helpers when implementations leverage asyncio.
- Capture validation steps (`./spectra.sh --check`, targeted tests) in PR descriptions to document coverage.
- Prioritize account workflows, orchestration pipelines, and interface triggers.

## Commit & Pull Request Guidelines
- Follow Conventional Commit prefixes seen in history (`feat:`, `docs:`, `fix:`) and keep messages imperative.
- PRs should list scenario context, validation commands, related issues, and screenshots or TUI recordings for UX changes.
- Note schema migrations or configuration updates explicitly so operators can plan rollouts.

## TUI Integration Requirement
- Ship every feature through the TUI: update `spectra_app/spectra_coordination_gui.py`, related templates, and documentation (e.g., `GUI_README.md`).
- Ensure CLI/back-end additions expose equivalent controls in the TUI and document the navigation path.

## Outstanding TODO References
- `tgarchive/notifications.py:26` — add non-Telegram notification providers.
- `tgarchive/cli_extensions.py:255` — list topics from the database within CLI extensions.
- `tgarchive/cli_extensions.py:306` — persist topic metadata via `TopicOperations`.
- Track these items when planning future work; add TUI hooks once implemented.
