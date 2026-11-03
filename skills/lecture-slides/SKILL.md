---
name: lecture-slides
description: Download YouTube lectures and extract native-resolution, timestamped slide screenshots and caption transcripts with lecture-slides. Use when saving lecture slides, processing lecture videos, masking presenter picture-in-picture, downloading captions alongside slides, or inspecting lecture-slides output on a headless device.
compatibility: Python 3.11+, uv, lecture-slides; Node 22+ or Deno recommended for YouTube downloads.
---

# Lecture slides

Use the installed `lecture-slides` CLI. Do not build a new downloader or transcriber for this task.

## Before running

1. Run `command -v lecture-slides` and `lecture-slides --help` to confirm availability and flags.
2. Use the user's chosen output parent. If none is given, use `~/workspace` and state the destination. Quote URLs and paths; titles contain spaces and punctuation. Do not put downloaded media in the source repository.
3. Check available disk space (`df -h`) for long lectures; retained videos may be large.
4. If the CLI is missing, install with `uv tool install .` from the repository root. This skill is stored at `skills/lecture-slides/SKILL.md`; resolve symlinks first, then go two directories above its directory to find the repo. Read the repo's `README.md` for full setup and usage.

## Download slides and transcript together

```bash
lecture-slides 'https://www.youtube.com/watch?v=VIDEO_ID' -o "$HOME/workspace"
```

`-o` selects a **parent**, not the final output folder. URL output goes in `PARENT/Video title [VIDEO_ID]/`; titles are sanitized and truncated for filesystem safety. Local video input goes in `PARENT/filename-stem/`.

Outputs:

- `slide-0001_HH-MM-SS.mmm.png`: native-resolution, lossless screenshots; no upscaling.
- `slides.json`: image filenames, actual captured-frame timestamps, stable-candidate start times, dimensions, and detection settings.
- `transcript.txt`: readable timestamped captions, if available.
- `transcript.json`: timed text segments, selected language, and automatic-caption flag.
- `video/`: downloaded video, metadata, and original JSON3 captions when available.

English is the default transcript language. Use `--language nl` (or another code) when requested. Human captions are preferred over automatic captions, including regional language variants. Automatic tracks may be YouTube translations. Local inputs produce slides only; no audio transcription is performed.

## Presenter picture-in-picture

Presenter motion can cause both duplicate images and missed slides. Mask the actual overlay when its position is known:

```bash
lecture-slides 'YOUTUBE_URL' -o "$HOME/workspace" --ignore bottom-right
# Exact rectangle: x,y,width,height as fractions of the ORIGINAL video.
lecture-slides 'YOUTUBE_URL' -o "$HOME/workspace" --ignore 0.88,0.68,0.12,0.32
```

Corner presets cover 30% of image width and height; prefer a tighter rectangle when that would otherwise hide slide content from detection. Repeat `--ignore` for multiple regions. There is **no automatic presenter detection**. Do not assume every lecture has the same layout.

Ignore masks change detection only: saved PNGs retain the presenter. `--crop 0,0,0.75,1` saves only the left 75%, without resizing. All coordinates refer to the original video, even with a crop. Covered slide pixels cannot be reconstructed.

If needed, use `--preview` to save a first-frame `preview.png` and inspect it with the image-reading tool. For URLs this downloads the full video and captions first, not merely a thumbnail. If the first frame doesn't show the lecture layout, inspect a later saved frame. Reuse `video/VIDEO_ID.ext` as a local input for subsequent extraction rather than downloading again.

## Tune and rerun

```bash
lecture-slides '/path/to/video.mp4' -o "$HOME/workspace/refined" \
  --ignore 0.88,0.68,0.12,0.32 --interval 0.5 --settle 1
```

Existing slide results are protected from overwrite. Use a new parent directory for reruns; never delete prior output without permission. Local reruns create a filename-stem folder and do not fetch a transcript. Original captions remain in the original URL output folder.

- Defaults: sample every 1 second; require 2 seconds of stability; count 1.5% changed area as a new slide.
- Brief slides: lower `--interval` and `--settle`.
- Small bullet builds: try `--change 0.005 --stability 0.001`.
- Noisy recordings: try `--stability 0.008`; it must remain below `--change`.
- This is visual change detection, not semantic slide recognition: title cards, transitions, and talking heads can be retained; brief slides or small edits can be missed.

## Verify before reporting success

1. Inspect `slides.json`: slide count, dimensions, timestamps, settings, and filenames. Confirm referenced PNGs exist.
2. Open several screenshots from the start, middle, and end. Check readability, presenter position, duplicates, missed beginnings, and unwanted crops. Do not claim every slide was checked if only samples were viewed.
3. Check that `transcript.txt` AND `transcript.json` actually exist and contain text. A successful command exit does **not** guarantee a transcript.
4. Report the exact output folder, slide count/resolution, caption status, and any sampling limitations.

Caption absence, unsupported format, or HTTP errors are nonfatal: slides still save. YouTube HTTP 429 means rate limiting; report the missing transcript accurately. Do not repeatedly retry or redownload a large video to chase captions. Do not promise speech-to-text fallback. Only use `--cookies-from-browser firefox` (or another browser) with explicit user approval because it accesses an authenticated session. Never print cookies or tokens.

## Headless viewing

Offer copying the folder over SCP/SFTP or an SSH-forwarded local web server. For browsing, bind on the headless device to loopback, not all interfaces:

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory "$HOME/workspace"
```

On the user's computer:

```bash
ssh -N -L 8000:127.0.0.1:8000 USER@HOST
```

Then open `http://localhost:8000`. Replace `USER@HOST` with the actual SSH target. Do not start a persistent server unless requested; keep it bound to loopback and explain how to stop it. Serve only the needed output directory when practical.
