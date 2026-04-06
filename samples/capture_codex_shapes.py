import asyncio, json
from pathlib import Path

from ipyai.codex_client import get_codex_client

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT/"samples"/"outputs"


async def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = get_codex_client()
    thread_id = await client.start_thread(model="gpt-5.4-mini", ephemeral=True)

    raw_events = []
    async for chunk in client.turn_stream(thread_id,
        "Think and provide a really concise reference of how the SI units are built from first principles.",
        think="h"):
        raw_events.append(chunk)

    path = OUT_DIR/"codex_text_stream.json"
    path.write_text(json.dumps(raw_events, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(f"Wrote {len(raw_events)} events to {path}")


if __name__ == "__main__": asyncio.run(main())
