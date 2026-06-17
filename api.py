#!/usr/bin/env python3
import asyncio
import html
import io
import json
import os
import re
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

import requests
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
import uvicorn

from main import (
    models, SYSTEM_PROMPT, OLLAMA,
    is_code_question, get_context, ask, cache, is_online, log
)

app = FastAPI(title="Fuche AI", version="1.0.0")




class AskRequest(BaseModel):
    q: str
    model: str | None = None


class AskResponse(BaseModel):
    model: str
    answer: str
    context: bool
    online: bool


def clean(text):
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'</?answer>', '', text)
    return text.strip()


def ntfy(msg):
    try:
        requests.post("https://ntfy.sh/fuche2026", data=msg.encode(), timeout=3)
    except Exception:
        pass


def ask_stream(model, messages, temp=0.3):
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {"temperature": temp}
    }
    with requests.post(OLLAMA, json=payload, stream=True, timeout=120) as resp:
        for line in resp.iter_lines():
            if not line:
                continue
            try:
                data = json.loads(line)
                content = data.get("message", {}).get("content", "")
                if content:
                    yield f"data: {json.dumps({'token': content})}\n\n"
                if data.get("done"):
                    break
            except json.JSONDecodeError:
                continue


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/status")
def status():
    return {
        "models": {"code": models.code, "general": models.general},
        "online": is_online(),
        "cache": {"entries": len(cache._memory) + len(cache._disk)}
    }


@app.get("/models")
def list_models():
    return {"available": models.list_ollama(), "code": models.code, "general": models.general, "crawl": models.crawl}


class ModelSet(BaseModel):
    code: str | None = None
    general: str | None = None
    crawl: bool | None = None


@app.post("/models")
def set_models(req: ModelSet):
    models.set(code=req.code, general=req.general, crawl=req.crawl)
    return {"status": "ok", "code": models.code, "general": models.general, "crawl": models.crawl}


JARVIS = os.path.expanduser("~/fuche-coder/jarvis-rs")
JARVIS_MODEL = os.path.expanduser("~/projects/rust-ai/jarvis-rs/models/Qwen3-TTS-12Hz-0.6B-CustomVoice")


@app.get("/tts")
def tts(text: str, voice: str = "ryan", language: str = "english"):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
    try:
        result = subprocess.run(
            [JARVIS, "run", text, "--model", JARVIS_MODEL, "--voice", voice, "--language", language, "-o", wav_path],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            return {"error": f"jarvis-rs error: {result.stderr}"}
        with open(wav_path, "rb") as f:
            data = f.read()
        return StreamingResponse(io.BytesIO(data), media_type="audio/wav")
    finally:
        if os.path.exists(wav_path):
            os.unlink(wav_path)


VRAM_TIERS = [
    (6.0, "qwen2.5-coder:7b", "qwen2.5-coder:7b-instruct"),
    (3.0, "deepseek-coder:1.3b", "alibayram/hunyuan:0.5b"),
    (0.0, "qwen3:0.6b", "alibayram/hunyuan:0.5b"),
]


def get_vram():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free,memory.used,utilization.gpu", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5
        )
        if out.returncode != 0:
            return {"available": False, "gpu": None, "free_gb": 0, "util_pct": 0, "recommended": {"code": models.code, "general": models.general}}
        parts = [p.strip() for p in out.stdout.strip().split(",")]
        free_gb = float(parts[2].split()[0]) / 1024
        total_gb = float(parts[1].split()[0]) / 1024
        used_gb = float(parts[3].split()[0]) / 1024
        util_pct = int(parts[4].split()[0])
        rec_code, rec_gen = models.code, models.general
        for threshold, c, g in VRAM_TIERS:
            if free_gb >= threshold:
                rec_code, rec_gen = c, g
                break
        return {
            "available": True,
            "gpu": parts[0],
            "total_gb": round(total_gb, 1),
            "free_gb": round(free_gb, 1),
            "used_gb": round(used_gb, 1),
            "util_pct": util_pct,
            "recommended": {"code": rec_code, "general": rec_gen}
        }
    except Exception:
        return {"available": False, "gpu": None, "free_gb": 0, "util_pct": 0, "recommended": {"code": models.code, "general": models.general}}


@app.get("/vram")
def vram():
    return get_vram()


@app.post("/api/ask", response_model=AskResponse)
def ask_endpoint(req: AskRequest):
    online = is_online()
    is_code = is_code_question(req.q)
    model = req.model or models.pick(is_code)
    ctx = get_context(req.q)
    messages = [
        {"role": "system", "content": f"Answer using web context.\n{ctx}"},
        {"role": "user", "content": req.q}
    ] if ctx else [{"role": "user", "content": req.q}]
    answer = clean(ask(model, messages, 0.2))
    return AskResponse(model=model, answer=answer, context=bool(ctx), online=online)


INDEX = Path("templates/index.html").read_text()


@app.get("/")
async def index():
    return HTMLResponse(INDEX)


@app.post("/ask/stream")
async def ask_stream_ep(q: str = Form(...), model: str = Form("")):
    if not model:
        is_code = is_code_question(q)
        model = models.pick(is_code)
    else:
        is_code = (model == models.code)
    badge = "💻 Coder" if is_code else "🧠 Reasoner"

    ctx = get_context(q)
    messages = [
        {"role": "system", "content": f"Answer using web context.\n{ctx}"},
        {"role": "user", "content": q}
    ] if ctx else [{"role": "user", "content": q}]

    async def event_stream():
        def parse_sse(line):
            if line.startswith("data: "):
                return json.loads(line[6:].strip())
            return None

        full = ""
        try:
            yield f"data: {json.dumps({'meta': {'badge': badge, 'model': model}})}\n\n"
            for event in ask_stream(model, messages, 0.2):
                data = parse_sse(event)
                if data and "token" in data:
                    full += data["token"]
                yield event
            full = clean(full)
            yield f"data: {json.dumps({'done': True, 'full': full})}\n\n"
        except (GeneratorExit, RuntimeError, asyncio.CancelledError):
            pass  # client disconnected, stop cleanly
        finally:
            ntfy(f"[{badge}] {q[:50]}... → {full[:80] or '(empty)'}...")

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/ask")
async def ask_ui(q: str = Form(...), model: str = Form("")):
    if not model:
        is_code = is_code_question(q)
        model = models.pick(is_code)
    else:
        is_code = (model == models.code)
    badge = "💻 Coder" if is_code else "🧠 Reasoner"

    ctx = get_context(q)
    messages = [
        {"role": "system", "content": f"Answer using web context.\n{ctx}"},
        {"role": "user", "content": q}
    ] if ctx else [{"role": "user", "content": q}]

    answer = clean(ask(model, messages, 0.2))

    user = f'<div class="flex justify-end"><div class="bg-blue-600 px-4 py-2.5 rounded-2xl rounded-br-sm max-w-[80%]"><span class="text-xs text-blue-300 block">{html.escape(badge)}</span>{html.escape(q)}</div></div>'
    ans = f'<div class="flex justify-start"><div class="bg-gray-800 px-4 py-2.5 rounded-2xl rounded-bl-sm max-w-[80%]"><span class="text-xs text-gray-400 block">🤖 {html.escape(model)}</span>{html.escape(answer)}</div></div>'
    ntfy(f"[{badge}] {q[:50]}... → {answer[:80]}...")
    return HTMLResponse(user + ans)


@app.get("/history")
async def history_ui():
    from main import hist
    convs = hist.list_convs()
    items = "".join(
        f'<div class="bg-gray-800 px-4 py-2 rounded-lg text-sm mb-2 cursor-pointer">📝 {html.escape(c["snippet"])} <span class="text-gray-500">— {c["count"]} msgs</span></div>'
        for c in convs
    ) or '<div class="text-center text-gray-600 italic py-8">No history yet</div>'
    return HTMLResponse(items)


@app.get("/search")
async def search_ui(q: str):
    from main import hist
    results = hist.search(q)
    items = "".join(
        f'<div class="bg-gray-800 px-4 py-2 rounded-lg text-sm mb-2">{html.escape(r["role"])}: {html.escape(r["content"][:120])}</div>'
        for r in results
    ) or '<div class="text-center text-gray-600 italic py-8">No matches</div>'
    return HTMLResponse(items)


if __name__ == "__main__":
    uvicorn.run("api:app", host="127.0.0.1", port=8000, log_level="info")
