#!/usr/bin/env python3
from mcp.server.fastmcp import FastMCP
from main import (
    CODE_MODEL, GEN_MODEL, SYSTEM_PROMPT,
    is_code_question, get_context, ask, cache, is_online
)

mcp = FastMCP("Fuche AI")


@mcp.tool()
def ask_question(q: str) -> str:
    """Ask Fuche a question — routes to Qwen3 (code) or Hunyuan (general), searches web, returns answer."""
    is_code = is_code_question(q)
    model = CODE_MODEL if is_code else GEN_MODEL
    hist = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": q}] if not is_code else [{"role": "user", "content": q}]
    ctx = get_context(q)
    if ctx:
        hist = [{"role": "system", "content": f"Answer using this web context. If not relevant, use your own knowledge.\n{ctx}"}, {"role": "user", "content": q}]
    return ask(model, hist, 0.2)


@mcp.tool()
def search_web(q: str) -> str:
    """Search the web for a query and return page content."""
    ctx = get_context(q)
    return ctx or "No results — offline or search failed."


@mcp.tool()
def get_status() -> str:
    """Return Fuche system status: models loaded, online state, cache entries."""
    return f"Models: code={CODE_MODEL}, general={GEN_MODEL} | Online: {is_online()} | Cache: {len(cache._memory) + len(cache._disk)} entries"


if __name__ == "__main__":
    mcp.run("stdio")
