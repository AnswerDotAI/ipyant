# ipyai

`ipyai` is a terminal IPython extension with three AI backends:

- Claude Agent SDK (`claude-sdk`, default)
- Claude API (`claude-api`)
- Codex (`codex`)

It is aimed at terminal IPython, not notebook frontends.

## Install

```bash
pip install -e ipyai
```

`ipyai` uses `safepyrun` for live Python state. Backend requirements:

- `claude-sdk`: local Claude Code / Agent SDK install and auth
- `claude-api`: Anthropic API access
- `codex`: local Codex app-server access

## How to Use Prompts

There are several ways to send an AI prompt from ipyai:

**Dot prefix (`.`)** — In normal IPython mode, start any line with `.` to send it as a prompt. Everything after the dot is sent to the selected backend. Continuation lines (without a dot) are included too, so you can write multi-line prompts:

```python
.explain what this dataframe transform is doing
```

```python
.draft a plan for this notebook:
focus on state management
and failure cases
```

**Prompt mode** — When prompt mode is on, *every* line you type is sent as an AI prompt by default. To run normal Python code instead, prefix the line with `;`. Shell commands (`!`) and magics (`%`) still work as usual. There are three ways to enable prompt mode:

- **`opt-p`** (Alt-p) — toggle prompt mode on/off at any time from the terminal
- **`-p` flag** — start ipyai in prompt mode: `ipyai -p`
- **`prompt_mode` config** — set `"prompt_mode": true` in `config.json` to always start in prompt mode

You can also toggle prompt mode during a session with `%ipyai prompt`.

## CLI

```bash
ipyai
ipyclaude
ipycodex
```

Flags:

```bash
ipyai -r                 # resume last session for the selected backend
ipyai -r 43              # resume session 43
ipyai -l session.ipynb   # load a saved notebook session at startup
ipyai -b codex           # select backend: claude-sdk | claude-api | codex
ipyai -p                 # start in prompt mode
```

`ipyclaude` is equivalent to `ipyai -b claude-api`.

`ipycodex` is equivalent to `ipyai -b codex`.

On exit, `ipyai` prints the session ID so you can resume later.

## Load As Extension

```python
%load_ext ipyai
```

## Usage

`ipyai` is a normal IPython session — you can run Python code exactly as you would in plain IPython. On top of that, you can send prompts to the selected AI backend as described above. `%ipyai` / `%%ipyai` magics are also available.

Useful commands:

```python
%ipyai
%ipyai model sonnet
%ipyai completion_model haiku
%ipyai think m
%ipyai code_theme monokai
%ipyai log_exact true
%ipyai prompt
%ipyai save mysession
%ipyai load mysession
%ipyai sessions
%ipyai reset
```

## Context Model

For each AI prompt, `ipyai` sends:

- recent IPython code as `<code>`
- string-literal note cells as `<note>`
- recent outputs as `<output>`
- the current request as `<user-request>`
- referenced live variables as `<variable>`
- referenced shell command output as `<shell>`

Prompt history is stored in SQLite; for compatibility, the table is currently named `claude_prompts`. Session metadata is stored in IPython's `sessions.remark` JSON, including `cwd`, `backend`, and `provider_session_id`.

## Tools

`ipyai` exposes the same custom tools across all backends:

- `pyrun`: run Python in the live IPython namespace
- `bash`: run an allowed shell command via `safecmd`
- `start_bgterm`: start a persistent shell session
- `write_stdin`: send input to a persistent shell session and read output
- `close_bgterm`: close a persistent shell session
- `lnhashview_file`: view hash-addressed file lines for verified edits
- `exhash_file`: apply verified hash-addressed edits to a file

When using the Claude Agent SDK backend, it also enables these built-in Claude Code tools:

- `Bash`
- `Edit`
- `Read`
- `Skill`
- `WebFetch`
- `WebSearch`
- `Write`

The `ipyai` CLI loads `safepyrun` before `ipyai`, so `pyrun` is available by default in normal terminal use.
`bash`, `start_bgterm`, `write_stdin`, `close_bgterm`, `lnhashview_file`, and `exhash_file` are seeded into the user namespace by `ipyai`.

## Skills

When using the Claude Agent SDK backend, `ipyai` enables the built-in `Skill` tool and loads normal Claude user/project skills through the Agent SDK.

## Notebook Save/Load

`%ipyai save <filename>` writes a notebook snapshot. It stores:

- code cells
- note cells
- AI responses as markdown cells
- prompt metadata including both `prompt` and `full_prompt`

`%ipyai load <filename>` restores that notebook into a fresh session.

`ipyai -l <filename>` does the same during startup.

Backend restore is backend-specific:

- `claude-sdk`: synthesizes a Claude transcript once, then resumes natively
- `claude-api`: reuses the saved local prompt history directly on each turn
- `codex`: starts a fresh thread and sends the loaded notebook as XML context once

## Keyboard Shortcuts

- `Alt-.`: AI inline completion
- `Alt-p`: toggle prompt mode
- `Alt-Up/Down`: history navigation
- `Alt-Shift-W`: paste all Python code blocks from the last response
- `Alt-Shift-1` through `Alt-Shift-9`: paste the Nth Python code block
- `Alt-Shift-Up/Down`: cycle through extracted Python blocks

## Config

Config lives under `XDG_CONFIG_HOME/ipyai/`:

- `config.json`
- `sysp.txt`
- `exact-log.jsonl`

`config.json` supports:

```json
{
  "model": "sonnet",
  "completion_model": "haiku",
  "think": "l",
  "code_theme": "monokai",
  "log_exact": false,
  "prompt_mode": false
}
```

## Development

See [DEV.md](DEV.md).
