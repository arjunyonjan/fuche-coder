"""MCP tool handler for system cleanup. Imported by cascade-mcp.py."""
import json, subprocess, os

TOOL_DEF = {
    "name": "system_cleanup",
    "description": "Run extreme file management cleanup. Dry-run by default. Use --force for actual deletion.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["dry-run", "force", "analyse-only", "wsl-compact"],
                "description": "dry-run (preview), force (execute), analyse-only (show sizes), wsl-compact (compact VHDX)"
            }
        },
        "required": ["mode"]
    }
}

def handle_cleanup(mode="dry-run"):
    cmd = ["python3", "/home/arjun/fuche-coder/cleanup.py"]
    if mode == "force":
        cmd.append("--force")
    elif mode == "analyse-only":
        cmd.append("--analyse-only")
    elif mode == "wsl-compact":
        cmd.append("--wsl-compact")
    else:
        cmd.append("--dry-run")

    env = os.environ.copy()
    env["PATH"] = f"/home/arjun/fuche-coder/venv/bin:{env.get('PATH', '')}"

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
    output = result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout
    if result.stderr:
        output += "\nSTDERR:\n" + result.stderr[-1000:]
    return output
