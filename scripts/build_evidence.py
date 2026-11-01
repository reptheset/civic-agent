"""Rebuilds the evidence pack for a finished run from its checkpoint: python -m scripts.build_evidence <run_id>"""
import asyncio
import json
import sys

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agent.config import CHECKPOINT_DB, RECEIPT_DIR
from agent.evidence import build_evidence_pdf


async def main(run_id: str):
    async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB)) as saver:
        tup = await saver.aget_tuple({"configurable": {"thread_id": run_id}})
    state = tup.checkpoint["channel_values"]
    rec = json.loads((RECEIPT_DIR / f"{run_id}.json").read_text())
    path, digest = build_evidence_pdf(rec, state)
    print(path, digest[:16])


asyncio.run(main(sys.argv[1]))
