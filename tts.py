#!/usr/bin/env python3
"""Local TTS via jarvis-rs (Qwen3-TTS-0.6B on CUDA) → daemon socket or subprocess."""
import argparse
import json
import os
import socket
import subprocess
import sys

JARVIS_DIR = os.path.expanduser("~/projects/rust-ai/jarvis-rs")
JARVIS = os.path.join(JARVIS_DIR, "target/release/jarvis-rs")
MODEL = os.path.join(JARVIS_DIR, "models/Qwen3-TTS-12Hz-0.6B-CustomVoice")
VOICE = "ryan"
SOCKET_PATH = "/tmp/jarvis.sock"

parser = argparse.ArgumentParser(description="Local TTS with jarvis-rs")
parser.add_argument("text", nargs="*", help="Text to speak")
parser.add_argument("--preset", default=None, choices=["jarvis", "subtle", "heavy", "bassy", "none"],
                    help="FX preset (overrides --fx)")
parser.add_argument("--fx", default="flanger,reverb",
                    help="Comma-separated FX: flanger,chorus,reverb,tremolo")
parser.add_argument("--voice", default=VOICE, help="Voice name")
parser.add_argument("--style", default="calm",
                    choices=["conversational", "news", "storytelling", "cheerful", "calm"],
                    help="Expression style preset")
parser.add_argument("--no-fast", action="store_true",
                    help="Disable greedy decoding (slower, higher quality)")
parser.add_argument("--chunk-size", type=int, default=2,
                    help="Stream chunk size (lower = lower latency)")
parser.add_argument("--dtype", default=None, choices=["bf16"],
                    help="Half precision via BF16 (~2x speed, RTX 5060+)")
parser.add_argument("--instruct", default=None,
                    help="Raw instruct text (overrides --style)")
parser.add_argument("--daemon", action="store_true",
                    help="Start daemon mode (blocks, listens on Unix socket)")
args = parser.parse_args()


def _try_daemon(text):
    """Try synthesizing via daemon socket. Returns (pcm_bytes, sample_rate) or None."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(120)
    try:
        sock.connect(SOCKET_PATH)
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        sock.close()
        return None

    request = {
        "text": text,
        "voice": args.voice,
        "language": "english",
        "style": args.style,
    }
    if args.preset:
        request["preset"] = args.preset
    elif args.fx:
        request["fx"] = args.fx
    request["fast"] = not args.no_fast
    request["chunk_size"] = args.chunk_size
    if args.instruct:
        request["instruct"] = args.instruct

    sock.sendall((json.dumps(request) + "\n").encode())
    sock.shutdown(socket.SHUT_WR)

    header_bytes = b""
    while True:
        c = sock.recv(1)
        if not c or c == b"\n":
            break
        header_bytes += c

    meta = json.loads(header_bytes.decode())
    sample_rate = meta.get("sample_rate", 24000)

    if meta.get("error"):
        sock.close()
        raise RuntimeError(f"Daemon error: {meta['error']}")

    pcm = b""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            break
        pcm += chunk

    sock.close()
    return pcm, sample_rate


if args.daemon:
    cmd = [JARVIS, "serve", "--model", MODEL]
    if args.dtype:
        cmd += ["--dtype", args.dtype]
    os.execvp(cmd[0], cmd)

text = " ".join(args.text) or sys.stdin.read().strip()
if not text:
    print("Usage: ./tts.py [--style conversational|news|...] 'text'", file=sys.stderr)
    sys.exit(1)

result = _try_daemon(text)
if result is not None:
    pcm, sample_rate = result
    paplay = subprocess.Popen(
        ["paplay", "--raw", f"--rate={sample_rate}", "--channels=1", "--format=s16le"],
        stdin=subprocess.PIPE
    )
    paplay.stdin.write(pcm)
    paplay.stdin.close()
    paplay.wait()
    print(f"  ✓ {text[:60]}… (daemon)", file=sys.stderr)
    sys.exit(0 if paplay.returncode == 0 else 1)

cmd = [JARVIS, "run", text, "--model", MODEL, "--voice", args.voice, "--stdout",
       "--style", args.style]
if args.preset:
    cmd += ["--preset", args.preset]
elif args.fx:
    cmd += ["--fx", args.fx]
if not args.no_fast:
    cmd += ["--fast"]
cmd += ["--chunk-size", str(args.chunk_size)]
if args.dtype:
    cmd += ["--dtype", args.dtype]
if args.instruct:
    cmd += ["--instruct", args.instruct]

jarvis = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

paplay = subprocess.Popen(
    ["paplay", "--raw", "--rate=24000", "--channels=1", "--format=s16le"],
    stdin=jarvis.stdout
)

jarvis.stdout.close()
paplay.wait()
jarvis.wait()

if jarvis.returncode != 0:
    err = jarvis.stderr.read().decode()
    print(f"jarvis-rs error: {err}", file=sys.stderr)
    sys.exit(1)

print(f"  ✓ {text[:60]}…", file=sys.stderr)
