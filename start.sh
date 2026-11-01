#!/bin/bash
# Test portal (internal only) + agent API (public). The API reaches the portal at localhost:8001.
set -e
uvicorn testbed.main:app --host 127.0.0.1 --port 8001 &
sleep 2
exec uvicorn agent.server:app --host 0.0.0.0 --port "${PORT:-7860}"
