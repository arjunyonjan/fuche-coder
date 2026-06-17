#!/usr/bin/env python3
import ast
import re
from mcp.server.fastmcp import FastMCP
from main import (
    models, SYSTEM_PROMPT,
    is_code_question, get_context, ask, cache, is_online, log
)

mcp = FastMCP("Fuche AI")

FIX_PROMPT = "The code above has an error: {error}\nFix the error and return only the corrected code. Do not explain."


def extract_code(text):
    blocks = re.findall(r'```(?:\w+)?\n(.*?)```', text, re.DOTALL)
    if blocks:
        return blocks[0].strip()
    lines = text.strip().split('\n')
    code_lines = [line for line in lines if line.strip() and not line.strip().startswith(('//', '#'))]
    return '\n'.join(code_lines) if code_lines else text.strip()


def check_code(code):
    try:
        ast.parse(code)
        return None
    except SyntaxError as e:
        return f"SyntaxError at line {e.lineno}: {e.msg}"


@mcp.tool()
def ask_question(q: str) -> str:
    """Ask Fuche a question — routes to Qwen3 (code) or Hunyuan (general), searches web, returns answer."""
    is_code = is_code_question(q)
    model = models.pick(is_code)
    hist = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": q}] if not is_code else [{"role": "user", "content": q}]
    ctx = get_context(q)
    if ctx:
        hist = [{"role": "system", "content": f"Answer using this web context. If not relevant, use your own knowledge.\n{ctx}"}, {"role": "user", "content": q}]
    return ask(model, hist, 0.2)


@mcp.tool()
def generate_code(q: str) -> str:
    """Generate code with automatic error fixing. Writes code, checks for Python syntax errors, and retries up to 3 times."""
    hist = [
        {"role": "system", "content": "You are a code generator. Output only the code. If the user asks for Python, always include the function definition."},
        {"role": "user", "content": q}
    ]
    last_code = ""
    for attempt in range(1, 4):
        log.info(f"  [generate_code] attempt {attempt}")
        answer = ask(models.pick(True), hist, 0.2)
        code = extract_code(answer)
        last_code = code or answer

        if not code:
            return answer

        error = check_code(code)
        if error is None:
            log.info("  [generate_code] syntax OK")
            return code

        log.info(f"  [generate_code] error: {error}")
        hist.append({"role": "assistant", "content": answer})
        hist.append({"role": "user", "content": FIX_PROMPT.format(error=error)})

    log.info("  [generate_code] max retries — returning last attempt")
    return last_code


@mcp.tool()
def search_web(q: str) -> str:
    """Search the web for a query and return page content."""
    ctx = get_context(q)
    return ctx or "No results — offline or search failed."


@mcp.tool()
def speak(text: str, voice: str = "ryan", model: str = "qwen") -> str:
    \"\"\"Trigger Text-to-Speech via fuche tts. Supports 'qwen' (daemon) and 'kokoro' models.\"\"\"
    import subprocess
    try:
        # Construct the fuche command
        cmd = ["fuche", "tts", text]
        if model != "qwen":
            cmd.extend(["--model", model])
        if voice != "ryan":
            cmd.extend(["--voice", voice])
        
        # Execute via the bash entrypoint
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return f"Speech triggered successfully. Output: {result.stdout.strip()}"
    except subprocess.CalledProcessError as e:
        return f"TTS failed: {e.stderr or str(e)}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"

@mcp.tool()
def get_status() -> str:

    """Return Fuche system status: models loaded, online state, cache entries."""
    return f"Coder={models.code or '(none)'}, Reasoner={models.general or '(none)'}, Crawl={models.crawl} | Online: {is_online()} | Cache: {len(cache._memory) + len(cache._disk)} entries"


if __name__ == "__main__":
    mcp.run("stdio")
