#!/usr/bin/env python3
"""Local TTS via jarvis-rs (Qwen3-TTS-0.6B on CUDA) daemon socket."""
import argparse
import json
import os
import socket
import struct
import subprocess
import sys
import time

BINARY = os.path.expanduser("~/fuche-coder/jarvis-rs")
MODEL = os.path.expanduser("~/projects/rust-ai/jarvis-rs/models/Qwen3-TTS-12Hz-0.6B-CustomVoice")
VOICE = "ryan"
SOCKET_PATH = "/tmp/jarvis.sock"


def _pcm_wav_bytes(pcm, rate):
    data_size = len(pcm)
    header = struct.pack("<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE",
        b"fmt ", 16, 1, 1, rate, rate * 2, 2, 16,
        b"data", data_size)
    return header + pcm


def _win_temp():
    try:
        out = subprocess.run(["cmd.exe", "/c", "echo", "%USERNAME%"],
                             capture_output=True, text=True, timeout=5)
        for u in [out.stdout.strip(), "ACER", "User"]:
            base = f"/mnt/c/Users/{u}/AppData/Local/Temp"
            if os.path.isdir(base):
                return base
    except Exception:
        pass
    return "/tmp"


def _play_powershell(wav_bytes):
    tmp = os.path.join(_win_temp(), f"fuche_tts_{os.getpid()}.wav")
    with open(tmp, "wb") as f:
        f.write(wav_bytes)
    win = tmp.replace("/mnt/c/", "C:/").replace("/", "\\")
    dur_s = (len(wav_bytes) - 44) / 48000
    sleep_s = int(dur_s) + 2
    subprocess.run(["powershell.exe", "-Command",
                    "Add-Type -AssemblyName presentationCore;"
                    f"$mp=New-Object System.Windows.Media.MediaPlayer;"
                    f"$mp.Open('{win}');"
                    "Start-Sleep -Seconds 1;"
                    "$mp.Play();"
                    f"Start-Sleep -Seconds {sleep_s};"
                    "$mp.Close();"],
                   timeout=300, capture_output=True)


def _player_proc(rate):
    try:
        subprocess.run(["pactl", "info"], capture_output=True, timeout=2)
        cmd = ["paplay", "--raw", f"--rate={rate}", "--channels=1", "--format=s16le"]
    except Exception:
        cmd = ["ffplay", "-nodisp", "-autoexit", "-f", "s16le", "-ar", str(rate), "-ac", "1", "-"]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def _play_native(pcm, rate):
    proc = _player_proc(rate)
    proc.stdin.write(pcm)
    proc.stdin.close()
    t0 = time.time()
    while time.time() - t0 < 120:
        if proc.poll() is not None:
            return
        time.sleep(0.1)
    proc.kill()
    proc.wait()


def _play(pcm, rate):
    try:
        subprocess.run(["powershell.exe", "-Command", "1+1"],
                       capture_output=True, timeout=5, check=True)
        _play_powershell(_pcm_wav_bytes(pcm, rate))
        return
    except Exception:
        pass
    _play_native(pcm, rate)


parser = argparse.ArgumentParser(description="Local TTS with jarvis-rs")
parser.add_argument("text", nargs="*", help="Text to speak")
parser.add_argument("--preset", default=None, choices=["jarvis", "subtle", "heavy", "bassy", "none"],
                    help="FX preset (overrides --fx)")
parser.add_argument("--fx", default="flanger,reverb",
                    help="Comma-separated FX: flanger,chorus,reverb,tremolo")
parser.add_argument("--voice", default=VOICE, help="Voice name")
parser.add_argument("--language", default="english", help="Output language")
parser.add_argument("--style", default="calm",
                    choices=["conversational", "news", "storytelling", "cheerful", "calm"],
                    help="Expression style preset")
parser.add_argument("--chunk-size", type=int, default=2,
                    help="Stream chunk size (lower = lower latency)")
parser.add_argument("--batch", action="store_true",
                    help="Batch mode: generate all audio then play")
parser.add_argument("--ultra", action="store_true",
                    help="Sub-1s streaming: bypass daemon, run jarvis-rs directly")
parser.add_argument("--fast", action="store_true",
                    help="Fast mode: generate all audio then send")
parser.add_argument("--instruct", default=None,
                    help="Raw instruct text (overrides --style)")
parser.add_argument("--speed", type=float, default=1.2,
                    help="Speed multiplier: 1.2 = 20%% faster (WSOLA time-stretch)")
args = parser.parse_args()


def _try_daemon(text, stream_player=None):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect(SOCKET_PATH)
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        sock.close()
        return None

    sock.settimeout(120)

    request = {
        "text": text, "voice": args.voice, "language": args.language,
        "style": args.style,
    }
    if args.preset:
        request["preset"] = args.preset
    elif args.fx:
        request["fx"] = args.fx
    request["chunk_size"] = args.chunk_size
    if args.instruct:
        request["instruct"] = args.instruct
    if args.speed is not None:
        request["speed"] = args.speed

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

    if stream_player:
        sock.settimeout(None)
        written = 0
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            stream_player.stdin.write(chunk)
            written += len(chunk)
        sock.close()
        return written, sample_rate
    else:
        pcm = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            pcm += chunk
        sock.close()
        return pcm, sample_rate


text = " ".join(args.text) or sys.stdin.read().strip()
text = text.replace("fuche", "foochchay").replace("Fuche", "Foochchay").replace("FUCHE", "FOOCHCHAY")
if not text:
    print("Usage: ./tts.py [--style ...] 'text'", file=sys.stderr)
    sys.exit(1)

# --- Ultra mode: subprocess streaming (bypass daemon) ---
if args.ultra:
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        sentences = [text]
    player = None
    total_written = 0
    for sentence in sentences:
        cmd = [BINARY, "run", sentence, "--model", MODEL, "--voice", args.voice,
               "--language", args.language, "--stdout", "--style", args.style,
               "--chunk-size", "2", "--speed", str(args.speed)]
        if args.fast:
            cmd += ["--fast"]
        if args.preset:
            cmd += ["--preset", args.preset]
        elif args.fx:
            cmd += ["--fx", args.fx]
        if args.instruct:
            cmd += ["--instruct", args.instruct]
        jarvis = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if player is None:
            player = _player_proc(24000)
        while True:
            chunk = jarvis.stdout.read(4096)
            if not chunk:
                break
            player.stdin.write(chunk)
            total_written += len(chunk)
        jarvis.stdout.close()
        jarvis.wait()
    if player:
        player.stdin.close()
        player.wait()
    _dur = total_written / 48000
    print(f"  | ultra: {total_written}B, {_dur:.1f}s ({len(sentences)} sentences)", file=sys.stderr)
    print(f"  \u2713 {text[:60]}\u2026 (ultra)", file=sys.stderr)
    sys.exit(0)

# --- Batch mode: daemon request then play ---
if args.batch:
    result = _try_daemon(text)
    if result is not None:
        pcm, sample_rate = result
        _play(pcm, sample_rate)
        _dur = len(pcm) / 48000
        print(f"  | batch: {len(pcm)}B, {_dur:.1f}s", file=sys.stderr)
        print(f"  \u2713 {text[:60]}\u2026 (batch)", file=sys.stderr)
        sys.exit(0)
    # fallback to subprocess
    cmd = [BINARY, "run", text, "--model", MODEL, "--voice", args.voice,
           "--language", args.language, "--stdout", "--style", args.style,
           "--chunk-size", str(args.chunk_size), "--speed", str(args.speed)]
    if args.fast:
        cmd += ["--fast"]
    if args.preset:
        cmd += ["--preset", args.preset]
    elif args.fx:
        cmd += ["--fx", args.fx]
    if args.instruct:
        cmd += ["--instruct", args.instruct]
    jarvis = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    raw_pcm = jarvis.stdout.read()
    jarvis.stdout.close()
    jarvis.wait()
    if jarvis.returncode != 0:
        err = jarvis.stderr.read().decode()
        print(f"jarvis-rs error: {err}", file=sys.stderr)
        sys.exit(1)
    _play(raw_pcm, 24000)
    print(f"  \u2713 {text[:60]}\u2026 (subprocess)", file=sys.stderr)
    sys.exit(0)

# --- Default: daemon streaming ---
player = _player_proc(24000)
result = _try_daemon(text, stream_player=player)
if result is not None:
    written, sr = result
    player.stdin.close()
    player.wait()
    _dur = written / 48000
    print(f"  | qwen: {written}B, {_dur:.1f}s", file=sys.stderr)
    print(f"  \u2713 {text[:60]}\u2026 (qwen)", file=sys.stderr)
    sys.exit(0)
player.stdin.close()
player.wait()

# Daemon down — fallback to subprocess
cmd = [BINARY, "run", text, "--model", MODEL, "--voice", args.voice,
       "--language", args.language, "--stdout", "--style", args.style,
       "--chunk-size", "2", "--speed", str(args.speed)]
if args.fast:
    cmd += ["--fast"]
if args.preset:
    cmd += ["--preset", args.preset]
elif args.fx:
    cmd += ["--fx", args.fx]
if args.instruct:
    cmd += ["--instruct", args.instruct]
jarvis = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
player = _player_proc(24000)
total = 0
while True:
    chunk = jarvis.stdout.read(4096)
    if not chunk:
        break
    player.stdin.write(chunk)
    total += len(chunk)
player.stdin.close()
player.wait()
_dur = total / 48000
print(f"  | subprocess: {total}B, {_dur:.1f}s", file=sys.stderr)
print(f"  \u2713 {text[:60]}\u2026 (qwen-subprocess)", file=sys.stderr)
