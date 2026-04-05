# DEV

`ipyant` is now a Claude Agent SDK-backed rewrite of the old `ipycodex` idea. The Codex app-server implementation has been removed.

## Setup

Editable install:

```bash
pip install -e ipyant
```

Run tests:

```bash
cd ipyant
./tools/test.sh
```

Capture fresh Claude SDK shape samples:

```bash
cd ipyant
./tools/capture_samples.sh
```

The wrappers intentionally keep setup small:

- `tools/test.sh` sets `XDG_CONFIG_HOME` and `CLAUDE_CONFIG_DIR` to repo-local temp dirs, then runs `pytest`
- `tools/capture_samples.sh` regenerates the committed Claude SDK stream-shape artifacts under `samples/outputs/`

## File Map

- [ipyant/core.py](ipyant/core.py): IPython extension logic, prompt transforms, SQLite bookkeeping, notebook save/load, prompt mode, keybindings, Rich streaming display
- [ipyant/claude_client.py](ipyant/claude_client.py): Claude SDK backend, custom `python` MCP tool, partial-stream normalization, synthetic session writing
- [ipyant/cli.py](ipyant/cli.py): `ipyant` console entry point
- [tests/conftest.py](tests/conftest.py): minimal shell/history/backend harness
- [tests/test_core.py](tests/test_core.py): focused integration-heavy extension tests
- [tests/test_claude_client.py](tests/test_claude_client.py): formatter and synthetic-session tests
- [samples/capture_sdk_shapes.py](samples/capture_sdk_shapes.py): real Claude SDK capture script
- [samples/outputs/](samples/outputs/): committed normalized SDK payload captures

## Current Architecture

### Prompt Flow

1. Input starting with `.` is rewritten into `%ipyant`.
2. `IPyAIExtension.run_prompt()` reconstructs recent code/output/note context from IPython history.
3. Variable refs like `$`name`` and shell refs like `!`cmd`` are injected above the prompt.
4. `ClaudeBackend.stream_turn()` opens a fresh `ClaudeSDKClient`, optionally resumes a prior Claude session ID, and streams partial events.
5. `astream_to_stdout()` renders the response through Rich in TTY mode and stores the final transcript text locally.

### State Model

There are two layers of state:

- IPython shell session state, stored in IPython's own SQLite DB
- Claude conversation state, stored as Claude session IDs plus Claude-native local transcript files

`ipyant` uses:

- `claude_prompts` for AI prompt history
- `sessions.remark` JSON for `cwd`, `provider`, and `provider_session_id`

If prompt history was restored from an explicit notebook load and `provider_session_id` is still missing, `ipyant` synthesizes a Claude transcript JSONL file once and resumes from that instead of replaying the full prompt history turn-by-turn.

Notebook save/load is explicit only:

- `%ipyant save <filename>`
- `%ipyant load <filename>`

There is no implicit `startup.ipynb` behavior.

### Tools

The custom tool story is intentionally small:

- one in-process MCP tool: `python`
- built-ins: `Bash`, `Edit`, `Read`, `Skill`, `WebFetch`, `WebSearch`, `Write`

No dynamic `%ipyant tool ...` path remains.

### Skills

Skills are Claude-native now:

- built-in `Skill` tool is enabled
- SDK `setting_sources=["user", "project"]`
- optional plugin directories are discovered from `.claude/plugins` up the cwd parent chain

The old custom `.agents/skills/` parser, `load_skill`, and eval-block mechanism are gone.

## Samples

The `samples/` directory exists so stream-shape spelunking does not need to be repeated.

Artifacts currently committed:

- `samples/outputs/text_stream.json`
- `samples/outputs/python_tool_stream.json`

Those captures are useful when working on:

- `StreamEvent` shape changes
- tool-use / tool-result ordering
- `SystemMessage.init` payload changes
- partial thinking/text handling

## Tests

The test suite is intentionally small and integration-heavy.

Current coverage focuses on:

- prompt transform behavior
- Rich streaming integration
- prompt/session persistence
- notebook save/load
- synthetic Claude session generation
- end-to-end follow-up prompt flow using a deterministic fake backend

There is also one real Claude-side integration point in the tests: synthetic session files are verified through `claude_agent_sdk.get_session_messages()` rather than only through local mocks.

## Notes

- `ipyant` resolves config paths via XDG.
- The repo-local test harness sets `XDG_CONFIG_HOME` so config writes stay out of a normal user config tree.
- The Claude SDK sample capture uses a repo-local `samples/.claude/` directory for Claude session artifacts.
