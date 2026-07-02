# AI Server Ping Monitor

## What It Does
Pings the current OpenCode provider's host (TCP connect), measures latency, reports status. Runs every 5 min via cron, cached to `/tmp/.ai-status`.

## Status Colors
| Status | Color | Latency | Meaning |
|--------|-------|---------|---------|
| fast | Green ● | <500ms | Responsive, work freely |
| ok | Yellow ● | 500-2000ms | Moderate, acceptable |
| slow | Red ● | >2000ms | Laggy, consider waiting |
| unreach | Red ✗ | timeout | Server down |

## Cascade Status
Cascade model load status fetched from Rust compressor server (`localhost:3000/cascade`) and written to `/tmp/.cascade-status`.

**Display format**: `cascade — Qwen ●, Ornith ○, DeepSeek ○`
- ● = model loaded in Ollama
- ○ = model unloaded

**Displayed in**:
- **Every OpenCode response** (via server-ping.md instruction)
- **fuche alias** — prints cascade bar before OpenCode starts
- **Cascade panel** in frontend HTML (`localhost:8080`) with official Qwen/DeepSeek SVGs

## Components
- **ping-ai.sh** (`~/.local/bin/ping-ai.sh`) — reads runtime model from `opencode.db`, selects host per provider (`api.deepseek.com` for opencode, `api.ollama.com` for ollama-cloud), measures TCP connect time
- **cron** — `*/5 * * * *` → writes JSON to `/tmp/.ai-status`
- **ai-ping-heartbeat.sh** — wraps ping + cascade status + writes both + TTS if slow. Runs from cron and on demand.
- **Prompt dot** (`~/.bashrc`) — `__ai_dot()` function prepended to PS1, shows colored dot before each shell command
- **OpenCode instruction** (`~/.config/opencode/instructions/server-ping.md`) — model reads `/tmp/.ai-status` and `/tmp/.cascade-status`, prefixes response with status + cascade chain
- **fuche alias** — reads `/tmp/.cascade-status` and prints cascade bar before launching OpenCode

## Providers
| Provider | Host | Key required? |
|----------|------|---------------|
| opencode (deepseek) | api.deepseek.com | No (TCP only) |
| ollama-cloud | api.ollama.com | No (TCP only) |

## OpenCode Response Prefix
Format: `🟢/🟡/🔴 + ms | cascade — Qwen ●, Ornith ○, DeepSeek ○`

Example: `🟢 84ms | cascade — Qwen ●, Ornith ○, DeepSeek ○`
