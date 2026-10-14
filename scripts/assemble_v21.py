#!/usr/bin/env python3
"""Assemble refrear Unrolla V21 from V20 + regenerated clips.

Usage: python3 scripts/assemble_v21.py picks.json out.mp4

picks.json maps segment id -> {"file": path, "offset": seconds into the clip (default 0)}.
Kept V20 ranges and replaced ranges are frame-exact at 24 fps (792 frames = 33.0 s).
V20 audio is stream-copied untouched.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
V20 = ROOT / "v20" / "refrear_Unrolla_v20_brand_review.mov"
FPS = 24
W, H = 1080, 1920

# (segment id, start frame, end frame exclusive); "keep" = take V20 frames as-is
TIMELINE = [
    ("keep", 0, 180),     # 0.00-7.50  LINE / mirror / MRT
    ("R1a", 180, 222),    # 7.50-9.25
    ("R1b", 222, 262),    # 9.25-10.92
    ("R2", 262, 330),     # 10.92-13.75
    ("keep", 330, 396),   # 13.75-16.50 lens in dish
    ("R3", 396, 444),     # 16.50-18.50
    ("R4", 444, 528),     # 18.50-22.00
    ("R5", 528, 696),     # 22.00-29.00
    ("keep", 696, 792),   # 29.00-33.00 end card
]

# Gentle shared grade applied to every frame (kept + new) so the cut points sit in one look.
GRADE = "eq=contrast=0.97:saturation=0.96:gamma=1.01,curves=all='0/0.02 1/0.985'"
GRAIN = "noise=alls=3:allf=t"
CONFORM = f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"


def run(cmd):
    subprocess.run(cmd, check=True)


def mean_rgb(path, start_s, dur_s, n=6):
    """Average RGB over n frames sampled from [start_s, start_s+dur_s)."""
    acc = []
    for i in range(n):
        t = start_s + dur_s * (i + 0.5) / n
        png = ROOT / "work" / "_probe.png"
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(path),
             "-vf", "scale=270:-2", "-frames:v", "1", str(png)])
        acc.append(np.asarray(Image.open(png).convert("RGB"), dtype=np.float64).reshape(-1, 3).mean(0))
    return np.mean(acc, axis=0)


def main():
    picks = json.loads(Path(sys.argv[1]).read_text())
    out = Path(sys.argv[2])
    tmp = ROOT / "work" / "assemble"
    tmp.mkdir(parents=True, exist_ok=True)

    parts = []
    for idx, (sid, a, b) in enumerate(TIMELINE):
        n = b - a
        part = tmp / f"{idx:02d}_{sid}.mov"
        if sid == "keep":
            vf = f"trim=start_frame={a}:end_frame={b},setpts=PTS-STARTPTS,{GRADE}"
            run(["ffmpeg", "-v", "error", "-y", "-i", str(V20), "-vf", vf, "-an",
                 "-c:v", "prores_ks", "-profile:v", "3", str(part)])
        else:
            src = Path(picks[sid]["file"])
            off = float(picks[sid].get("offset", 0))
            # Match the new clip's average colour to the V20 shot it replaces (clamped, subtle).
            ref = mean_rgb(V20, a / FPS, n / FPS)
            cur = mean_rgb(src, off, n / FPS)
            gain = np.clip(ref / np.maximum(cur, 1), 0.93, 1.07)
            gain = 1 + (gain - 1) * 0.6
            mix = f"colorchannelmixer=rr={gain[0]:.4f}:gg={gain[1]:.4f}:bb={gain[2]:.4f}"
            vf = f"{CONFORM},{mix},{GRADE}"
            run(["ffmpeg", "-v", "error", "-y", "-ss", f"{off:.3f}", "-i", str(src), "-vf", vf,
                 "-frames:v", str(n), "-an", "-c:v", "prores_ks", "-profile:v", "3", str(part)])
        got = int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                                  "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(part)],
                                 capture_output=True, text=True, check=True).stdout.strip())
        if got != n:
            sys.exit(f"{part.name}: expected {n} frames, got {got}")
        print(f"{sid:5s} {a/FPS:6.2f}-{b/FPS:6.2f}s  {n:3d} frames  ok")
        parts.append(part)

    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(V20),
         "-map", "0:v", "-map", "1:a", "-vf", GRAIN, "-c:v", "libx264", "-preset", "slow", "-crf", "19",
         "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "copy", "-movflags", "+faststart", str(out)])
    print("wrote", out)


if __name__ == "__main__":
    main()
