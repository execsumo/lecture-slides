---
name: lecture-slides
description: Download lecture videos, extract timestamped native-resolution slide screenshots, retrieve transcripts with YouTube captions or Supadata fallback, and build a polished synchronized slide/transcript reader. Use when saving lecture slides, handling presenter overlays, naming lecture folders intuitively, or viewing lecture materials remotely.
compatibility: Python 3.11+, uv, lecture-slides; Node 22+ or Deno recommended for YouTube; optional Supadata API key or MCP for transcript fallback.
---

# Lecture slides

Use the installed `lecture-slides` CLI, not a new downloader or transcriber. Read the repo's `README.md` for full options. This skill lives at `skills/lecture-slides/SKILL.md`; resolve symlinks and go two levels above its directory to find the repo.

## Plan the output

1. Check `command -v lecture-slides` and `lecture-slides --help`. If missing, run `uv tool install .` from the repo root.
2. Use the user's chosen parent directory, otherwise `~/workspace`. Quote URLs and paths. Check `df -h` for long lectures; video temporarily uses disk space during decoding.
3. **Use LLM judgement to choose `--slug`**, rather than merely copying the title. Include the concrete subject, product/entity, or problem the user would search for. Prefer the user's own search vocabulary; ask if the topic is ambiguous instead of inventing names. Add useful context, omit filler such as "lecture" and "introduction", and keep it short. Slugs use lowercase letters/digits separated by hyphens (max 100 characters).
4. For the Stanford lecture the user thinks of as "grok bot", use `grok-bot-always-on-agents`, not just `always-on-agents-stanford-cs146s`. This is a search hint supplied by the user, not a claim inferred from the title.
5. `-o` is a **parent** directory; `--slug` names the subfolder. Without `--slug`, the CLI falls back to a cleaned title plus video ID (or local filename stem). Do not overwrite completed slides or rename existing lecture folders without asking.

## Extract slides, transcript, and reader

```bash
lecture-slides 'https://www.youtube.com/watch?v=VIDEO_ID' \
  -o "$HOME/workspace" --slug 'topic-product-useful-context'
```

Outputs inside `PARENT/SLUG/`:

- `index.html`: self-contained lecture reader with sequenced thumbnails, expandable slide modal, linked transcript panel, and original-video link. No CDN or web app backend.
- `slide-0001_HH-MM-SS.mmm.png`: lossless screenshots at native resolution; no upscaling.
- `slides.json`: captured-frame times, stable-candidate start times, dimensions, settings, and source URL.
- `lecture.json`: compact source title/ID/link/resolution metadata for URL inputs.
- `transcript.txt` and `transcript.json`: timestamped text and structured segments, if retrieval succeeds.

Downloaded video and raw download intermediates are **temporary by default**, cleaned on success, ordinary errors, and Ctrl+C. Never promise cleanup after a hard kill or host crash. `--keep-video` explicitly retains downloaded media under `video/`; use only when requested or when the user agrees it is useful for repeated tuning. **Local input videos are never deleted.** Existing videos retained by older versions need separate, explicit cleanup; do not delete arbitrary media directories.

## Presenter overlays and tuning

```bash
lecture-slides 'YOUTUBE_URL' -o "$HOME/workspace" --slug 'useful-topic' \
  --ignore bottom-right
# Tight rectangle: x,y,width,height in original-video fractions.
lecture-slides 'YOUTUBE_URL' -o "$HOME/workspace" --slug 'useful-topic' \
  --ignore 0.88,0.68,0.12,0.32
```

Presenter motion can cause missed slides and duplicates. Inspect the actual layout; there is no automatic presenter detector. Corner presets cover 30% of width and height, so prefer tighter masks when they would otherwise hide slide changes. Repeat `--ignore` for multiple regions.

Masks affect detection only; the PNG still includes the presenter. Use `--crop 0,0,0.75,1` only when the user wants cropped output. Coordinates always refer to the original frame. Hidden pixels cannot be recovered.

`--preview` saves a first-frame image. URL preview still downloads the whole video, but that video is then deleted unless `--keep-video` was requested. Inspect a later output screenshot if the first frame doesn't show the lecture layout.

Defaults: 1-second sampling, 2-second stability, 1.5% changed area. Brief slides: lower `--interval` and `--settle`. Small bullet builds: `--change 0.005 --stability 0.001`. Noisy recordings: try `--stability 0.008`; stability must remain below change. This is visual change detection, not semantic slide recognition.

For repeated extraction, use a new parent directory and a local input only if one was explicitly retained. Do not redownload a large video merely to rebuild the reader or obtain a transcript.

## Transcripts: YouTube, then Supadata

English is the default; use `--language nl` or another requested code. Human YouTube captions are preferred over automatic captions, including regional variants. If captions fail or are absent, the tool can use Supadata through `SUPADATA_API_KEY` in the process environment. Never put the key in a command argument, repo, HTML, logs, or chat. Do not invent credentials or silently install an MCP server.

If Supadata is available as an MCP tool instead, request **timestamped** segments, not one plain-text transcript. Save the result in the normalized `transcript.json` format below and write timestamped `transcript.txt`, then rebuild the viewer. The standalone CLI uses the API, not the harness's MCP connection. Preserve provider/language metadata, and do not label Supadata output as human-authored unless its response establishes that.

```json
{"provider":"supadata","language":"en","segments":[{"start_seconds":0,"end_seconds":3.2,"text":"Welcome"}]}
```

Supadata's documented offset/duration units must be converted to seconds. The package's `lecture_slides.transcripts` helpers handle API normalization and file export; prefer those to a second converter. Follow the documented transcript mode and don't silently opt into paid AI transcription when only existing captions were authorized. If neither provider succeeds, report that explicitly; a zero exit code does not guarantee a transcript. Never repeatedly hammer YouTube after HTTP 429.

## Existing lecture / reader refresh

```bash
lecture-slides --build-viewer '/absolute/path/to/existing/lecture'
```

This reads the existing `slides.json`, attempts the configured transcript fallback if needed, and rebuilds `index.html` **without downloading or decoding video**. Preserve existing images and folder names. If choosing a masked variant, make sure the manifest passed to the reader references those images, not the earlier unmasked run. Do not fabricate transcript data to demonstrate synchronization.

## Verify and report

- Check manifest counts, native image dimensions, ordered timestamps, and referenced image files.
- Open screenshots from the beginning, middle, and end. Be precise about spot checks versus full coverage.
- Confirm both transcript files contain actual timed text before claiming a transcript is available.
- Open `index.html` in a browser: check thumbnails, source link, modal, Escape/focus behavior, and **left/down = previous, up/right = next**. Check slide selection seeks the transcript and user transcript scrolling updates the selected slide without oscillation or jump-back.
- Confirm temporary videos are gone unless retention was explicitly requested. Do not delete user-supplied local inputs.
- Report exact output folder, reader path, slide count/resolution, transcript provider/status, and cleanup status.

## Remote viewing

Use the `remote-viewing` skill when available: serve the **lecture folder containing index.html** on loopback, with an automatic **15-minute timeout**, and give the viewing device a fully populated SSH forwarding command based on this device's actual SSH details. Do not serve only `slides-masked/` when the reader and transcript live in the parent. Do not expose the server publicly or leave it running indefinitely. Local `file://` viewing also works after copying the full lecture folder.
