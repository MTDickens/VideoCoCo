# Project conventions

- Always use `uv` to manage Python environments and dependencies.
- Declare dependencies in `pyproject.toml` and maintain `uv.lock` with `uv`.
- Use `uv sync` for setup, `uv add` for dependency changes, and `uv run` for
  Python scripts and tests. Do not use standalone `pip` or `python -m venv`.
- Keep setup instructions, examples, and runtime help consistent with this policy.
- Blender scripts use Blender's bundled Python; do not manage that interpreter
  or install packages into it.
- Run `bash run_autoformat.sh` for safe Ruff fixes and formatting, and
  `bash run_ci_checks.sh` for formatting, linting, ty, and offline tests.
- These checks cover the Seedance runner in `scripts/` and `tests/`.
- Keep Python 3.10 compatibility and annotate new or changed runner functions.
