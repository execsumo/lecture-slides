# lecture-slides

## What does this do?

Turn a YouTube lecture — or a video file on your computer — into a folder of slide images at the video's native resolution, plus a self-contained `index.html` reader that keeps the slides and the transcript in sync. No account, no backend, no upload: you open the reader in any browser.

## Why use it?

- **Revisit a lecture visually.** Every stable slide is saved as a lossless PNG, in order, with timestamps — no more scrubbing through video or taking screenshots by hand.
- **Read along with the transcript.** The reader jumps between a slide and the speech that goes with it, and the transcript is written in complete sentences, not caption fragments.
- **Hand a lecture to an AI agent.** Every run also writes `lecture.md` and `lecture-aligned.json`: the slides in order with their matching speech, ready to read or analyze.
- **Keep only what matters.** The downloaded video is temporary by default and cleaned up afterwards; a local input file is never deleted.

## Setup

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and ffmpeg. ffmpeg is needed to merge the highest-quality YouTube video and audio streams — without it, YouTube downloads may fail or fall back to lower quality. For YouTube, Node 22+ or Deno is also recommended (yt-dlp uses it for YouTube's JavaScript challenges).

```bash
uv tool install git+https://github.com/execsumo/lecture-slides
```

Or from a clone: `git clone https://github.com/execsumo/lecture-slides && cd lecture-slides && uv tool install .`. Add `--force` to upgrade. Then install the agent skill (below) if you want an AI agent to run it for you.

## Use

```bash
lecture-slides 'https://www.youtube.com/watch?v=VIDEO_ID' \
  --slug how-neural-networks-learn \
  --ignore 0.88,0.68,0.12,0.32
```

`--output` is the parent directory (default: `~/Downloads`, created if missing). `--slug` is a human/agent-chosen, search-friendly folder name, not necessarily a restatement of the title. Include the subject or product you would actually search for. It accepts 1–100 lowercase letters/digits separated by hyphens. Without it, the CLI uses a cleaned title plus video ID; local inputs use a cleaned filename stem. Existing slide output is protected against overwrite.

```text
~/Downloads/how-neural-networks-learn/
  index.html
  lecture.md
  lecture-aligned.json
  lecture.json
  slides.json
  slide-0001_00-00-02.000.png
  slide-0002_00-00-19.000.png
  transcript.txt
  transcript.json
```

### Reader

Open `index.html` directly after copying the folder to your computer, or serve it over an SSH-forwarded local HTTP server. The reader has no CDN dependency, fetch requests, or application backend.

- A full-window app layout: a header with the video title, source link and a **Light / System / Dark** toggle (remembered per browser); a collapsible left rail of sequenced thumbnails; a centre stage that fits the current slide to the available space without cropping; and a collapsible right transcript. Collapsing either side gives the slide more room. On narrow screens the side panels become drawers.
- Collapsible transcript panel beside the slides (below them on small screens).
- Selecting a slide jumps to its transcript section; scrolling the transcript updates the selected slide. Synchronization uses observed stable-slide start times, not exact slide-onset detection.
- **Left/up** goes to the previous slide; **down/right** goes to the next; **Home/End** jump to the first/last; **[** and **]** toggle the slide list and transcript; Escape closes a mobile drawer. Clicking the progress bar jumps to that slide. The mouse wheel over the centre column also steps through slides (the side panels scroll normally).
- The download button saves **`lecture-export.zip`** (also written beside `index.html` on every reader build): `lecture.md` (readable), `lecture.json` (machine-readable, with image references) and `slides/001.png…`. It is deliberately minimal for LLM hand-off, and omitted if any slide image is missing.
- The expanded viewer has a segmented, time-weighted progress bar: a slide discussed for five minutes occupies more space than one shown for ten seconds. Position uses the selected slide's start time, not its ordinal number.
- Transcript fragments are joined into complete sentences and readable paragraphs. Timestamps appear only on the first new sentence after a slide change (and at the beginning), not on every provider cue. A sentence already underway continues without an inserted timestamp.
- A source-video link with the selected slide's capture timestamp.
- Clear transcript-unavailable state if neither provider succeeds.

Rebuild a reader or add a newly available transcript **without downloading the video again**:

```bash
lecture-slides --build-viewer '/path/to/existing/lecture'
```

The folder must contain `slides.json` and its referenced images. Existing slide PNGs are not overwritten. Existing valid transcripts are reused.

### LLM-friendly companion

Every extraction and reader rebuild also writes **`lecture.md`** and **`lecture-aligned.json`** beside the images. Markdown provides the lecture source, numbered slide image links, time windows, and associated transcript text; JSON provides the same ordered slide/paragraph associations for programmatic use. `lecture.json` remains compact source metadata, not the aligned export.

The reader and companion use the same sentence alignment: speech belongs to the slide active when the sentence begins. Sentences crossing a slide change are kept whole rather than duplicated or cut. Brief slides with no new sentence have an explicit empty-section explanation. In-cue sentence times are estimated from character offsets, not word-level audio alignment. Raw `transcript.json` is preserved for precise provider-cue timestamps; no speech is summarized or rephrased. If captions lack punctuation, wrapping is approximate and timestamps are deferred rather than invented mid-sentence.

### Transcripts

URL runs try YouTube captions first, preferring human captions to automatic ones. English is the default; choose another language with `--language nl` (or another language code). Automatic tracks can include YouTube translations.

If captions fail or are missing, **Supadata is the optional fallback**. Make `SUPADATA_API_KEY` available in the process environment through your secret manager. Do not put it in source files or command arguments. The CLI does not read credentials from the harness's MCP configuration automatically. An agent can also obtain timed content through Supadata MCP, save a normalized transcript, and run `--build-viewer`.

The API fallback explicitly uses `mode=native` (existing captions only), which costs one Supadata credit per request, including an unavailable-caption response. It never silently enables Supadata's per-minute AI generation. HTTP 206/202, empty content, and failed requests leave the reader usable without a transcript; no automatic retry loop runs. Supadata may return a different available language when the requested one is absent; the tool records it and warns. Only YouTube URLs are submitted, because Supadata file URLs force generation regardless of mode. See [Supadata transcript docs](https://docs.supadata.ai/get-transcript).

After reader generation, `transcript.txt` contains readable paragraphs with timestamps only at slide-related sentence boundaries, matching the reader and `lecture.md`. `transcript.json` retains unchanged provider-cue text and timing. If extraction fails before reader generation, the text export may still be in its initial cue-by-cue form. `transcript.json` records provider, language, and timed segments with `start_seconds`, `end_seconds`, and `text`. Raw YouTube rolling captions are normalized to remove overlapping repeated words. The transcript is saved before slide extraction, so it survives a later extraction failure.

Missing credentials, unavailable captions, unsupported formats, rate limits, and API errors are warnings, not reasons to discard slides. **A successful command does not guarantee a transcript.** Local inputs have no automatic transcript lookup; place a compatible timed transcript in an existing output folder and rebuild its reader. There is no local speech-to-text engine.

### Download cleanup

**Downloaded video is temporary by default.** The CLI keeps the video and download intermediates in a temporary directory while decoding, then removes that directory on success, ordinary failure, or Ctrl+C. Only PNGs, compact metadata, normalized transcripts, and the reader remain. Partial download files are cleaned too. The manifest marks an unretained video as `null`.

Use `--keep-video` explicitly if you want the downloaded video and raw captions retained under `OUTPUT/SLUG/video/`, for example while tuning extraction repeatedly. Local input files are **never deleted**. Reader rebuilding does not download a video.

An abrupt hard kill or host crash can bypass cleanup. Old outputs from versions that retained videos are not automatically deleted or migrated. Never run a broad deletion against a user-provided media directory.

### Presenter picture-in-picture

```bash
# Corner preset:
lecture-slides 'YOUTUBE_URL' --slug useful-topic --ignore bottom-right

# Local video, exact presenter rectangle:
lecture-slides ./lecture.mp4 -o ./slides --ignore 0.78,0.65,0.22,0.35
```

`--ignore` takes **x,y,width,height fractions of the original video**, or `top-left`, `top-right`, `bottom-left`, `bottom-right`. Corner shortcuts cover 30% of width and height. Adjust to the actual overlay and repeat the option for multiple regions. Nothing is ignored by default; there is no automatic presenter detector.

Masks affect **detection only**: saved images retain the presenter. Crop to the slide area with `--crop 0,0,0.75,1` (left 75%) only if desired. Cropping never rescales the saved image; all coordinates remain relative to the original frame. No tool can recover slide pixels hidden behind a presenter from that video alone.

To inspect the layout, `--preview` saves a first-frame `preview.png`. URL preview downloads the full video and then cleans it up by default, just like extraction. Use `--keep-video` if you need to reuse it. If the first frame is a title card, inspect a later extracted screenshot.

### Detection tuning

```bash
# Brief slides:
lecture-slides ./lecture.mp4 -o ./slides-fast --interval 0.5 --settle 1
# Smaller bullet changes:
lecture-slides ./lecture.mp4 -o ./slides-sensitive \
  --ignore bottom-right --change 0.005 --stability 0.001
# Noisier recordings:
lecture-slides ./lecture.mp4 -o ./slides-noisy --stability 0.008
```

Defaults: sample every 1 second, require 2 seconds of stability, and require 1.5% of visible detection pixels to change. Stability defaults to 0.3% and must be below the change threshold. Images are blurred and reduced to at most 640 pixels wide **only for detection**, never for PNG export. Video is decoded sequentially even with sparse sampling.

Filename timestamps come from actual decoded frames. `slides.json` also stores `stable_since_seconds`: the first observation of the stable candidate, not a guaranteed exact onset. This is visual change detection, not semantic slide recognition: stable talking heads and title cards can be saved, animations can prevent settling, and brief slides or tiny text edits may be missed. Revisited slides are kept at their new timestamps.

YouTube's available streams, access restrictions, and rate limits determine what can be downloaded. Only use content you have permission to access. Browser cookies require explicit opt-in (`--cookies-from-browser firefox`); they use your authenticated session.

## Agent skill

[`skills/lecture-slides/SKILL.md`](skills/lecture-slides/SKILL.md) follows the open [Agent Skills](https://agentskills.io) format, so the same folder works in Pi, Claude Code and Codex. The skill drives the CLI, so **install the CLI first** (above). It uses LLM judgement to choose searchable slugs, handles the Supadata fallback, and verifies the reader.

Clone once, then link the skill folder into your agent's skills directory (use `cp -r` instead of `ln -s` if you prefer a copy):

```bash
git clone https://github.com/execsumo/lecture-slides ~/.local/share/lecture-slides
SKILL=~/.local/share/lecture-slides/skills/lecture-slides
```

| Agent | Install | Use |
|---|---|---|
| **Pi** | `pi install git:github.com/execsumo/lecture-slides` (or `mkdir -p ~/.pi/agent/skills && ln -s "$SKILL" ~/.pi/agent/skills/`) | `/reload`, then `/skill:lecture-slides` |
| **Claude Code** | `mkdir -p ~/.claude/skills && ln -s "$SKILL" ~/.claude/skills/` (per project: `.claude/skills/`) | Restart Claude Code; ask it to save a lecture's slides, or run `/lecture-slides` |
| **Codex** | `mkdir -p ~/.agents/skills && ln -s "$SKILL" ~/.agents/skills/` (per project: `.agents/skills/`; older Codex versions read `~/.codex/skills/`) | Restart Codex; ask for lecture slides, or type `$lecture-slides` |

`~/.agents/skills/` is also read by Pi. Check an existing destination before linking so you don't overwrite another skill. To update, `git -C ~/.local/share/lecture-slides pull` and `uv tool install --force git+https://github.com/execsumo/lecture-slides`.

## Development

```bash
uv sync
uv run pytest -q
uv run lecture-slides --help
# Optional real-browser synchronization/keyboard/mobile test:
uv run --with playwright playwright install chromium
uv run --with playwright python -m pytest tests/test_browser.py -q
```

The browser test is skipped when Playwright isn't installed; it is not a runtime dependency. `PLAYWRIGHT_CHROMIUM_EXECUTABLE` can point to an already installed Chromium binary.

Tests use generated lecture videos, mock network traffic, and cover native 4K output, timestamps, masks, captions, naming, cleanup, and reader generation. Live provider availability is not guaranteed by the test suite. To update dependencies locally, use `uv sync --upgrade-package yt-dlp --upgrade-package yt-dlp-ejs`, then `uv tool install --force .`.
