# Samples

This directory stores reproducible Claude SDK stream-shape artifacts used during `ipyant` development.

Files:

- `capture_sdk_shapes.py`: runs a couple of small real Claude SDK prompts and writes normalized message/stream output
- `outputs/text_stream.json`: recorded text-only partial-message shape
- `outputs/python_tool_stream.json`: recorded custom-tool partial-message shape

Regenerate with:

```bash
cd ipyant
./tools/capture_samples.sh
```

The script writes Claude local state under `samples/.claude/` so it does not touch a normal `~/.claude` project transcript directory.
