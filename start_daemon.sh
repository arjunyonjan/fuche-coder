#!/bin/bash
cd /home/arjun/fuche-coder
source venv/bin/activate
python3 auto_ingest.py > /tmp/auto_ingest.log 2>&1 &
nohup python3 cascade-mcp.py --daemon > /tmp/cascade.log 2>&1 &
exec python3 search.py --daemon
