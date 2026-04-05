# ipyant

`ipyant` is a terminal IPython extension that supports Claude-backed prompt using the Agent SDK, so it supports Claude Code subscriptions as well as API keys.

It is aimed at terminal IPython, not notebook frontends.

## Install

```bash
pip install -e ipyant
```

`ipyant` uses the local Claude Code / Claude Agent SDK stack, so Claude must already be installed and authenticated on the machine. It also depends on `safepyrun` for the live `python` tool.

## How to Use Prompts

There are several ways to send a prompt to Claude from ipyant:

**Dot prefix (`.`)** — In normal IPython mode, start any line with `.` to send it as a prompt. Everything after the dot is sent to Claude. Continuation lines (without a dot) are included too, so you can write multi-line prompts:

```python
.explain what this dataframe transform is doing
```

```python
.draft a plan for this notebook:
focus on state management
and failure cases
```

**Prompt mode** — When prompt mode is on, *every* line you type is sent to Claude by default. To run normal Python code instead, prefix the line with `;`. Shell commands (`!`) and magics (`%`) still work as usual. There are three ways to enable prompt mode:

- **`opt-p`** (Alt-p) — toggle prompt mode on/off at any time from the terminal
- **`-p` flag** — start ipyant in prompt mode: `ipyant -p`
- **`prompt_mode` config** — set `"prompt_mode": true` in `config.json` to always start in prompt mode

You can also toggle prompt mode during a session with `%ipyant prompt`.

## CLI

```bash
ipyant
```

Flags:

```bash
ipyant -r        # resume last session
ipyant -r 43     # resume session 43
ipyant -l file   # load a saved notebook session
ipyant -p        # start in prompt mode
```

On exit, `ipyant` prints the session ID so you can resume later.

## Load As Extension

```python
%load_ext ipyant
```

## Usage

`ipyant` is a normal IPython session — you can run Python code exactly as you would in plain IPython. On top of that, you can send prompts to Claude as described above. `%ipyant` / `%%ipyant` magics are also available.

Useful commands:

```python
%ipyant
%ipyant model sonnet
%ipyant completion_model haiku
%ipyant think m
%ipyant code_theme monokai
%ipyant log_exact true
%ipyant prompt
%ipyant save mysession
%ipyant load mysession
%ipyant sessions
%ipyant reset
```

## Context Model

For each AI prompt, `ipyant` sends:

- recent IPython code as `<code>`
- string-literal note cells as `<note>`
- recent outputs as `<output>`
- the current request as `<user-request>`
- referenced live variables as `<variable>`
- referenced shell command output as `<shell>`

Prompts are stored in SQLite in a dedicated `claude_prompts` table. Claude-native session metadata is stored in IPython's `sessions.remark` as JSON, including `cwd`, `provider`, and `provider_session_id`.

## Tools

`ipyant` exposes exactly one custom tool:

- `python`: delegates to `pyrun` in the live IPython namespace

It also enables these built-in Claude Code tools:

- `Bash`
- `Edit`
- `Read`
- `Skill`
- `WebFetch`
- `WebSearch`
- `Write`

The `ipyant` CLI loads `safepyrun` before `ipyant`, so `pyrun` is available by default in normal terminal use.

## Skills

Skills are Claude-native. `ipyant` enables the built-in `Skill` tool and loads normal Claude user/project skills through the Agent SDK.

## Notebook Save/Load

`%ipyant save <filename>` writes a notebook snapshot. It stores:

- code cells
- note cells
- AI responses as markdown cells
- prompt metadata including both `prompt` and `full_prompt`

`%ipyant load <filename>` restores that notebook into a fresh session. On the next prompt after such a load, `ipyant` synthesizes a Claude transcript JSONL file once, stores the resulting Claude session ID, and then resumes natively from that point onward.

## Keyboard Shortcuts

- `Alt-.`: AI inline completion
- `Alt-p`: toggle prompt mode
- `Alt-Up/Down`: history navigation
- `Alt-Shift-W`: paste all Python code blocks from the last response
- `Alt-Shift-1` through `Alt-Shift-9`: paste the Nth Python code block
- `Alt-Shift-Up/Down`: cycle through extracted Python blocks

## Config

Config lives under `XDG_CONFIG_HOME/ipyant/`:

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
