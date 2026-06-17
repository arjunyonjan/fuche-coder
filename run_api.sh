#!/bin/bash
[ -f ~/.fuche/env ] && source ~/.fuche/env
source ~/fuche-coder/venv/bin/activate
uvicorn api:app --host 127.0.0.1 --port 8000 --reload
