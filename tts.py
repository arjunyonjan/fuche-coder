#!/usr/bin/env python3
"""Local TTS via jarvis-rs (Qwen3-TTS-0.6B on CUDA) → stream to paplay."""
import argparse
import os
import subprocess
import sys

JARVIS_DIR = os.path.expanduser("~/projects/rust-ai/jarvis-rs")
JARVIS = os.path.join(JARVIS_DIR, "target/release/jarvis-rs")
MODEL = os.path.join(JARVIS_DIR, "models/Qwen3-TTS-12Hz-0.6B-CustomVoice")
VOICE = "ryan"

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
parser.add_argument("--fast", action="store_true",
                    help="Greedy decoding (faster, lower quality)")
parser.add_argument("--chunk-size", type=int, default=8,
                    help="Stream chunk size (lower = lower latency)")
parser.add_argument("--dtype", default="f32", choices=["f32", "f16"],
                    help="Model precision (f16 needs AC power)")
parser.add_argument("--instruct", default=None,
                    help="Raw instruct text (overrides --style)")
args = parser.parse_args()

text = " ".join(args.text) or sys.stdin.read().strip()
if not text:
    print("Usage: ./tts.py [--style conversational|news|...] 'text'", file=sys.stderr)
    sys.exit(1)

cmd = [JARVIS, "run", text, "--model", MODEL, "--voice", args.voice, "--stdout",
       "--style", args.style]
if args.preset:
    cmd += ["--preset", args.preset]
elif args.fx:
    cmd += ["--fx", args.fx]
if args.fast:
    cmd += ["--fast"]
if args.chunk_size != 8:
    cmd += ["--chunk-size", str(args.chunk_size)]
if args.dtype != "f32":
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
