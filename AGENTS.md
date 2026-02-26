# nanobot Development Guide

## Cursor Cloud specific instructions

### Project overview
nanobot is an ultra-lightweight personal AI assistant framework (~4,000 lines). It provides a CLI agent, a gateway for chat platforms, and scheduled tasks. See `README.md` for full details.

### Development commands
- **Install**: `pip install -e ".[dev]"` (add `[matrix]` for matrix channel tests)
- **Lint**: `ruff check nanobot/`
- **Test**: `pytest tests/ --ignore=tests/test_heartbeat_service.py` (that test has a pre-existing import error for `HEARTBEAT_OK_TOKEN`)
- **CLI**: `nanobot status`, `nanobot agent -m "Hello!"`, `nanobot onboard`

### Known issues
- `tests/test_heartbeat_service.py` fails to collect due to importing `HEARTBEAT_OK_TOKEN` which does not exist in `nanobot/heartbeat/service.py`. Exclude it with `--ignore`.
- 5 tests in `tests/test_matrix_channel.py` have pre-existing failures (KeyError on `attachments` metadata key, and a positional args mismatch in the mock).
- `ruff check` reports ~535 pre-existing style warnings (mostly `W293` whitespace and `I001` import ordering). These are in the existing codebase.

### PATH setup
The `nanobot` CLI and dev tools (`ruff`, `pytest`) install to `~/.local/bin`. Ensure it is on PATH:
```
export PATH="$HOME/.local/bin:$PATH"
```

### Running the agent
`nanobot agent -m "Hello!"` requires at least one LLM provider API key configured in `~/.nanobot/config.json`. Without a key, the CLI exits with `Error: No API key configured.`

To configure via the `OPENROUTER_API_KEY` env var, run `nanobot onboard` first, then inject the key into `~/.nanobot/config.json` programmatically. Example model: `openrouter/google/gemini-2.0-flash-001`.

### Config location
`~/.nanobot/config.json` — run `nanobot onboard` to initialize defaults.
