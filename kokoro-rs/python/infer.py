#!/usr/bin/env python3
"""Kokoro-82M inference via stdin/stdout IPC.
Reads JSON lines from stdin, writes length-prefixed f32 PCM to stdout."""
import json
import os
import struct
import sys

import numpy as np

try:
    import torch
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
except ImportError:
    device = 'cpu'

try:
    from kokoro import KPipeline
    pipeline = KPipeline(lang_code='a', repo_id='hexgrad/Kokoro-82M', device=device)
except ImportError as e:
    print(f"Kokoro import error: {e}. Run: pip install kokoro", file=sys.stderr)
    sys.exit(1)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except json.JSONDecodeError as e:
        print(f"JSON error: {e}", file=sys.stderr)
        continue

    text = req.get("text", "")
    voice = req.get("voice", "bm_george")
    speed = req.get("speed", 1.0)
    if not text:
        continue

    try:
        chunks = []
        for result in pipeline(text, voice=voice, speed=speed):
            arr = result.audio.cpu().numpy() if hasattr(result.audio, 'cpu') else np.asarray(result.audio, dtype=np.float32)
            chunks.append(arr.astype(np.float32))
        if not chunks:
            continue
        audio = np.concatenate(chunks)
        pcm = audio.tobytes()
        sys.stdout.buffer.write(struct.pack('<I', len(pcm)))
        sys.stdout.buffer.write(pcm)
        sys.stdout.buffer.flush()
    except Exception as e:
        print(f"Inference error: {e}", file=sys.stderr)
        continue
