#!/usr/bin/env python3
"""Generate a test WAV file (sine wave, 10 seconds) on Windows desktop and test playback."""
import struct, os, subprocess, sys, time

def make_sine_wav(path, duration_sec=10, rate=24000, freq=440):
    n = int(rate * duration_sec)
    samples = []
    for i in range(n):
        v = int(32767 * 0.3 * __import__('math').sin(2 * 3.14159 * freq * i / rate))
        samples.extend(struct.pack('<h', v))
    pcm = bytes(samples)
    data_size = len(pcm)
    header = struct.pack("<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE",
        b"fmt ", 16, 1, 1, rate, rate * 2, 2, 16,
        b"data", data_size)
    with open(path, "wb") as f:
        f.write(header + pcm)
    return path

# Generate to Desktop
dest = r"C:\Users\ACER\Desktop\test_sine_10s.wav"
make_sine_wav(dest, 10, 24000, 440)
size = os.path.getsize(dest)
print(f"Generated: {dest} ({size}B, {(size-44)/24000:.1f}s)")

# Test playback with SoundPlayer PlayLooping
print("\n--- Test 1: PlayLooping + Start-Sleep ---")
t0 = time.time()
subprocess.run(["powershell.exe", "-Command",
    f"$w=New-Object Media.SoundPlayer('{dest}');"
    "$w.Load();"
    "$w.PlayLooping();"
    "Start-Sleep -Seconds 10;"
    "$w.Stop();"
    "Write-Host 'DONE';"],
    timeout=30)
print(f"Returned after {time.time() - t0:.1f}s")

print("\n--- Test 2: PlayLooping + Stopwatch + DoEvents ---")
t0 = time.time()
subprocess.run(["powershell.exe", "-Command",
    "[void][System.Windows.Forms.Application]::EnableVisualStyles();"
    f"$w=New-Object Media.SoundPlayer('{dest}');"
    "$w.Load();"
    "$w.PlayLooping();"
    "$t=[Diagnostics.Stopwatch]::StartNew();"
    "while($t.ElapsedMilliseconds -lt 10000){"
    "[System.Windows.Forms.Application]::DoEvents();"
    "Start-Sleep -Milliseconds 50"
    "}"
    "$w.Stop();"
    "Write-Host 'DONE';"],
    timeout=30)
print(f"Returned after {time.time() - t0:.1f}s")

# Also test with MediaPlayer
print("\n--- Test 3: MediaPlayer (WPF) ---")
t0 = time.time()
subprocess.run(["powershell.exe", "-Command",
    "[void][System.Windows.Media.MediaPlayer]"
    f"$mp=New-Object System.Windows.Media.MediaPlayer;"
    f"$mp.Open('{dest}');"
    "Start-Sleep -Seconds 1;"
    "$mp.Play();"
    "Start-Sleep -Seconds 10;"
    "$mp.Close();"
    "Write-Host 'DONE';"],
    timeout=30)
print(f"Returned after {time.time() - t0:.1f}s")
