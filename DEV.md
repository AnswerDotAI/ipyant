# DEV

## Setup

Editable install:

```bash
pip install -e ipyai
```

Run tests:

```bash
cd ipyai
./tools/test.sh
```

Capture fresh Claude SDK shape samples:

```bash
cd ipyai
./tools/capture_samples.sh
```

The wrappers intentionally keep setup small:

- `tools/test.sh` sets `XDG_CONFIG_HOME` and `CLAUDE_CONFIG_DIR` to repo-local temp dirs, then runs `pytest`
- `tools/capture_samples.sh` regenerates the committed Claude SDK stream-shape artifacts under `samples/outputs/`

## File Map

- [ipyai/core.py](ipyai/core.py): IPython extension logic, prompt transforms, SQLite bookkeeping, notebook save/load, prompt mode, keybindings, Rich streaming display, backend selection
- [ipyai/backends.py](ipyai/backends.py): backend registry, canonical backend names, default models
- [ipyai/backend_common.py](ipyai/backend_common.py): shared backend context/base classes, typed conversation seed types, common stream formatter, replay helpers, and shared tool/command display helpers
- [ipyai/claude_client.py](ipyai/claude_client.py): Claude Agent SDK backend, custom MCP tool registration, synthetic session writing, and SDK event translation into canonical backend events
- [ipyai/api_client.py](ipyai/api_client.py): Claude API backend via `lisette`; this is the explicit exception to the common canonical-event formatter path and still uses lisette's native formatter
- [ipyai/codex_client.py](ipyai/codex_client.py): Codex app-server backend, thread/session orchestration, and app-server event translation into canonical backend events
- [ipyai/tooling.py](ipyai/tooling.py): shared custom `ToolRegistry`, schema generation, and local tool calling helpers
- [ipyai/cli.py](ipyai/cli.py): `ipyai` console entry point
- [tests/conftest.py](tests/conftest.py): minimal shell/history harness with repo-local config paths
- [tests/test_backends.py](tests/test_backends.py): shared backend test helpers
- [tests/test_backend_claude_sdk.py](tests/test_backend_claude_sdk.py): Claude SDK end-to-end test
- [tests/test_backend_claude_api.py](tests/test_backend_claude_api.py): Claude API end-to-end test
- [tests/test_backend_codex.py](tests/test_backend_codex.py): Codex end-to-end test
- [tests/test_core.py](tests/test_core.py): small local guardrail tests for transforms and backend session filtering
- [samples/capture_sdk_shapes.py](samples/capture_sdk_shapes.py): real Claude SDK capture script
- [samples/outputs/](samples/outputs/): committed normalized SDK payload captures

## CLI Flag Plumbing

`ipyai` uses `ipythonng.cli.parse_flags()` to split CLI args into ipyai flags and IPython args. `parse_flags` scans `sys.argv[1:]` for short flags (e.g. `-b`, `-r`, `-l`) that are not IPython's own short flags, collects them and their values into `IPYTHONNG_FLAGS` env var, and passes the rest through to IPython. When the ipyai extension loads, `_parse_ng_flags()` in `core.py` reads `IPYTHONNG_FLAGS` and parses it with argparse. This two-stage approach lets ipyai flags coexist with IPython flags on the same command line (e.g. `ipyai -b codex -r 5 --pdb`).

## Current Architecture

### Prompt Flow

1. Input starting with `.` is rewritten into `%ipyai`.
2. `IPyAIExtension.run_prompt()` reconstructs recent code/output/note context from IPython history.
3. Variable refs like `$`name`` and shell refs like `!`cmd`` are injected above the prompt.
4. The selected backend streams the turn:
   - `core.py` first builds a typed `ConversationSeed`
   - each backend then `prepare_turn(...)`s using that seed
   - Claude Agent SDK resumes or synthesizes a provider session
   - Claude API rebuilds flat history from the typed seed
   - Codex resumes or bootstraps an app-server thread from the typed seed
5. `astream_to_stdout()` renders the response through Rich in TTY mode and stores the final transcript text locally.

Completion policy is shared in `BaseBackend.complete()`:

- empty `ConversationSeed`
- `provider_session_id=None`
- `tool_mode="off"`
- `ephemeral=True`
- `think="l"`

Backends can still override `complete()` if a provider genuinely requires it, but the default path is now the contract.

### State Model

There are two layers of state:

- IPython shell session state, stored in IPython's own SQLite DB
- backend conversation state, stored as provider session IDs or thread IDs when the backend supports them

`ipyai` uses:

- `claude_prompts` for AI prompt history
- `sessions.remark` JSON for `cwd`, `backend`, and `provider_session_id`

If prompt history exists locally but `provider_session_id` is missing, provider bootstrap is backend-specific:

- Claude Agent SDK synthesizes a Claude transcript JSONL file once
- Claude API uses the typed flat-history seed directly
- Codex starts a new thread and sends the typed notebook-XML seed once

Notebook save/load is explicit only:

- `%ipyai save <filename>`
- `%ipyai load <filename>`
- `ipyai -l <filename>`

There is no implicit `startup.ipynb` behavior.

### Tools

The custom tool story is intentionally small:

- shared custom tools across all backends:
  `pyrun`, `bash`, `start_bgterm`, `write_stdin`, `close_bgterm`, `lnhashview_file`, `exhash_file`
- built-ins: `Bash`, `Edit`, `Read`, `Skill`, `WebFetch`, `WebSearch`, `Write`

`pyrun` does not call back into `InteractiveShell.run_cell*`. It delegates to `safepyrun`, looked up in `shell.user_ns`, matching the old `ipycodex` direct-call boundary and avoiding nested IPython cell execution.

Provider-specific tool exposure now fans out from the shared `ToolRegistry`:

- Claude SDK: MCP tool objects plus allowed `mcp__ipy__...` names
- Claude API: OpenAI-style function schemas
- Codex: app-server `dynamicTools`

The `ipyai` CLI loads `safepyrun` before `ipyai`, so normal terminal sessions get `pyrun` automatically. `ipyai` seeds the other custom tools into `shell.user_ns` directly.

### Skills

Skills are Claude-native:

- built-in `Skill` tool is enabled
- SDK `setting_sources=["user", "project"]`
- optional plugin directories are discovered from `.claude/plugins` up the cwd parent chain

## Samples

The `samples/` directory exists so stream-shape spelunking does not need to be repeated.

Artifacts currently committed:

- `samples/outputs/text_stream.json`
- `samples/outputs/python_tool_stream.json`
- `samples/toolslm_sdk_tool_demo.py`

Those captures are useful when working on:

- `StreamEvent` shape changes
- tool-use / tool-result ordering
- `SystemMessage.init` payload changes
- partial thinking/text handling

`samples/toolslm_sdk_tool_demo.py` is a minimal reference for the `toolslm.get_schema_nm(...) -> claude_agent_sdk.tool(...) -> create_sdk_mcp_server(...)` path.

## Tests

The test suite is intentionally small and integration-heavy.

Current coverage focuses on:

- one real round-trip test for each backend
- notebook save/load followed by a real follow-up prompt
- backend-specific session metadata persistence
- prompt transform behavior
- backend session filtering in resume listings

## Notes

- `ipyai` resolves config paths via XDG.
- The repo-local test harness sets `XDG_CONFIG_HOME` so config writes stay out of a normal user config tree.
- The Claude SDK sample capture uses a repo-local `samples/.claude/` directory for Claude session artifacts.
