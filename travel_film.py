"""
AI Travel Film — Narrative-driven travel video generator
========================================================
Turn raw travel footage into cinematic short films with zero manual editing.

Features:
  - Motion & brightness analysis for intelligent clip selection
  - 5-act narrative structure (Hook → Departure → Journey → Peak → Epilogue)
  - Crossfade transitions between clips
  - Per-act color grading with curves
  - BGM with sidechain ducking + loudnorm -16 LUFS
  - TTS narration via edge-tts
  - 16:9 horizontal and 9:16 vertical output

Usage:
  python travel_film.py                        # Build with default config
  python travel_film.py --config my_trip.json  # Build with custom config
  python travel_film.py analyze                # Analyze sources only
  python travel_film.py --vertical             # 9:16 vertical output

Requirements:
  - ffmpeg & ffprobe in PATH
  - Python 3.9+
  - edge-tts (optional, for narration): pip install edge-tts

License: MIT
"""
import subprocess, os, sys, json, shutil, asyncio, re, argparse
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

__version__ = "2.0.0"

# ============================================================
# Default Configuration (override via --config JSON file)
# ============================================================
DEFAULT_CONFIG = {
    "source_dirs": [
        # Each entry: [path, type, label]
        # type: "aerial" (drone), "action" (action cam), "camera" (handheld/tripod)
        # Example:
        # ["~/Videos/drone", "aerial", "DJI Drone"],
        # ["~/Videos/gopro", "action", "GoPro"],
        # ["~/Videos/camera", "camera", "Sony A7"],
    ],
    "output_dir": "./output",
    "bgm_path": "",  # Path to BGM file. Empty = generate synthetic BGM
    "trip_dates": {
        # "2024-07": {"name": "Summer Road Trip", "mood": "adventurous"},
    },
    "narrative": [
        {
            "act": "hook", "label": "Hook",
            "duration_target": 5, "n_clips": 1, "speed": 0.35,
            "prefer_type": "aerial", "prefer_motion": [10, 40],
            "color_grade": "curves=r='0/0 0.15/0.08 0.5/0.45 0.85/0.9 1/1':g='0/0 0.15/0.1 0.5/0.5 0.85/0.92 1/1':b='0/0 0.15/0.15 0.5/0.55 0.85/0.88 1/1',eq=contrast=1.12:saturation=1.25",
            "narration": None, "subtitle": None,
        },
        {
            "act": "departure", "label": "Departure",
            "duration_target": 25, "n_clips": 4, "speed": 1.0,
            "prefer_type": "aerial", "prefer_motion": [20, 60],
            "color_grade": "eq=contrast=1.05:saturation=1.15:brightness=0.02",
            "narration": "Some places can't be captured by photos or videos. You just have to go there yourself.",
            "subtitle": "Some places can't be captured\nby photos or videos.\nYou just have to go there yourself.",
        },
        {
            "act": "journey", "label": "Journey",
            "duration_target": 35, "n_clips": 7, "speed": 1.0,
            "prefer_type": "action", "prefer_motion": [30, 80],
            "stabilize": True,
            "color_grade": "eq=contrast=1.1:saturation=1.1:brightness=0.01",
            "narration": "When you stop rushing, you realize the wind has been talking all along.",
            "subtitle": "When you stop rushing,\nyou realize the wind\nhas been talking all along.",
        },
        {
            "act": "peak", "label": "Peak",
            "duration_target": 50, "n_clips": 6, "speed": 0.4,
            "prefer_type": "camera", "prefer_motion": [15, 50],
            "color_grade": "curves=r='0/0 0.3/0.25 0.6/0.65 1/1':g='0/0 0.3/0.28 0.6/0.68 1/1':b='0/0 0.3/0.22 0.6/0.6 1/1',eq=contrast=1.08:saturation=1.3:brightness=0.03",
            "narration": "All the rushing, all the waiting — it was all for this moment.",
            "subtitle": "All the rushing, all the waiting —\nit was all for this moment.",
        },
        {
            "act": "epilogue", "label": "Epilogue",
            "duration_target": 25, "n_clips": 3, "speed": 0.5,
            "prefer_type": "aerial", "prefer_motion": [5, 30],
            "color_grade": "eq=contrast=1.03:saturation=1.2:brightness=0.04",
            "narration": "When you come back, you realize it wasn't the scenery that changed. It was you.",
            "subtitle": "When you come back, you realize\nit wasn't the scenery that changed.\nIt was you.",
        },
    ],
    "specs": {
        "horizontal": {"w": 1920, "h": 1080},
        "vertical": {"w": 1080, "h": 1920},
    },
    "max_source_dur": 300,
    "min_source_dur": 5,
    "crf": 17,
    "crossfade_dur": 0.6,
    "tts_voice": "en-US-GuyNeural",  # Change to zh-CN-YunxiNeural for Chinese
    "reclassify_rules": {
        # filename patterns that should be reclassified
        # e.g., gimbal footage in aerial dir should be "action"
        "dji_mimo": "action",
    },
}

# ============================================================
# FFmpeg utilities
# ============================================================
def ff(cmd, timeout=300, quiet=True):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        if not quiet and r.returncode != 0:
            print(f"    stderr: {r.stderr[:300]}")
        return r
    except subprocess.TimeoutExpired:
        return None

def probe_format(path):
    r = ff(["ffprobe", "-v", "error", "-show_entries", "format=duration,size",
            "-of", "json", str(path)], 15)
    if r and r.stdout:
        try: return json.loads(r.stdout).get("format", {})
        except: pass
    return {}

def probe_stream(path):
    r = ff(["ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate,codec_name",
            "-of", "json", str(path)], 15)
    if r and r.stdout:
        try:
            streams = json.loads(r.stdout).get("streams", [])
            return streams[0] if streams else {}
        except: pass
    return {}

def probe_audio(path):
    r = ff(["ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_name",
            "-of", "json", str(path)], 15)
    if r and r.stdout:
        try:
            streams = json.loads(r.stdout).get("streams", [])
            return streams[0] if streams else None
        except: pass
    return None

def get_duration(path):
    fmt = probe_format(path)
    try: return float(fmt.get("duration", 0))
    except: return 0

def parse_fps(rate_str):
    try:
        if "/" in str(rate_str):
            n, d = str(rate_str).split("/")
            return int(n) / int(d) if int(d) else 30
        return float(rate_str)
    except: return 30

def fmt_srt_time(s):
    h, rem = divmod(s, 3600)
    m, rem = divmod(rem, 60)
    sec, ms = divmod(rem, 1)
    return f"{int(h):02d}:{int(m):02d}:{int(sec):02d},{int(ms*1000):03d}"

# ============================================================
# Phase 0: Deep source analysis
# ============================================================
def analyze_motion(path, samples=5):
    dur = get_duration(path)
    if dur < 3: return 50
    scores = []
    for i in range(samples):
        t = dur * (i + 1) / (samples + 1)
        r = ff(["ffmpeg", "-ss", str(t), "-i", str(path),
                "-vframes", "2", "-vf", "scale=160:90,format=gray",
                "-f", "rawvideo", "-"], timeout=15)
        if r and r.stdout:
            raw = r.stdout.encode("latin-1") if isinstance(r.stdout, str) else r.stdout
            frame_size = 160 * 90
            if len(raw) >= frame_size * 2:
                f1, f2 = raw[:frame_size], raw[frame_size:frame_size*2]
                diff = sum(abs(a - b) for a, b in zip(f1, f2)) / frame_size
                scores.append(min(100, diff * 2))
    return sum(scores) / len(scores) if scores else 50

def analyze_brightness(path):
    dur = get_duration(path)
    r = ff(["ffmpeg", "-ss", str(dur * 0.4), "-i", str(path),
            "-vframes", "1", "-vf", "scale=80:45,format=gray",
            "-f", "rawvideo", "-"], timeout=15)
    if r and r.stdout:
        raw = r.stdout.encode("latin-1") if isinstance(r.stdout, str) else r.stdout
        if len(raw) > 100: return sum(raw) / len(raw)
    return 128

def extract_date_from_name(name):
    m = re.search(r'(\d{4})(\d{2})(\d{2})', name)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None

def scan_sources(cfg, cache_path=None):
    if cache_path and Path(cache_path).exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("version") == 2 and cached.get("sources"):
                print(f"    (using cache: {len(cached['sources'])} sources)")
                return cached["sources"]
        except: pass

    print("    First-time analysis, this takes 2-3 minutes...")
    all_sources = []
    seen = set()
    reclassify = cfg.get("reclassify_rules", {})
    trip_dates = cfg.get("trip_dates", {})

    for entry in cfg.get("source_dirs", []):
        if len(entry) < 3: continue
        base_dir, src_type, src_label = Path(entry[0]).expanduser(), entry[1], entry[2]
        if not base_dir.exists():
            print(f"    [WARN] {src_label} dir not found: {base_dir}")
            continue

        for f in sorted(base_dir.glob("*.[mM][pP]4")):
            key = str(f).lower()
            if key in seen: continue
            seen.add(key)
            name = f.name.lower()
            if "proxy" in name or "540p" in name or "cache" in name: continue

            # Reclassify based on filename patterns
            actual_type = src_type
            for pattern, retype in reclassify.items():
                if pattern.lower() in name:
                    actual_type = retype
                    break

            dur = get_duration(f)
            if dur < cfg.get("min_source_dur", 5) or dur > cfg.get("max_source_dur", 300):
                continue
            stream = probe_stream(f)
            w, h = int(stream.get("width", 0)), int(stream.get("height", 0))
            fps = parse_fps(stream.get("r_frame_rate", "30/1"))
            if w < 1280: continue

            date = extract_date_from_name(f.name)
            trip = trip_dates.get(date[:7]) if date else None

            all_sources.append({
                "path": str(f), "name": f.name, "type": actual_type,
                "dur": round(dur, 2), "w": w, "h": h, "fps": round(fps, 1),
                "is_4k": w >= 3840, "is_vertical": h > w,
                "has_audio": probe_audio(f) is not None,
                "date": date,
                "trip_name": trip["name"] if trip else None,
                "size_mb": round(f.stat().st_size / (1024*1024), 1),
            })

    print(f"    Base scan: {len(all_sources)} sources")

    # Parallel motion + brightness analysis
    print(f"    Motion analysis...")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(analyze_motion, s["path"], 3): i for i, s in enumerate(all_sources)}
        for fut in as_completed(futs):
            try: all_sources[futs[fut]]["motion_score"] = round(fut.result(), 1)
            except: all_sources[futs[fut]]["motion_score"] = 50

    print(f"    Brightness analysis...")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(analyze_brightness, s["path"]): i for i, s in enumerate(all_sources)}
        for fut in as_completed(futs):
            try: all_sources[futs[fut]]["brightness"] = round(fut.result(), 1)
            except: all_sources[futs[fut]]["brightness"] = 128

    # Composite scoring
    for s in all_sources:
        score = 0
        if s.get("trip_name"): score += 50
        if s["is_4k"]: score += 15
        if s["fps"] > 60: score += 15
        motion = s.get("motion_score", 50)
        if 20 < motion < 70: score += 10
        if s["type"] == "aerial": score += 10
        if 10 < s["dur"] < 60: score += 5
        s["composite_score"] = score

    all_sources.sort(key=lambda x: x["composite_score"], reverse=True)

    if cache_path:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"version": 2, "timestamp": datetime.now().isoformat(),
                       "sources": all_sources}, f, ensure_ascii=False, indent=2)
    return all_sources

# ============================================================
# Phase 1: Intelligent clip selection
# ============================================================
def select_clips(sources, narrative):
    used = set()
    selections = []
    for act in narrative:
        prefer = act["prefer_type"]
        motion_range = act.get("prefer_motion", [0, 100])
        n = act["n_clips"]
        clip_dur = act["duration_target"] / n

        pool = [s for s in sources if s["path"] not in used and not s.get("is_vertical")]

        def score(s):
            sc = s.get("composite_score", 0)
            if s["type"] == prefer: sc += 80
            motion = s.get("motion_score", 50)
            lo, hi = motion_range
            if lo <= motion <= hi: sc += 25
            else: sc += max(0, 25 - abs(motion - (lo+hi)/2))
            return sc

        pool.sort(key=score, reverse=True)
        for c in pool[:n]:
            used.add(c["path"])
            speed = act["speed"]
            fps = c.get("fps", 30)
            if fps > 60 and speed < 1.0:
                esp = max(30.0 / fps, speed)
            else:
                esp = speed
            raw_needed = min(clip_dur * esp, c["dur"] - 2)
            ss = max(1, c["dur"] * 0.35)
            if ss + raw_needed > c["dur"] - 1:
                ss = max(0.5, c["dur"] - raw_needed - 1)

            selections.append({
                **c, "act": act["act"], "act_label": act["label"],
                "clip_dur": round(clip_dur, 2), "speed": speed,
                "effective_speed": round(esp, 3),
                "raw_needed": round(raw_needed, 2), "ss": round(ss, 2),
                "color_grade": act.get("color_grade", ""),
                "stabilize": act.get("stabilize", False),
            })
    return selections

# ============================================================
# Phase 2: Extract clips
# ============================================================
def extract_clip(sel, idx, spec, clips_dir, crf=17):
    w, h = spec["w"], spec["h"]
    out = clips_dir / f"clip_{idx:02d}_{sel['act']}.mp4"
    vf = []
    vf.append(f"scale={w}:{h}:force_original_aspect_ratio=decrease")
    vf.append(f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black")
    if sel.get("stabilize"):
        vf.append("dejudder")
        vf.append("unsharp=5:5:0.8:5:5:0.4")
    esp = sel["effective_speed"]
    if abs(esp - 1.0) > 0.01:
        vf.append(f"setpts={1.0/esp}*PTS")
    vf.append("fps=30")
    if sel.get("color_grade"):
        vf.append(sel["color_grade"])
    target = sel["clip_dur"]
    vf.append(f"fade=t=in:d=0.3")
    vf.append(f"fade=t=out:st={max(0.5, target-0.3)}:d=0.3")

    r = ff(["ffmpeg", "-y", "-ss", str(sel["ss"]),
            "-t", str(sel["raw_needed"]),
            "-i", sel["path"],
            "-vf", ",".join(vf),
            "-c:v", "libx264", "-crf", str(crf), "-preset", "fast",
            "-pix_fmt", "yuv420p", "-an", str(out)], timeout=240)
    if r and r.returncode == 0 and out.exists() and out.stat().st_size > 1000:
        return str(out), round(get_duration(out), 2)
    return None, 0

# ============================================================
# Phase 3: Generate synthetic BGM
# ============================================================
def generate_bgm(total_dur, work_dir):
    bgm_path = work_dir / "bgm_synthetic.mp3"
    ratios = [0.04, 0.18, 0.25, 0.35, 0.18]
    configs = [
        {"freqs": [(55, 0.12), (110, 0.06)], "noise": 0.015},
        {"freqs": [(80, 0.10), (160, 0.08), (320, 0.04)], "noise": 0.02},
        {"freqs": [(100, 0.08), (200, 0.10), (400, 0.06)], "noise": 0.025},
        {"freqs": [(120, 0.12), (240, 0.10), (480, 0.08), (960, 0.04)], "noise": 0.03},
        {"freqs": [(65, 0.10), (130, 0.06), (260, 0.03)], "noise": 0.012},
    ]
    segments = []
    for i, (ratio, cfg) in enumerate(zip(ratios, configs)):
        dur = total_dur * ratio
        seg = work_dir / f"bgm_seg_{i}.wav"
        inputs, filters = [], []
        for j, (freq, vol) in enumerate(cfg["freqs"]):
            inputs.append(f"sine=frequency={freq}:duration={dur}")
            filters.append(f"[{j}:a]volume={vol}[t{j}]")
        ni = len(cfg["freqs"])
        inputs.append(f"anoisesrc=d={dur}:c=pink:a={cfg['noise']}")
        filters.append(f"[{ni}:a]lowpass=f=1500[n]")
        mix = "".join(f"[t{j}]" for j in range(ni)) + "[n]"
        filters.append(f"{mix}amix=inputs={ni+1}:duration=longest,"
                       f"afade=t=in:d={min(2,dur*0.15)},"
                       f"afade=t=out:st={dur-min(2,dur*0.15)}:d={min(2,dur*0.15)}[out]")
        cmd = ["ffmpeg", "-y"]
        for inp in inputs: cmd.extend(["-f", "lavfi", "-i", inp])
        cmd.extend(["-filter_complex", ";".join(filters), "-map", "[out]",
                     "-c:a", "pcm_s16le", str(seg)])
        ff(cmd, timeout=60)
        if seg.exists(): segments.append(str(seg))

    if not segments: return None
    cf = work_dir / "bgm_concat.txt"
    with open(cf, "w") as f:
        for s in segments: f.write(f"file '{s}'\n")
    ff(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(cf),
        "-c:a", "libmp3lame", "-b:a", "192k", "-af", "lowpass=f=2500,highpass=f=40",
        str(bgm_path)], timeout=60)
    return str(bgm_path) if bgm_path.exists() else None

# ============================================================
# Phase 4: TTS narration
# ============================================================
def generate_narrations(narrative, work_dir, voice):
    narr_files = {}
    try: import edge_tts
    except ImportError:
        print("    [INFO] edge-tts not installed, skipping narration")
        return narr_files

    async def _gen():
        for act in narrative:
            if not act.get("narration"): continue
            out = work_dir / f"narr_{act['act']}.mp3"
            try:
                c = edge_tts.Communicate(act["narration"], voice, rate="-5%")
                await c.save(str(out))
                if out.exists() and out.stat().st_size > 1000:
                    narr_files[act["act"]] = str(out)
                    print(f"      {act['act']}: {get_duration(out):.1f}s")
            except Exception as e:
                print(f"      {act['act']}: [FAIL] {e}")
    asyncio.run(_gen())
    return narr_files

# ============================================================
# Phase 5: Assembly
# ============================================================
def build_act_video(act_info, clip_paths, narr_path, work_dir, xfade_dur=0.6):
    act_name = act_info["act"]
    if len(clip_paths) == 1:
        act_video = work_dir / f"act_{act_name}.mp4"
        shutil.copy2(clip_paths[0], act_video)
    else:
        # Crossfade chain
        n = len(clip_paths)
        durs = [get_duration(p) for p in clip_paths]
        offsets = []
        cum = 0
        for i in range(n - 1):
            offsets.append(cum + durs[i] - xfade_dur)
            cum = offsets[-1]

        parts = []
        if n == 2:
            parts.append(f"[0:v][1:v]xfade=transition=fade:duration={xfade_dur}:offset={offsets[0]}[vout]")
        else:
            prev = "[0:v]"
            for i in range(1, n):
                out = f"[v{i}]" if i < n-1 else "[vout]"
                parts.append(f"{prev}[{i}:v]xfade=transition=fade:duration={xfade_dur}:offset={offsets[i-1]}{out}")
                prev = out

        act_video = work_dir / f"act_{act_name}.mp4"
        cmd = ["ffmpeg", "-y"] + [x for p in clip_paths for x in ["-i", p]]
        cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]",
                "-c:v", "libx264", "-crf", "17", "-preset", "fast",
                "-pix_fmt", "yuv420p", str(act_video)]
        ff(cmd, timeout=180)

        if not act_video.exists():
            # Fallback: simple concat
            cf = work_dir / f"concat_{act_name}.txt"
            with open(cf, "w") as f:
                for p in clip_paths: f.write(f"file '{os.path.relpath(p, work_dir)}'\n")
            ff(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(cf),
                "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p",
                str(act_video)], timeout=120)

    if not act_video.exists(): return None, 0, 0
    act_dur = get_duration(act_video)

    # Add audio track (narration or silence)
    act_audio = work_dir / f"act_{act_name}_a.mp4"
    narr_dur = 0
    if narr_path and Path(narr_path).exists():
        narr_dur = get_duration(narr_path)
        ff(["ffmpeg", "-y", "-i", str(act_video), "-i", narr_path,
            "-filter_complex",
            f"[1:a]adelay=1500|1500,volume=1.2[narr];"
            f"anullsrc=r=44100:cl=stereo,atrim=duration={act_dur}[sil];"
            f"[sil][narr]amix=inputs=2:duration=first[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", str(act_audio)], timeout=60)
    else:
        ff(["ffmpeg", "-y", "-i", str(act_video),
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", str(act_audio)], timeout=60)

    if act_audio.exists():
        return str(act_audio), get_duration(act_audio), narr_dur
    return str(act_video), act_dur, 0

def assemble_final(act_results, bgm_path, spec, output_path, work_dir, cfg):
    w, h = spec["w"], spec["h"]
    crf = cfg.get("crf", 17)
    breath_dur = 0.6

    parts = []
    for i, (path, dur, act, ndur) in enumerate(act_results):
        parts.append(path)
        if i < len(act_results) - 1:
            bp = str(work_dir / f"breath_{i}.mp4")
            ff(["ffmpeg", "-y",
                "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:d={breath_dur}:r=30",
                "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-t", str(breath_dur), bp])
            if Path(bp).exists(): parts.append(bp)

    cf = work_dir / "final_concat.txt"
    with open(cf, "w") as f:
        for p in parts: f.write(f"file '{os.path.relpath(p, work_dir)}'\n")

    raw = work_dir / "raw_final.mp4"
    ff(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(cf),
        "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
        "-c:a", "aac", "-b:a", "192k", str(raw)], timeout=300)

    if not raw.exists():
        print("  [ERR] Final concat failed")
        return None

    total_dur = get_duration(raw)
    print(f"    Total: {total_dur:.1f}s")

    # Mix BGM
    if bgm_path and Path(bgm_path).exists():
        bgm_dur = get_duration(bgm_path)
        bgm_filter = (f"[1:a]atrim=duration={total_dur},volume=0.20,"
                       f"afade=t=in:d=2,afade=t=out:st={total_dur-3}:d=3[bgm]")
        if bgm_dur < total_dur:
            bgm_filter = (f"[1:a]aloop=loop=3:size=2e+09,atrim=duration={total_dur},"
                           f"volume=0.20,afade=t=in:d=2,afade=t=out:st={total_dur-3}:d=3[bgm]")

        r = ff(["ffmpeg", "-y", "-i", str(raw), "-i", bgm_path,
            "-filter_complex",
            f"[0:v]fade=t=in:d=1.5,fade=t=out:st={total_dur-2.5}:d=2.5[vout];"
            f"{bgm_filter};"
            f"[0:a][bgm]amix=inputs=2:duration=first,"
            f"loudnorm=I=-16:LRA=11:TP=-1.5[aout]",
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
            "-c:a", "aac", "-b:a", "192k", "-shortest",
            "-metadata", "title=AI Travel Film",
            str(output_path)], timeout=300, quiet=False)

        if not output_path.exists():
            # Fallback without loudnorm
            ff(["ffmpeg", "-y", "-i", str(raw), "-i", bgm_path,
                "-filter_complex",
                f"[0:v]fade=t=in:d=1.5,fade=t=out:st={total_dur-2.5}:d=2.5[vout];"
                f"{bgm_filter};"
                f"[0:a][bgm]amix=inputs=2:duration=first[aout]",
                "-map", "[vout]", "-map", "[aout]",
                "-c:v", "libx264", "-crf", str(crf),
                "-c:a", "aac", "-b:a", "192k", "-shortest",
                str(output_path)], timeout=300)
    else:
        shutil.copy2(str(raw), str(output_path))

    if not output_path.exists():
        print("  [ERR] Final file not created")
        return None

    # Generate SRT
    srt_entries = []
    cursor = 0.0
    narrative = cfg.get("narrative", [])
    for path, adur, act_name, ndur in act_results:
        sub = None
        for act in narrative:
            if act["act"] == act_name: sub = act.get("subtitle"); break
        if sub and ndur > 0:
            srt_entries.append((len(srt_entries)+1, cursor+1.5, cursor+1.5+ndur+0.5, sub))
        cursor += adur + breath_dur

    srt_path = output_path.with_suffix(".srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        for idx, s, e, text in srt_entries:
            f.write(f"{idx}\n{fmt_srt_time(s)} --> {fmt_srt_time(e)}\n{text}\n\n")

    # Cover image
    cover = output_path.with_name(output_path.stem + "_cover.jpg")
    ff(["ffmpeg", "-y", "-ss", str(total_dur * 0.45), "-i", str(output_path),
        "-vframes", "1", "-q:v", "2", str(cover)])

    return total_dur, len(srt_entries)

# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="AI Travel Film Generator")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "analyze"],
                        help="build (default) or analyze sources only")
    parser.add_argument("--config", type=str, default="", help="Path to config JSON file")
    parser.add_argument("--vertical", action="store_true", help="Output 9:16 vertical video")
    args = parser.parse_args()

    # Load config
    cfg = dict(DEFAULT_CONFIG)
    if args.config and Path(args.config).exists():
        with open(args.config, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        cfg.update(user_cfg)

    if not cfg["source_dirs"]:
        print("No source directories configured!")
        print("Create a config file (see example_config.json) and run:")
        print("  python travel_film.py --config my_trip.json")
        return

    spec_key = "vertical" if args.vertical else "horizontal"
    spec = cfg["specs"][spec_key]
    output_dir = Path(cfg["output_dir"]).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir / "_work"
    clips_dir = output_dir / "clips"
    work_dir.mkdir(exist_ok=True)
    clips_dir.mkdir(exist_ok=True)
    cache_path = output_dir / "source_analysis.json"

    t0 = datetime.now()
    suffix = "_vertical" if args.vertical else ""
    output_path = output_dir / f"travel_film{suffix}.mp4"

    print(f"\n{'='*60}")
    print(f"  AI Travel Film v{__version__}")
    print(f"  Output: {spec['w']}x{spec['h']}")
    print(f"{'='*60}\n")

    # Phase 0
    print("  [1/7] Analyzing sources...")
    sources = scan_sources(cfg, cache_path)
    types = {}
    for s in sources: types[s["type"]] = types.get(s["type"], 0) + 1
    print(f"    {len(sources)} sources: {types}")

    if args.command == "analyze":
        print(f"\n  Analysis saved to {cache_path}")
        return

    if len(sources) < 10:
        print("  [ERR] Need at least 10 source clips")
        return

    # Phase 1
    narrative = cfg.get("narrative", DEFAULT_CONFIG["narrative"])
    print(f"\n  [2/7] Selecting clips...")
    selections = select_clips(sources, narrative)
    for s in selections:
        tag = {"aerial":"[air]","camera":"[cam]","action":"[act]"}.get(s["type"],"[???]")
        print(f"    {tag} [{s['act_label']}] {s['w']}x{s['h']}@{s['fps']:.0f}fps "
              f"->{s['clip_dur']:.1f}s @{s['effective_speed']:.2f}x  {s['name'][:30]}")

    # Phase 2
    print(f"\n  [3/7] Extracting {len(selections)} clips...")
    clips_by_act = {}
    for i, sel in enumerate(selections):
        print(f"    [{i+1}/{len(selections)}] {sel['act_label']} ...", end=" ", flush=True)
        path, dur = extract_clip(sel, i, spec, clips_dir, cfg.get("crf", 17))
        if path:
            clips_by_act.setdefault(sel["act"], []).append(path)
            print(f"OK {dur:.1f}s / {Path(path).stat().st_size/(1024*1024):.1f}MB")
        else:
            print("FAIL")

    total_clips = sum(len(v) for v in clips_by_act.values())
    if total_clips < 5:
        print("  [ERR] Not enough clips extracted")
        return

    # Phase 3
    print(f"\n  [4/7] Generating narration...")
    narr_files = generate_narrations(narrative, work_dir, cfg.get("tts_voice", "en-US-GuyNeural"))

    # Phase 4
    xfade = cfg.get("crossfade_dur", 0.6)
    print(f"\n  [5/7] Building narrative segments...")
    act_results = []
    for act in narrative:
        paths = clips_by_act.get(act["act"], [])
        if not paths:
            print(f"    [SKIP] {act['label']}: no clips")
            continue
        path, dur, ndur = build_act_video(act, paths, narr_files.get(act["act"]), work_dir, xfade)
        if path:
            act_results.append((path, dur, act["act"], ndur))
            print(f"    {act['label']}: {dur:.1f}s / {len(paths)} clips"
                  + (f" / narration {ndur:.1f}s" if ndur else ""))

    if not act_results:
        print("  [ERR] No segments built")
        return

    # Phase 5: BGM
    est_total = sum(d for _,d,_,_ in act_results) + 0.6*(len(act_results)-1)
    bgm = cfg.get("bgm_path", "")
    if bgm and Path(bgm).expanduser().exists():
        bgm_path = str(Path(bgm).expanduser())
        print(f"\n  [6/7] BGM: {Path(bgm_path).name}")
    else:
        print(f"\n  [6/7] Generating synthetic BGM ({est_total:.0f}s)...")
        bgm_path = generate_bgm(est_total, work_dir)

    # Phase 6: Final assembly
    print(f"\n  [7/7] Final assembly...")
    result = assemble_final(act_results, bgm_path, spec, output_path, work_dir, cfg)
    if not result: return

    total_dur, n_subs = result
    elapsed = (datetime.now() - t0).total_seconds()
    m, s = divmod(int(total_dur), 60)
    sz = output_path.stat().st_size / (1024*1024)

    # Report
    report = {
        "version": __version__, "timestamp": datetime.now().isoformat(),
        "duration": f"{m}:{s:02d}", "size_mb": round(sz, 1),
        "clips": total_clips, "sources": len(sources), "subtitles": n_subs,
        "elapsed_s": round(elapsed),
    }
    with open(output_path.with_name("report.json"), "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n  {'='*60}")
    print(f"  * AI Travel Film Done")
    print(f"    [video] {output_path}")
    print(f"    [time]  {m}:{s:02d}")
    print(f"    [size]  {sz:.0f}MB")
    print(f"    [clips] {total_clips} (from {len(sources)} sources)")
    print(f"    [subs]  {n_subs}")
    print(f"    [took]  {elapsed:.0f}s")
    print(f"  {'='*60}")

    # Cleanup work dir
    for f in work_dir.glob("*.mp4"): f.unlink(missing_ok=True)
    for f in work_dir.glob("*.wav"): f.unlink(missing_ok=True)
    for f in work_dir.glob("*.txt"): f.unlink(missing_ok=True)

if __name__ == "__main__":
    main()
