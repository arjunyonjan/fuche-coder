# Session: jarvis-rs TTS Optimization — June 17, 2026

## Project Map

- `~/fuche-coder/` — Python wrapper + `fuche` alias entry point
- `~/projects/rust-ai/jarvis-rs/` — Rust TTS CLI (Qwen3-TTS-0.6B on CUDA)
- `~/projects/rust-ai/qwen_tts_patched/` — Patched Qwen TTS Rust crate

## Pipeline

```
fuche tts "text"
  → ~/.bashrc PATH → ~/fuche-coder/fuche (bash wrapper)
  → source venv → python3 tts.py "$@"
  → jarvis-rs run "text" --stdout --style calm --fx flanger,reverb
                          --fast --chunk-size 2
  → raw PCM (24kHz s16le) → pipe → paplay (speakers)
```

All paths use `os.path.expanduser()` — no relative paths. Works from any directory.

---

## Changes Made

### 1. tts.py — Voice defaults

| Flag | Before | After |
|---|---|---|
| `--style` | `cheerful` | **calm** |
| `--fx` | `none` | **flanger,reverb** |
| `--preset` | `"none"` | `None` (explicit only) |
| `--fast` (implied) | off | **on** (flag inverted to `--no-fast`) |
| `--chunk-size` | `8` | **2** |

Always passes `--chunk-size` to jarvis-rs. Always passes `--fast` unless `--no-fast`.

### 2. jarvis-rs — --fast flag (greedy decoding)

`main.rs` RunArgs:
```rust
#[arg(long)]
fast: bool,
```

Uses `TtsEngine::synthesize_fast()`:
- `do_sample: false` — greedy, no sampling
- `max_new_tokens: 512`
- ~2x speedup

Wired through `run()` — fast path generates all audio, applies FX, then writes/plays.

### 3. jarvis-rs — --chunk-size flag

```rust
#[arg(long, default_value = "8")]
chunk_size: usize,
```

Replaces hardcoded `8` in `synthesize_stream()` call. Lower values = lower first-token latency.

### 4. jarvis-rs — --dtype f32|f16

```rust
#[arg(long, default_value = "f32")]
dtype: String,
```

Runtime toggle for weight precision. `TtsEngine::new()` accepts `DType` parameter.
Threaded through `main.rs` → `tts.rs` → `repl.rs` → `tts.py`.

**F16 status:** Model loads in F16 but inference fails:
- Streaming path: `unexpected dtype, expected: F32, got: F16`
- Fast path (--fast + F16): generates garbage/noise (40-160s output for 4 words)
- Flag kept for future models that properly support half-precision

### 5. Flash attention (added then reverted)

Source files were modified:
- `Cargo.toml`: `features = ["cuda", "flash-attn"]`
- `main.rs`, `repl.rs`, `tts.rs`: added `use_flash_attn: bool` plumbing
- `tts.py`: added `--flash-attn` flag

Build aborted — `candle-flash-attn` compiles CUDA kernels via nvcc, very resource-heavy on laptop. Reverted to `features = ["cuda"]` only.

### 6. Daemon mode (planned)

`jarvis-rs/src/serve.rs` — Unix socket listener:
- Loads model once on startup
- Listens on `/tmp/jarvis.sock`
- Accepts JSON requests → runs TTS → returns PCM audio

`main.rs` — `Serve(ServeArgs)` subcommand.

`tts.py` — try daemon socket first, fallback to subprocess.

Eliminates the 30-60s cold start.

---

## Files Changed

| File | Lines | Purpose |
|---|---|---|
| `~/fuche-coder/tts.py` | ~75 | All CLI flags, defaults, daemon fallback |
| `~/projects/rust-ai/jarvis-rs/src/main.rs` | ~25 | `--fast`, `--chunk-size`, `--dtype`, `--flash-attn` |
| `~/projects/rust-ai/jarvis-rs/src/tts.rs` | ~5 | `DType` + `use_flash_attn` params |
| `~/projects/rust-ai/jarvis-rs/src/repl.rs` | ~5 | Thread `dtype` + `flash_attn` |
| `~/projects/rust-ai/jarvis-rs/Cargo.toml` | 1 | flash-attn feature (reverted) |

---

## Git

**fuche-coder:**
```
cca2eb7  Thread --fast, --chunk-size, --dtype through fuche tts wrapper
3c5f89f  Default to --fast + --chunk-size 2 (--no-fast to opt out)
```

**jarvis-rs:**
```
d42104f  Add --fast, --chunk-size, --dtype CLI flags + FP16 toggle
```

No remote configured on jarvis-rs.

---

## CLI Cheatsheet

```bash
fuche tts "text"                              # calm + flanger,reverb + fast
fuche tts "text" --no-fast                    # disable greedy (full quality)
fuche tts "text" --chunk-size 8               # larger chunks (higher latency)
fuche tts "text" --style news --fx none       # override everything
fuche tts "text" --dtype f16                  # F16 (if model supports it)
fuche tts "text" --preset jarvis              # full JARVIS FX preset
fuche tts "text" --voice vivian               # switch voice
fuche tts "text" --instruct "Speak like Yoda" # custom instruct
```

## Performance

| Config | Speed | Quality | Notes |
|---|---|---|---|
| Default (fast + chunk 2) | ~2x faster | Very good | Recommended |
| `--no-fast` | baseline | Best | Streaming with sampling |
| `--chunk-size 1` | lowest latency | Same | Aggressive streaming |
| `--dtype f16` | N/A | Broken | Model doesn't support F16 |

**Remaining bottleneck:** 30-60s model cold start on every call. Daemon mode will fix this.
