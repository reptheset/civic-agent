"""Terminal stand-in for the web UI: starts a run, shows events, answers pauses."""
import asyncio
import json
import sys

import httpx
import websockets

API = "http://localhost:8000"


async def answer(data: dict):
    kind = data.get("kind")
    if kind == "human_step":
        print(f"\n>>> {data.get('reason')}")
        await asyncio.to_thread(input, ">>> Do it in the agent's browser window, then press Enter... ")
        return {"done": True}
    if kind == "missing_info":
        print(f"\n>>> Missing information: {data.get('reason')}")
        key = await asyncio.to_thread(input, ">>> Field name: ")
        value = await asyncio.to_thread(input, ">>> Value: ")
        return {"key": key, "value": value}
    if kind == "approval":
        print("\n>>> Review before final submission:")
        for label, value in data.get("rows", []):
            print(f"    {label}: {value}")
        print("    Sources:", ", ".join(f"{k}={v}" for k, v in data.get("sources", {}).items()))
        ans = await asyncio.to_thread(input, ">>> Approve final submission? (yes/no): ")
        return {"approved": ans.strip().lower() == "yes"}
    return None


async def main():
    run_id = sys.argv[1] if len(sys.argv) > 1 else None
    async with httpx.AsyncClient(timeout=30) as http:
        if run_id is None:
            r = await http.post(f"{API}/runs", json={})
            r.raise_for_status()
            run_id = r.json()["run_id"]
        print(f"Run {run_id}\n")
        async with websockets.connect(f"ws://localhost:8000/runs/{run_id}/events") as ws:
            async for msg in ws:
                ev = json.loads(msg)
                print(f"[{ev['type']:8}] {ev['message']}")
                if ev["type"] == "interrupt":
                    value = await answer(ev["data"])
                    await http.post(f"{API}/runs/{run_id}/resume", json={"value": value})
                if ev["type"] == "done" or ev["message"].startswith("Workflow error"):
                    if ev["type"] == "done" and ev["data"].get("receipt"):
                        print("\nReceipt:", json.dumps(ev["data"]["receipt"], indent=2)[:1500])
                    break


if __name__ == "__main__":
    asyncio.run(main())
