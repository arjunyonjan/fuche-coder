#!/usr/bin/env python3
"""
Extreme File Management — Cleanup Engine
Usage: python3 cleanup.py [--dry-run] [--force] [--analyse-only] [--wsl-compact]
"""

import os, sys, shutil, json, time, subprocess, hashlib
from pathlib import Path
from datetime import datetime

LOG_DIR = Path.home() / ".opencode"
LOG_FILE = LOG_DIR / "cleanup.log"
LOG_DIR.mkdir(parents=True, exist_ok=True)

REPORT = {"freed_bytes": 0, "deleted_files": 0, "deleted_dirs": 0, "errors": []}
DRY_RUN = False
FORCE = False

def log(msg, kind="info"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{kind.upper()}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def warn(msg):
    log(msg, "warn")

def error(msg):
    log(msg, "error")
    REPORT["errors"].append(msg)

def dry(msg):
    if DRY_RUN:
        warn(f"[DRY-RUN] Would: {msg}")

def safe_rm_file(path, desc=""):
    p = Path(path)
    if not p.exists():
        return
    size = p.stat().st_size
    if size > 100 * 1024 * 1024 and not FORCE:
        ans = input(f"  Confirm delete {desc} ({size/1024/1024:.0f}MB)? [y/N] ")
        if ans.lower() != "y":
            warn(f"Skipped {p.name} (user declined)")
            return
    if DRY_RUN:
        dry(f"delete file {p} ({size/1024/1024:.0f}MB)")
        REPORT["freed_bytes"] += size
        REPORT["deleted_files"] += 1
        return
    try:
        p.unlink()
        REPORT["freed_bytes"] += size
        REPORT["deleted_files"] += 1
        log(f"Deleted {p.name} ({size/1024/1024:.0f}MB)")
    except Exception as e:
        error(f"Failed to delete {p}: {e}")

def safe_rmdir(path, desc=""):
    p = Path(path)
    if not p.exists():
        return
    size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if not DRY_RUN else 0
    if DRY_RUN:
        dry(f"delete dir {p} (~{size/1024/1024:.0f}MB)")
        REPORT["freed_bytes"] += size
        REPORT["deleted_dirs"] += 1
        return
    try:
        shutil.rmtree(p)
        REPORT["freed_bytes"] += size
        REPORT["deleted_dirs"] += 1
        log(f"Deleted dir {p.name} ({size/1024/1024:.0f}MB)")
    except Exception as e:
        error(f"Failed to delete dir {p}: {e}")

# ── Analysis ──────────────────────────────────────────────

def folder_size(path):
    p = Path(path)
    if not p.exists():
        return 0
    if os.name == "posix":
        try:
            r = subprocess.run(
                ["du", "-sb", str(p)],
                capture_output=True, text=True, timeout=10
            )
            if r.returncode == 0:
                return int(r.stdout.split()[0])
        except:
            pass
    total = 0
    try:
        for f in p.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except:
                    pass
    except:
        pass
    return total

def show_largest(limit=10):
    targets = {
        "WSL ~/.cache": Path.home() / ".cache",
        "WSL /tmp": Path("/tmp"),
        "WSL pip cache": Path.home() / ".cache" / "pip",
    }
    sizes = []
    for name, p in targets.items():
        sz = folder_size(p)
        sizes.append((sz, name, p))
    sizes.sort(reverse=True)
    print(f"\n{'─'*50}")
    print(f"{'Folder':40s} {'Size':>10s}")
    print(f"{'─'*50}")
    for sz, name, p in sizes[:limit]:
        print(f"{name:40s} {sz/1024/1024:>9.1f}MB")
    print(f"{'─'*50}\n")

# ── Cleanup Actions ───────────────────────────────────────

def clean_temp():
    log("Cleaning temp directories...")
    targets = []
    if os.name == "posix":
        targets.append(("/tmp", "/tmp"))
    win_temp = "/mnt/c/Users/ACER/AppData/Local/Temp"
    if Path(win_temp).exists():
        targets.append(("Windows Temp", win_temp))
    for name, p in targets:
        path = Path(p)
        if not path.exists():
            continue
        count = 0
        for item in path.iterdir():
            try:
                if item.is_file():
                    safe_rm_file(item, f"{name}/{item.name}")
                    count += 1
                elif item.is_dir():
                    safe_rmdir(item, f"{name}/{item.name}")
                    count += 1
            except:
                pass
        log(f"  Scanned {count} items in {name}")

def clean_cache():
    log("Cleaning cache directories...")
    caches = [
        (Path.home() / ".cache", "WSL ~/.cache"),
        (Path.home() / ".cache" / "pip", "pip cache"),
    ]
    uv_cache = Path.home() / ".cache" / "uv"
    if uv_cache.exists():
        caches.append((uv_cache, "uv cache"))
    for p, name in caches:
        if p.exists():
            safe_rmdir(p, name)

def rotate_logs():
    log("Rotating logs (keep last 3)...")
    log_dir = Path("/tmp") / "search-daemon.log"
    targets = [
        "/tmp/search-daemon.log",
        "/tmp/daemon.log",
        "/tmp/daemon_out.txt",
        "/tmp/auto_ingest.log",
        str(Path.home() / ".opencode" / "cleanup.log"),
    ]
    for p in targets:
        f = Path(p)
        if not f.exists():
            continue
        for i in range(3, 0, -1):
            old = f.with_name(f"{f.name}.{i}.gz") if i > 0 else f
            new = f.with_name(f"{f.name}.{i+1}.gz")
            if old.exists():
                old.rename(new)
        import gzip
        with open(f, "rb") as src:
            with gzip.open(f"{f}.1.gz", "wb") as dst:
                dst.write(src.read())
        if not DRY_RUN:
            f.write_text("")
        log(f"  Rotated {f.name}")

def empty_trash():
    log("Emptying trash...")
    trash_linux = Path.home() / ".local/share/Trash"
    if trash_linux.exists():
        safe_rmdir(trash_linux / "files", "Linux Trash/files")
        safe_rmdir(trash_linux / "info", "Linux Trash/info")

def prune_docker():
    log("Pruning Docker unused volumes...")
    dry("docker system prune -f --volumes")
    if not DRY_RUN:
        subprocess.run(
            "docker system prune -f --volumes 2>/dev/null",
            shell=True, capture_output=True
        )
        log("  Docker prune done")

def compact_wsl():
    log("Compacting WSL VHDX...")
    dry("wsl --shutdown && diskpart compact vhdx")
    if not DRY_RUN:
        try:
            subprocess.run(["wsl", "--shutdown"], capture_output=True)
            vhdx_path = os.path.expanduser(
                "~/AppData/Local/Packages/CanonicalGroupLimited.Ubuntu24.04LTS_79rhkp1fndgsc/LocalState/ext4.vhdx"
            )
            diskpart_script = f"""select vdisk file="{vhdx_path}"
compact vdisk
exit"""
            dp = Path("/tmp/compact.txt")
            dp.write_text(diskpart_script)
            subprocess.run(
                f'diskpart /s "{dp}"',
                shell=True, capture_output=True
            )
            dp.unlink()
            log("  WSL VHDX compacted")
        except Exception as e:
            error(f"WSL compaction failed: {e}")

def remove_old_kernels(keep=2):
    log("Removing old Linux kernels...")
    boot = Path("/boot")
    kernels = sorted(boot.glob("vmlinuz-*"), key=lambda f: f.stat().st_mtime, reverse=True)
    for k in kernels[keep:]:
        safe_rm_file(k, f"old kernel {k.name}")

# ── Main ──────────────────────────────────────────────────

def run_cleanup(dry_run=False, force=False, analyse_only=False, wsl_compact=False):
    global DRY_RUN, FORCE, REPORT
    DRY_RUN = dry_run
    FORCE = force
    REPORT = {"freed_bytes": 0, "deleted_files": 0, "deleted_dirs": 0, "errors": []}

    log(f"Cleanup started (dry_run={dry_run}, force={force})")

    if analyse_only or dry_run:
        show_largest()

    if not analyse_only:
        clean_temp()
        clean_cache()
        empty_trash()
        rotate_logs()
        prune_docker()
        remove_old_kernels()
        if wsl_compact:
            compact_wsl()

    freed_mb = REPORT["freed_bytes"] / 1024 / 1024
    summary = (f"Cleanup done. Freed {freed_mb:.0f}MB, "
               f"deleted {REPORT['deleted_files']} files, "
               f"{REPORT['deleted_dirs']} dirs, "
               f"{len(REPORT['errors'])} errors.")
    log(summary)

    # ntfy
    try:
        subprocess.run(
            ["curl", "-s", "-H", "Title: Fuche Cleanup",
             "-d", summary, "https://ntfy.sh/fuche2026"],
            capture_output=True, timeout=10
        )
    except:
        pass

    # TTS
    try:
        tts_text = f"Cleanup done. {freed_mb:.0f} gigabytes freed."
        subprocess.Popen(
            ["setsid", "fuche-tts", tts_text, "--speed", "1.25"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except:
        pass

    return REPORT

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Extreme File Management Cleanup")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--force", action="store_true", help="Skip confirm >100MB")
    parser.add_argument("--analyse-only", action="store_true", help="Show largest folders")
    parser.add_argument("--wsl-compact", action="store_true", help="Compact WSL VHDX")
    args = parser.parse_args()
    run_cleanup(**vars(args))
