#!/usr/bin/env python3
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

from main import (
    CODE_MODEL, GEN_MODEL, SYSTEM_PROMPT,
    is_code_question, get_context, ask, cache, is_online
)

app = FastAPI(title="Fuche AI Coder API", version="1.0.0")


class AskRequest(BaseModel):
    q: str


class AskResponse(BaseModel):
    model: str
    answer: str
    context: bool
    online: bool


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/status")
def status():
    return {
        "models": {"code": CODE_MODEL, "general": GEN_MODEL},
        "online": is_online(),
        "cache": {"entries": len(cache._memory) + len(cache._disk)}
    }


@app.get("/search")
def search(q: str):
    ctx = get_context(q)
    if ctx:
        return {"query": q, "results": ctx, "cached": False}
    cached = cache.get(q)
    if cached:
        return {"query": q, "results": cached, "cached": True}
    return {"query": q, "results": None, "error": "offline or search failed"}


@app.post("/ask", response_model=AskResponse)
def ask_endpoint(req: AskRequest):
    online = is_online()
    is_code = is_code_question(req.q)

    if is_code:
        model = CODE_MODEL
        history = [{"role": "user", "content": req.q}]
    else:
        model = GEN_MODEL
        history = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": req.q}
        ]
    ctx = get_context(req.q)
    if ctx:
        enhanced = [
            {"role": "system", "content": f"Answer using this web context. If not relevant, use your own knowledge.\n{ctx}"},
            {"role": "user", "content": req.q}
        ]
        answer = ask(model, enhanced, 0.2)
        return AskResponse(model=model, answer=answer, context=True, online=online)

    answer = ask(model, history, 0.2)
    return AskResponse(model=model, answer=answer, context=False, online=online)


if __name__ == "__main__":
    uvicorn.run("api:app", host="127.0.0.1", port=8000, log_level="info")
