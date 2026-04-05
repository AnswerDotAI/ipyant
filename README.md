# ipyant

`ipyant` is a terminal IPython extension that turns input starting with `.` into a Claude-backed prompt.

It is aimed at terminal IPython, not notebook frontends.

## Install

```bash
pip install -e ipyant
```

`ipyant` uses the local Claude Code / Claude Agent SDK stack, so Claude must already be installed and authenticated on the machine.

## CLI

```bash
ipyant
```

Resume a previous session:

```bash
ipyant -r
ipyant -r 43
```

On exit, `ipyant` prints the session ID so you can resume later.

## Load As Extension

```python
%load_ext ipyant
```

Reload after local edits:

```python
%reload_ext ipyant
```

## Usage

Single-line prompt:

```python
.explain what this dataframe transform is doing
```

Multiline prompt:

```python
.draft a plan for this notebook:
focus on state management
and failure cases
```

`ipyant` also provides `%ipyant` / `%%ipyant`.

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

`%ipyant prompt` toggles prompt mode. `opt-p` toggles the same mode from the terminal keybinding layer.

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

- `python`: executes code in the live IPython namespace

It also enables these built-in Claude Code tools:

- `Bash`
- `Edit`
- `Read`
- `Skill`
- `WebFetch`
- `WebSearch`
- `Write`

There is no dynamic `%ipyant tool ...` mechanism.

## Skills

Skills are Claude-native now. `ipyant` enables the built-in `Skill` tool and loads normal Claude user/project skills through the Agent SDK. The old custom `load_skill` implementation is gone.

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
