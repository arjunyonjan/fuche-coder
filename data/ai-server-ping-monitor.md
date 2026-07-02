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
Cascade model load status fetched from localhost:3000/cascade and written to `/tmp/.cascade-status`.

**Display format**: `cascade — Qwen ●, Ornith ○, DeepSeek ○`
- ● = model loaded in Ollama
- ○ = model unloaded

**Displayed in**:
- **Every OpenCode response** (via server-ping.md instruction)
- **fuche alias** — prints cascade bar before OpenCode starts
- **Cascade panel** in token compressor frontend (`localhost:8080`) with official SVGs

## Components
- **ping-ai.sh** (`~/.local/bin/ping-ai.sh`) — reads runtime model from `opencode.db`, selects host per provider, measures TCP connect time
- **cron** — `*/5 * * * *` → writes JSON to `/tmp/.ai-status`
- **ai-ping-heartbeat.sh** — wraps ping + cascade status + writes both + TTS if slow
- **Prompt dot** (`~/.bashrc`) — `__ai_dot()` in PS1, colored dot before each shell command
- **OpenCode instruction** (`~/.config/opencode/instructions/server-ping.md`) — AI prefixes response with status + cascade chain
- **fuche alias** — reads `/tmp/.cascade-status` and prints cascade bar before OpenCode
- **cascade.py** (`~/fuche-coder/cascade.py`) — model cascade with quality gate, writes updated status after each cascade run

## Token Compressor
- **Rust server** on `:3000` with `/compress` and `/cascade` endpoints
- **Frontend** at `localhost:8080` (live-server serving `frontend/index.html`)
- Cascade panel shows model icons (Qwen, Ornith, DeepSeek) with ●/○ loaded indicators
- Speak button sends compressed text to `/tts` endpoint

## Providers
| Provider | Host | Key required? |
|----------|------|---------------|
| opencode (deepseek) | api.deepseek.com | No (TCP only) |
| ollama-cloud | api.ollama.com | No (TCP only) |

## OpenCode Response Prefix
Format: `🟢/🟡/🔴 + ms | cascade — Qwen ●, Ornith ○, DeepSeek ○`
