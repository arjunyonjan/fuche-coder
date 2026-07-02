# Session: jarvis-rs TTS — June 17, 2026

## 5 Things We Built / Fixed

1. **BF16 default** — F16 failed (5-bit exponent overflow → garbage). BF16 gives 1.34x speedup, identical quality to F32.
2. **Streaming fix** — `expected: F32, got: BF16` + `CUDA_ERROR_ASSERT` from OOB code lookups. Fixed: code clamp `[0,2047]`, BF16→F32 conversion, mid-generation decode.
3. **Daemon mode** — Unix socket, thread pool (4 workers), pre-warm, auto-start in wrapper. Instant cold start eliminated.
4. **Codebooks experiment (failed)** — Tried reducing RVQ from 32→16→8 layers. RVQ is additive, not denoising — any skip degrades quality. Reverted.
5. **Audio FX pipeline** — Flanger, reverb, bassboost, chorus, tremolo. JARVIS preset. Native f32 DSP, no extra deps.

**GUI**: None. CLI-only. 2 experiments failed, 3 shipped.

## Project Map

- `~/fuche-coder/` — Python wrapper + `fuche` alias + **release binary** (`jarvis-rs`)
- `~/projects/rust-ai/jarvis-rs/` — Rust TTS source + models
- `~/projects/rust-ai/qwen_tts_patched/` — Patched Qwen TTS Rust crate

## Pipeline

```
fuche tts "text"
  → fuche (bash wrapper) → python3 tts.py "$@"
  → ~/fuche-coder/jarvis-rs (daemon socket /tmp/jarvis.sock or subprocess)
  → raw PCM (24kHz s32le) → pipe → paplay/ffplay
```

## Changes Made (chronological)

### 1. tts.py — Defaults tuned for quality + speed
`--style calm`, `--fx flanger,reverb`, `--fast` on by default (`--no-fast` to disable), `--chunk-size 2`.

### 2. Greedy decoding (`--fast`)
`main.rs` RunArgs: `#[arg(long)] fast: bool`. Uses `synthesize_fast()` with `do_sample: false`, `subtalker_do_sample: false`, `repetition_penalty: 1.0`. ~2x speedup over streaming.

### 3. Chunk size (`--chunk-size`)
Configurable stream chunk size (default 2). Lower = lower first-token latency.

### 4. BF16 dtype (default)
`--dtype bf16` now default. Removed F16 (5-bit exponent overflows on attention). BF16 uses tensor cores on RTX 5060. **~1.34x speedup, 27% less CPU time** vs F32. Identical output quality.

### 5. Daemon mode (Unix socket)
`jarvis-rs/src/serve.rs` (~240 lines):
- Protocol: JSON request line → JSON header (`{"sample_rate":24000,"error":null}`) → raw PCM s16le
- Per-client threads, model via `Arc<TtsEngine>`
- Socket at `/tmp/jarvis.sock` (`0o666`)
- HTTP health endpoint: `GET /` or `/health` → `{"status":"ok"}`
- Error responses: invalid JSON / inference failures return `{"error":"..."}`
- Graceful shutdown via `libc::signal()` (SIGINT+SIGTERM → socket cleanup)
- Pre-warm: background thread runs dummy inference after load

`tts.py`: `--daemon` flag → `os.execvp` into `jarvis-rs serve`. Normal mode tries daemon first, falls back to subprocess.

### 6. Performance profiling (serve.rs)
PERF log line per request: `PERF fast | chars=69 samples=178005 sr=24000 | inference=7666.4ms fx=2.4ms write=0.7ms total=7669.6ms`
**Key finding**: GPU inference is bottleneck at ~1x real-time.

### 7. TTS fast-path optimizations (tts.rs)
- `subtalker_do_sample: false` — greedy, deterministic
- `repetition_penalty: 1.0` — skip penalty calc
- `max_new_tokens: text.len()*3` capped 64-2048 (up from 512)

### 8. BassBoost FX + JARVIS preset
`BassBoost` biquad low-shelf filter. `bassy_preset()`. Tuned JARVIS preset values (subtler flanger, tighter reverb).

### 9. Native f32 DSP pipeline
Removed redundant i16↔f32 conversions. `FxProcessor::process(&mut [f32])`. `TTSResult.samples: Vec<f32>` with `to_s16le()`, `apply_fx()`, `len_audio_ms()`.

### 10. Better max_new_tokens estimation
Uses `model.tokenize_text()` when available (×8, cap 2048). Falls back to char count (×3, cap 2048). Up from 512 → 2048 frames (~170s max).

### 11. Thread pool daemon
4 pre-spawned worker threads via `mpsc`. No `threadpool` dep.

### 12. Playback reliability (tts.py)
`_wait_playback()` kills player after 20s. Auto-detects PulseAudio via `pactl info`; falls back to ffplay.

### 13. Self-contained release binary
`jarvis-rs` (33MB) copied to `~/fuche-coder/`. No dep on `rust-ai/` at runtime.

### 14. `--codebooks` (added then removed)
Added `num_codebooks` field threaded through `CustomVoiceOptions` → `GenerationOptions` → `generate_with_cache()`. Two approaches tried:
1. **Zero-padding**: filled unused codebooks with token ID 0 → decoder summed token-0 embeddings (noise, not silence) → chipmunk output at 4/8/16/24 codebooks
2. **Unpadded**: decoder only loops over N actual codebooks → still chipmunk at 16-24
**Reverted**: RVQ layers are additive, not denoising — skipping any degrades quality at any level below 32.

### 15. Streaming fix — CUDA assert + dtype crash + daemon rebuild
`generate_custom_voice_from_text_stream()` crashed with `CUDA_ERROR_ASSERT` in conv1d/matmul and `expected: F32, got: BF16` in `to_vec1::<f32>()`.
**Root causes**:
- TTS model generates codes from vocab ~33k but tokenizer codebook has 2048 entries → OOB embedding lookups → NaN → GPU assert cascade
- Decoder outputs BF16 but `to_vec1::<f32>()` expects F32 CUDA storage
**Fixes**:
- Clamp codes to `[0, 2047]` before tokenizer decode (`codes.clamp(0u32, 2047u32)`)
- Explicit BF16→F32 conversion before `to_vec1::<f32>()`
- Refactored to decode **mid-generation** (every 8 frames) instead of collect-then-decode → lower first-audio latency
- Daemon mode: `TtsEngine` wrapped in `Arc<Mutex<>>` for thread safety
- Cleaned up unused `DType` imports from `code_predictor.rs`
- **Rebuilt & restarted daemon** with the fixed binary — old daemon was still running the pre-fix version

### 16. PowerShell audio playback (WSL→Windows bridge)
WSLg PulseAudio (RDPSink) was unreliable — audio either silent or cut off. Replaced `paplay`/`ffplay` with PowerShell's `Media.SoundPlayer` via `powershell.exe -Command`. Flow: PCM → WAV temp file in `/mnt/c/Users/.../AppData/Local/Temp/` → `powershell.exe (New-Object Media.SoundPlayer 'path').PlaySync()` → Windows speakers. Handles daemon and subprocess paths. Falls back to paplay/ffplay if PowerShell unavailable.

---
### June 18, 2026 — Session 2

### 17. Fast mode EOS fix — trailing silence eliminated → true greedy
`--fast` was using `do_sample=false, repetition_penalty=1.0` (greedy argmax). After speech content (~2.5s for 28 chars), argmax never selected EOS (4198) — the model generated all `max_new_tokens` steps, producing 10s+ audio with only ~2.5s speech followed by dead silence.

**Attempt 1** (Jun 17): `do_sample=true, temperature=0.01, repetition_penalty=1.05`. Near-deterministic, EOS fired, but inference was slow (~19.7s for 28 chars).

**Final fix** (Jun 18, Session 2): `do_sample=false, repetition_penalty=1.05`. True greedy. With repetition penalty 1.05, repeated post-speech tokens get penalized until EOS (4198) becomes the argmax. Inference dropped to **6.35s** — 3x faster than temperature=0.01, with clean termination.

**Additional**: `subtalker_do_sample=false` kept codebook generation deterministic.

`tts.py`: Removed `--no-fast` CLI flag. Fast mode is always the default.

### 19. Thread pool tuning — 4→2 workers, bounded queue
Daemon had 4 worker threads all serializing on the GPU via `Arc<Mutex<TtsEngine>>`. 4 workers added context-switch overhead with no throughput benefit (GPU can only run one inference at a time).

**Changes** (serve.rs):
- Workers reduced from 4 → 2 (one does GPU inference, other handles I/O)
- `mpsc::channel` (unbounded) → `mpsc::sync_channel(2)` (bounded). When 2 requests are queued, the acceptor blocks — clients wait at the socket level instead of piling up in memory.

### 18. Flash attention: CC 12.0 blocks fuse
RTX 5060 Laptop GPU = **CC 12.0** (Blackwell). `candle-flash-attn v0.9.2` compiles 33 CUDA kernels targeting `sm80` (CC 8.0). `nvcc` may crash or OOM on CC 12.0 with these kernel sources + CUTLASS headers (fetched from GitHub at build time). Build takes 30+ min if it doesn't crash.

**Status**: ❌ Deferred. Standard cuBLAS attention already uses CUDA — just not fused. If `candle-flash-attn` adds CC 12.0 support in a future release, revisit for potential 1.5-3x inference speedup.

---

## Current State

| Area | Status |
|---|---|
| Daemon | ✅ Running, socket at `/tmp/jarvis.sock` |
| BF16 default | ✅ Default dtype |
| Inference speed | ~1x real-time in BF16 (~7-17 chars/s) |
| Cold start | Eliminated (daemon pre-warm) |
| `--codebooks` | ❌ Removed — doesn't work with additive RVQ |
| Streaming (default) | ✅ Fixed — codes clamped, BF16→F32, mid-gen decode |
| Fast mode (EOS) | ✅ True greedy — `do_sample=false, rep_penalty=1.05`, 3x faster |
| `--no-fast` flag | ❌ Removed — no longer needed |
| Flash attention | ❌ Blocked — CC 12.0 not supported by candle-flash-attn v0.9.2 |

## Performance

| Config | Speed | Quality |
|---|---|---|
| Default (fast + chunk 2 + BF16) | ~2x | Very good |
| Daemon (after pre-warm) | Instant | Same |
| Codes: F32 | 0.77x RT | Reference |
| Codes: BF16 | 1.06x RT | Identical |

**Key insight**: Bottleneck is memory bandwidth on RTX 5060 (not compute). Flash attention would help but is blocked by CC 12.0. No viable quality/speed tradeoff exists via codebook reduction.

**Preference**: Always `--fast` (default). Daemon preferred over subprocess.

## CLI Cheatsheet

```bash
fuche tts "text"                              # defaults: BF16 + calm + flanger,reverb + fast + speed 1.2
fuche tts "text" --style news --fx none       # override style/FX
fuche tts "text" --voice vivian               # switch voice
fuche tts "text" --speed 1.0                  # normal speed (no time-stretch)
fuche tts "text" --speed 1.5                  # even faster (50% faster)
fuche tts "text" --instruct "Speak like Yoda" # custom instruct
fuche tts --daemon                            # start daemon (blocking)

# Health check
curl --unix-socket /tmp/jarvis.sock http://localhost/health
```

### 20. WSOLA Time-Stretch — Voice Speed Control (June 18)

Added `--speed` flag for time-stretching audio without changing pitch:

**Rust** (`dsp.rs`): `TimeStretch` struct implements WSOLA (Waveform Similarity Overlap-Add):
- Window size: 512 samples (~21ms at 24kHz), 50% overlap
- Cross-correlation alignment within ±128 samples for phase coherence
- Hann window + overlap-add normalization
- Pure f32 DSP, no external deps, ~80 lines

**FxConfig**: Added `SpeedParams { rate: f32 }` and `speed: Option<SpeedParams>` field. `has_effects()` includes speed.

**CLI**: `--speed <f32>` in both `jarvis-rs` (main.rs + serve.rs) and `tts.py`. Default: 1.2 in tts.py, 1.0 in jarvis-rs (backward compat).

**Performance**: time_stretch overhead = 14-29ms (negligible vs 2.8-4.5s inference).
- speed=1.0: 4.86s (44 chars)
- speed=1.2: 4.05s (20% faster) ✓
- speed=1.5: 3.24s (50% faster) ✓

**Daemon protocol**: `{"speed": 1.2}` in request JSON. Missing/serde default = `None` → no-op. Time-stretch applied after FX in fast path only (streaming path skips).

---
### July 2, 2026 — Session 3 — Cascade Monitoring & Token Compressor

### 21. AI Server Ping Monitor — cascade status
`ping-ai.sh` reads runtime model from opencode.db and TCP-pings provider host. Output cached to `/tmp/.ai-status` every 5 min via cron. Colors: fast (● <500ms), ok (● 500-2000ms), slow (● >2000ms), unreach (✗ timeout).

**OpenCode instruction** (`server-ping.md`): AI prefixes every response with status + cascade chain.

### 22. Cascade status heartbeat
`ai-ping-heartbeat.sh` writes both `/tmp/.ai-status` and `/tmp/.cascade-status` (from `localhost:3000/cascade`). Cron-driven.

### 23. Prompt dot in PS1
`~/.bashrc`: `__ai_dot()` shows colored ● before shell prompt based on `/tmp/.ai-status`.

### 24. fuche alias — cascade bar
Modified alias in `~/.bashrc` to print cascade status before OpenCode starts.

### 25. cascade.py — dynamic status update
Added `json.dump` of loaded/unloaded status to `/tmp/.cascade-status` after each cascade run. Only model that passed quality gate shows ●.

### 26. Token Compressor HTML — cascade panel + Speak button
Updated `frontend/index.html`:
- Cascade chain visualization with arrows showing active model
- Speak button sends compressed text to `/tts` endpoint
- Better styling, responsive indicators

### 27. KB docs updated
`ai-server-ping-monitor.md` and `qwen-code-deepseek-api.md` updated with current system state.

## Git

**fuche-coder** (origin/master): `e432dcc` → `85f6bcc` → `0a89319` → `a531e91` → `a2598e5` → `3c5f89f` → `cca2eb7` → `7ebba99` → `b67c8ca` → `d04987b`
