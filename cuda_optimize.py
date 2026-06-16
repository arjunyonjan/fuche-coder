#!/usr/bin/env python3
import subprocess
import sys
import os

def check_nvidia_smi():
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,compute_cap", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        return None

def check_torch_cuda():
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_memory / 1024**3
            cc = torch.cuda.get_device_capability(0)
            return name, vram, cc
    except ImportError:
        pass
    return None

def check_ollama_gpu():
    try:
        result = subprocess.run(
            ["ollama", "ps"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout if result.returncode == 0 else None
    except Exception:
        return None

def optimize_model(model_name):
    print(f"  Device map: cuda:0")
    print(f"  Data type:  float16")
    print(f"  Options:    --num-gpu 999 --num-thread 4")
    print(f"\n  Run with:\n    ollama run {model_name}")
    print(f"\n  Or for best perf:\n    OLLAMA_LOAD_IN_4BIT=1 OLLAMA_FLASH_ATTENTION=1 ollama run {model_name}")

if __name__ == "__main__":
    print("🔍 GPU Diagnostics\n")

    smi = check_nvidia_smi()
    if smi:
        print(f"✅ nvidia-smi: {smi}")
    else:
        print("❌ nvidia-smi: not detected")

    torch_info = check_torch_cuda()
    if torch_info:
        name, vram, cc = torch_info
        print(f"✅ PyTorch CUDA: {name} ({vram:.1f} GB, Compute {cc[0]}.{cc[1]})")
        if cc[0] >= 8:
            print("  ✅ Flash Attention compatible")
        if cc[0] >= 9:
            print("  ✅ Flash Attention 3 ready (RTX 50 series)")
    else:
        print("❌ PyTorch CUDA: not available")

    ollama = check_ollama_gpu()
    if ollama:
        print(f"✅ Ollama GPU: enabled")
        print(f"   {ollama.strip()}")
    else:
        print("❌ Ollama GPU: no models loaded or not detected")

    print("\n🚀 Optimization Recommendations")
    print("  Set: OLLAMA_FLASH_ATTENTION=1")
    print("  Set: OLLAMA_LOAD_IN_4BIT=1 (for low VRAM)")
    print("  Set: OLLAMA_NUM_GPU=999")
    print("  Or:  export OLLAMA_FLASH_ATTENTION=1 OLLAMA_LOAD_IN_4BIT=1 && ollama serve\n")

    if len(sys.argv) > 1:
        optimize_model(sys.argv[1])
