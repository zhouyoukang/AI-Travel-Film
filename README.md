# AI Travel Film

> Turn raw travel footage into cinematic short films — zero manual editing, fully AI-driven.

**One command. Five-act narrative. Professional output.**

```
python travel_film.py --config my_trip.json
```

## What It Does

Point it at your travel footage folders → it analyzes every clip (motion energy, brightness, resolution, frame rate) → selects the best moments → arranges them into a 5-act cinematic narrative → adds crossfade transitions, color grading, BGM with loudnorm, and TTS narration → outputs a publish-ready video.

### The 5-Act Structure

```
Emotion  ▁▃▅▇▇▇█████████████▇▅▃▁
         Hook  Departure  Journey   Peak        Epilogue
         (3s)   (25s)     (35s)    (50s)        (25s)
```

| Act | Purpose | Camera | Speed |
|-----|---------|--------|-------|
| **Hook** | Grab attention in 3 seconds | Drone aerial | 0.35x slow-mo |
| **Departure** | Build anticipation | Drone/wide | 1.0x normal |
| **Journey** | The road, the movement | Action cam | 1.0x + stabilize |
| **Peak** | Time stops. The payoff. | 4K camera | 0.4x slow-mo |
| **Epilogue** | Reflection, closure | Drone/wide | 0.5x slow-mo |

## Quick Start

### Prerequisites

- **Python 3.9+**
- **ffmpeg** and **ffprobe** in PATH
- (Optional) `pip install edge-tts` for AI narration

### 1. Create your config

```bash
cp example_config.json my_trip.json
```

Edit `my_trip.json` — point `source_dirs` to your footage:

```json
{
  "source_dirs": [
    ["~/Videos/drone", "aerial", "DJI Mini 3"],
    ["~/Videos/gopro", "action", "GoPro Hero 12"],
    ["~/Videos/sony", "camera", "Sony A7IV"]
  ],
  "output_dir": "./output",
  "bgm_path": "./my_bgm.mp3"
}
```

### 2. Run

```bash
# Analyze your footage first (optional)
python travel_film.py analyze --config my_trip.json

# Build the film
python travel_film.py --config my_trip.json

# Build 9:16 vertical for TikTok/Reels
python travel_film.py --config my_trip.json --vertical
```

### 3. Output

```
output/
├── travel_film.mp4          # Final video (publish-ready)
├── travel_film.srt          # Subtitle file
├── travel_film_cover.jpg    # Cover image
├── report.json              # Production report
├── source_analysis.json     # Cached analysis (speeds up re-runs)
└── clips/                   # Extracted clips
```

## How It Works

### Intelligent Clip Selection

Not random sampling — each clip is scored on:
- **Motion energy** (frame-to-frame pixel difference) — matches narrative pacing
- **Composite score** (4K bonus + high-fps bonus + trip date bonus + type match)
- **Type preference** — each act prefers specific camera types

### Technical Pipeline

```
Source Scan → Motion Analysis → Clip Selection → Extract + Color Grade
    ↓              ↓                  ↓                    ↓
 59 clips    brightness +       5-act narrative      crossfade +
 metadata    motion scores      structure            per-act curves
                                                          ↓
                                              TTS Narration → Act Assembly
                                                          ↓
                                              BGM Mix (loudnorm -16 LUFS)
                                                          ↓
                                              Subtitle Burn → Final Output
```

### Key FFmpeg Features Used

- `xfade` — smooth crossfade transitions between clips
- `setpts` — variable speed (slow-motion for 120fps footage)
- `dejudder` + `unsharp` — action camera stabilization
- `curves` — cinematic per-act color grading
- `loudnorm` — broadcast-standard audio normalization (-16 LUFS)
- `amix` — BGM + narration mixing
- `atrim` / `afade` — precise audio timing

## Configuration Reference

| Key | Type | Description |
|-----|------|-------------|
| `source_dirs` | array | `[[path, type, label], ...]` — type: aerial/action/camera |
| `output_dir` | string | Where to write output files |
| `bgm_path` | string | Path to BGM file. Empty = generate synthetic |
| `trip_dates` | object | `{"YYYY-MM": {"name": "...", "mood": "..."}}` — boost matching clips |
| `narrative` | array | 5-act structure. See `example_config.json` |
| `tts_voice` | string | edge-tts voice. `en-US-GuyNeural`, `zh-CN-YunxiNeural`, etc. |
| `reclassify_rules` | object | `{"filename_pattern": "new_type"}` — fix misclassified footage |
| `crf` | int | Video quality (17=high, 23=medium, 28=low) |
| `crossfade_dur` | float | Crossfade duration in seconds |
| `max_source_dur` | int | Skip clips longer than this (seconds) |

## Customizing the Narrative

Each act in the `narrative` array supports:

```json
{
  "act": "peak",
  "label": "The Moment",
  "duration_target": 50,
  "n_clips": 6,
  "speed": 0.4,
  "prefer_type": "camera",
  "prefer_motion": [15, 50],
  "stabilize": false,
  "color_grade": "eq=contrast=1.08:saturation=1.3",
  "narration": "Your narration text here.",
  "subtitle": "Subtitle text\nwith line breaks."
}
```

- **`speed`** — <1.0 = slow motion, 1.0 = normal, >1.0 = timelapse
- **`prefer_type`** — which camera type to prioritize for this act
- **`prefer_motion`** — `[min, max]` motion energy range (0-100)
- **`stabilize`** — apply dejudder for shaky action cam footage
- **`color_grade`** — any valid ffmpeg video filter string

## Tips for Best Results

1. **Organize footage by camera type** — drone in one folder, action cam in another
2. **Use high frame rate for peak moments** — 120fps footage becomes stunning slow-motion
3. **Provide a real BGM** — the synthetic fallback works but a proper track transforms the film
4. **Set `trip_dates`** — clips from your actual trip get priority over random footage
5. **Iterate** — run, watch, adjust narrative timing/speed, re-run (~10 min per build)

## Free BGM Sources

- [Incompetech](https://incompetech.com/music/royalty-free/) — Kevin MacLeod, CC BY 4.0
- [Pixabay Music](https://pixabay.com/music/) — Free for commercial use
- [Free Music Archive](https://freemusicarchive.org/) — Various CC licenses

## Requirements

```
Python >= 3.9
ffmpeg >= 5.0 (with libx264)
edge-tts >= 6.0 (optional)
```

No heavy dependencies. No moviepy, no opencv, no tensorflow. Just Python + ffmpeg.

## License

MIT — do whatever you want with it.

## Credits

Built with [Windsurf](https://windsurf.com) IDE + Cascade AI pair programming.

Inspired by the narrative techniques of travel filmmakers like 房琪kiki, 旅行者小辉, and 徐云.
