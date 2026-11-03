# lecture-slides

Download a YouTube lecture at the highest available resolution, save stable slides as **lossless PNGs at the video's native resolution**, and download its captions as a timestamped transcript in the same run. Runs locally, without an AI service, OCR, or API keys. Also accepts local videos (slides only; no speech-to-text).

`--output` is the parent directory of your choice. Results go in a subfolder named `Video title [video ID]`; the ID prevents identically titled videos from colliding. Local files use their filename stem. Titles are sanitized and long names shortened for filesystem safety.

**Changed from the first version:** `-o ./slides` now creates `./slides/Video title [ID]/` rather than putting results directly in `./slides/`.

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). For YouTube, a supported JavaScript runtime such as Node 22+ or Deno is recommended; the downloader enables both if installed.

```bash
cd /home/herwin/projects/lecture-slides
uv tool install .
```

## Pi skill

The usage skill lives in [`skills/lecture-slides/SKILL.md`](skills/lecture-slides/SKILL.md). Install it in Pi with a symlink so it stays in sync with this repo (run from the repo root):

```bash
mkdir -p "$HOME/.pi/agent/skills"
ln -s "$(pwd)/skills/lecture-slides" "$HOME/.pi/agent/skills/lecture-slides"
```

If that destination already exists, inspect it rather than overwriting it. Run `/reload` in an active Pi session, then use `/skill:lecture-slides` or ask to extract slides from a lecture.

## Use

```bash
lecture-slides 'https://www.youtube.com/watch?v=VIDEO_ID' -o ./my-lecture

# Ignore a moving presenter in the bottom-right corner when detecting slides:
lecture-slides 'https://www.youtube.com/watch?v=VIDEO_ID' -o ./my-lecture \
  --ignore bottom-right

# Local file, with an exact presenter rectangle:
lecture-slides ./lecture.mp4 -o ./slides --ignore 0.78,0.65,0.22,0.35
```

`--ignore` takes **x,y,width,height fractions of the original video**, or a corner name (`top-left`, `top-right`, `bottom-left`, `bottom-right`). Corner shortcuts cover 30% of the frame's width and height. Adjust them to the actual overlay; nothing is ignored by default. Repeat `--ignore` for multiple regions.

**Ignore masks affect detection only.** Saved images retain the presenter and any visible slide content. To save only a rectangular slide area, use `--crop`, for example `--crop 0,0,0.75,1` for the left 75%. Cropping never rescales the result. All coordinates, including ignore masks, are relative to the original video.

For finding coordinates, save the first frame:

```bash
lecture-slides ./lecture.mp4 -o ./preview --preview
# Inspect ./preview/lecture/preview.png; divide pixel coordinates by image width/height.
```

A URL preview downloads the video and any available captions first. The original downloaded video is retained under `OUTPUT/Video title [ID]/video/` and can be reused as a local input without downloading again.

### Output

```text
my-lecture/                         # your chosen --output directory
  Lecture title [VIDEO_ID]/
    video/VIDEO_ID.webm
    video/VIDEO_ID.info.json
    video/VIDEO_ID.en.json3          # original caption data
    transcript.txt                  # readable, timestamped text
    transcript.json                 # timed segments and language metadata
    slide-0001_00-00-02.000.png
    slide-0002_00-00-19.000.png
    slides.json
```

Filename timestamps are **the actual captured frame's time from the start of the video**, not a guessed transition time. `slides.json` includes that timestamp, the time the stable candidate was first observed (`stable_since_seconds`), image dimensions, and extraction settings. These are sampled observations, not exact slide-onset times. Existing slide output is not overwritten; choose a new directory to rerun. The manifest is updated after every image so a later decoding failure does not discard earlier results.

### Transcripts

Captions are downloaded automatically for URL inputs. The default language is English; change it with `--language nl` (or another language code). Human-written captions are preferred over automatic captions, including regional variants of the requested language. Automatic tracks can include YouTube-provided translations. `transcript.json` records the selected language and whether it was automatic.

`transcript.txt` contains lines such as `[00:03:12.500] The next slide shows…`. `transcript.json` contains segments with `start_seconds`, `end_seconds`, and `text`. Whitespace is normalized and repeated words in overlapping rolling captions are trimmed; original caption data remains under `video/`. Transcript timing comes from YouTube captions, not slide detection.

If captions are absent, restricted, fail to download, or aren't available in JSON3 format, the tool prints a warning and still extracts slides. It does **not** transcribe audio. Local video inputs do not fetch transcripts. Captions are saved before slide extraction, so they remain available if extraction later fails.

### Tune detection

```bash
# Faster builds / briefly shown slides:
lecture-slides ./lecture.mp4 -o ./slides-fast --interval 0.5 --settle 1

# Catch smaller incremental bullet changes (and accept more duplicates):
lecture-slides ./lecture.mp4 -o ./slides-sensitive \
  --ignore bottom-right --change 0.005 --stability 0.001

# For noisier recordings, allow more motion while settling:
lecture-slides ./lecture.mp4 -o ./slides-noisy --stability 0.008
```

Defaults: sample every 1 second, require 2 seconds of stability, and require 1.5% of visible detection pixels to change for a new slide. `--stability` defaults to 0.3% and must be below `--change`. Images are blurred and reduced to at most 640 pixels wide **only for comparison**, never for saved screenshots. The original video is decoded sequentially, so extraction still takes time even with a larger sample interval.

If YouTube requires sign-in, you can explicitly opt into your own browser cookies with `--cookies-from-browser firefox` (or `chrome`). This uses your authenticated session; use it only for videos you are authorized to access. No cookies are read by default.

## Limits

- This is visual change detection, **not semantic slide recognition**. Stable title cards or talking-head shots can also be saved. Animation, moving cursors, or unmasked presenters can prevent a slide from settling.
- There is no automatic presenter-region detector. Mask the overlay explicitly; if its position changes, multiple masks or separate runs may be needed. Changes entirely inside ignored areas cannot trigger a new slide.
- Slides visible for less than the sampling/settling window may be missed. The final slide must also meet the stability requirement. Revisited slides are retained at their new timestamps; an unchanged slide is not repeatedly emitted.
- The highest resolution means the highest stream YouTube makes available to the downloader. It cannot recreate the original slide deck, sharpen a low-resolution recording, or recover pixels hidden behind an overlay. No upscaling is applied. The video-only stream is preferred; audio is unnecessary for screenshots.
- YouTube restrictions and downloader changes can prevent downloads. Update with `uv tool upgrade lecture-slides`; for local development use `uv sync --upgrade-package yt-dlp --upgrade-package yt-dlp-ejs` and reinstall the tool.
- Large videos can consume substantial disk space and decoding memory. No video is automatically deleted. Only download content you have permission to use.

## Development

```bash
uv sync
uv run pytest -q
uv run lecture-slides --help
```

Tests generate a lossless lecture with changing slides and an animated presenter, then check extraction count, timestamps, lossless 4K output, ignore masks, cropping, and output protection. Transcript tests cover language selection, caption cleanup, directory naming, failure handling, and real yt-dlp output processing with network I/O mocked. Live YouTube downloads are not part of the test suite.
