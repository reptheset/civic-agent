"""Terminal stand-in for the web UI.

  python -m scripts.api_client --upload data/my_docs/*   (start from documents)
  python -m scripts.api_client                            (start from the saved profile)
"""
import asyncio
import json
import sys
from pathlib import Path

import httpx
import websockets

API = "http://localhost:8000"


async def ask(prompt: str) -> str:
    return (await asyncio.to_thread(input, prompt)).strip()


async def answer(data: dict):
    kind = data.get("kind")
    if kind == "confirm_profile":
        print("\n>>> Please confirm your details:")
        for f in data["fields"]:
            flag = "" if f["confirmed"] or f["confidence"] >= 0.85 else "  <- uncertain"
            print(f"    {f['key']:20} {f['value'][:30]:30} {f['source']:28} conf {f['confidence']:.2f}{flag}")
        for m in data["mismatches"]:
            print(f"    MISMATCH {m['field']}: {m['values']}")
        values = {}
        for key in data["uncertain"] + [m["field"] for m in data["mismatches"]]:
            cur = next((f["value"] for f in data["fields"] if f["key"] == key), "")
            values[key] = await ask(f">>> {key} [{cur}] (Enter = correct): ") or cur
        for m in data["missing"]:
            opts = f" ({'/'.join(m['options'])})" if m.get("options") else ""
            v = await ask(f">>> {m['label']}{opts} (Enter to skip): ")
            if v:
                values[m["key"]] = v
        return {"values": values}
    if kind == "eligibility":
        g = data.get("guideline", {})
        print(f"\n>>> Eligibility: {str(data.get('verdict')).upper()}  ({g.get('name')})")
        print(f"    Source: {g.get('url')}  fetched {g.get('fetched_at')}")
        for r in data.get("results", []):
            mark = {True: "PASS", False: "FAIL", None: "REVIEW"}[r["passed"]]
            print(f"    [{mark:6}] {r['reason']}\n             \"{r['rule']['quote'][:120]}\"")
        return {"proceed": (await ask(">>> Proceed with the application anyway? (yes/no): ")).lower() == "yes"}
    if kind == "human_step":
        print(f"\n>>> {data.get('reason')}")
        await ask(">>> Do it in the agent's browser window, then press Enter... ")
        return {"done": True}
    if kind == "missing_info":
        print(f"\n>>> Missing information: {data.get('reason')}")
        key = await ask(f">>> Field name [{data.get('suggested_key')}]: ") or data.get("suggested_key")
        return {"key": key, "value": await ask(f">>> Value for {key}: ")}
    if kind == "approval":
        print("\n>>> Review before final submission:")
        for label, value in data.get("rows", []):
            print(f"    {label}: {value}")
        print("    Sources:", ", ".join(f"{k}={v}" for k, v in data.get("sources", {}).items()))
        return {"approved": (await ask(">>> Approve final submission? (yes/no): ")).lower() == "yes"}
    return None


async def main():
    args = sys.argv[1:]
    async with httpx.AsyncClient(timeout=60) as http:
        if args and args[0] == "--upload":
            files = [("files", (Path(a).name, open(a, "rb"))) for a in args[1:]]
            r = await http.post(f"{API}/runs/upload", files=files)
        elif args:
            r = None
            run_id = args[0]
        else:
            r = await http.post(f"{API}/runs", json={})
        if r is not None:
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
                        print("\nReceipt:", json.dumps(ev["data"]["receipt"], indent=2)[:1200])
                    break


if __name__ == "__main__":
    asyncio.run(main())
