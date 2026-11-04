"""Native-resolution lecture slides with a synchronized transcript reader."""

import argparse
import json
import math
import re
import sys
import tempfile
import unicodedata
from contextlib import ExitStack
from pathlib import Path

import av
import cv2
import numpy as np
import yt_dlp

from .transcripts import ensure_transcript, write_transcript
from .viewer import build_viewer


CORNERS = {
    "top-left": (0, 0, 0.3, 0.3),
    "top-right": (0.7, 0, 0.3, 0.3),
    "bottom-left": (0, 0.7, 0.3, 0.3),
    "bottom-right": (0.7, 0.7, 0.3, 0.3),
}


def rectangle(value):
    """Normalized x,y,width,height in the original video, not the cropped image."""
    if value in CORNERS:
        return CORNERS[value]
    try:
        rect = tuple(float(part) for part in value.split(","))
        if len(rect) != 4 or not all(math.isfinite(n) for n in rect):
            raise ValueError
        x, y, w, h = rect
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1.000001 or y + h > 1.000001:
            raise ValueError
        return rect
    except ValueError:
        raise argparse.ArgumentTypeError("use x,y,width,height fractions within 0..1, or a corner name") from None


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return number


def fraction(value):
    number = positive(value)
    if number > 1:
        raise argparse.ArgumentTypeError("must be at most 1")
    return number


def bounds(rect, width, height):
    x, y, w, h = rect
    return (int(round(x * width)), int(round(y * height)),
            min(width, int(round((x + w) * width))),
            min(height, int(round((y + h) * height))))


class Detector:
    def __init__(self, width, height, crop, ignored):
        self.crop = bounds(crop, width, height)
        x1, y1, x2, y2 = self.crop
        if x2 <= x1 or y2 <= y1:
            raise ValueError("crop is smaller than one pixel")
        scale = min(1, 640 / (x2 - x1))
        self.size = (max(1, round((x2 - x1) * scale)), max(1, round((y2 - y1) * scale)))
        mask = np.ones((y2 - y1, x2 - x1), dtype=np.uint8)
        for rect in ignored:
            a, b, c, d = bounds(rect, width, height)
            a, b, c, d = max(a, x1), max(b, y1), min(c, x2), min(d, y2)
            if c > a and d > b:
                mask[b - y1:d - y1, a - x1:c - x1] = 0
        # Erode the mask so presenter pixels cannot bleed through the blur at its edge.
        self.mask = cv2.resize(mask, self.size, interpolation=cv2.INTER_NEAREST)
        self.mask = cv2.erode(self.mask, np.ones((7, 7), np.uint8)).astype(bool)
        if not self.mask.any():
            raise ValueError("ignore regions cover the entire detection area")

    def image(self, frame):
        x1, y1, x2, y2 = self.crop
        return frame[y1:y2, x1:x2]

    def fingerprint(self, frame):
        image = cv2.resize(self.image(frame), self.size, interpolation=cv2.INTER_AREA)
        return cv2.GaussianBlur(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), (5, 5), 0)

    def difference(self, a, b):
        return float(np.mean(cv2.absdiff(a, b)[self.mask] > 20))


def timestamp(seconds):
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}-{minutes:02d}-{seconds:02d}.{milliseconds:03d}"


def sample_frames(path, interval):
    """Decode in order, retaining real presentation timestamps (including VFR)."""
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError("source contains no video stream")
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        next_time = 0.0
        origin = None
        for frame in container.decode(stream):
            if frame.time is None:
                continue
            if origin is None:
                origin = float(frame.time)
            time = max(0.0, float(frame.time) - origin)
            if time + 1e-6 < next_time:
                continue
            yield time, frame.to_ndarray(format="bgr24")
            next_time = time + interval


def extract(video, output, *, interval=1.0, settle=2.0, change=0.015,
            stability=0.003, crop=(0, 0, 1, 1), ignored=(), source=None,
            video_retained=True):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "slides.json"
    if manifest_path.exists() or any(output.glob("slide-*.png")):
        raise ValueError(f"{output} already contains slides; choose a new output directory")
    slides = []
    manifest = {
        "source": source or str(video), "video": str(video) if video_retained else None,
        "video_retained": video_retained,
        "settings": {"interval": interval, "settle": settle, "change": change,
                     "stability": stability, "crop": crop, "ignored": ignored},
        "slides": slides,
    }

    def save_manifest():
        temporary = output / "slides.json.tmp"
        temporary.write_text(json.dumps(manifest, indent=2) + "\n")
        temporary.replace(manifest_path)

    detector = None
    anchor = None
    emitted = None
    stable_since = 0.0
    previous_time = 0.0
    for time, frame in sample_frames(video, interval):
        if detector is None:
            height, width = frame.shape[:2]
            detector = Detector(width, height, crop, ignored)
            manifest["video_resolution"] = [width, height]
        elif list(reversed(frame.shape[:2])) != manifest["video_resolution"]:
            raise ValueError("video resolution changed mid-stream; split the video before extraction")
        fingerprint = detector.fingerprint(frame)
        if anchor is None or detector.difference(anchor, fingerprint) > stability:
            anchor = fingerprint
            stable_since = time
        if time - stable_since + 1e-6 >= settle:
            if emitted is None or detector.difference(emitted, fingerprint) >= change:
                filename = f"slide-{len(slides) + 1:04d}_{timestamp(time)}.png"
                image = detector.image(frame)
                if not cv2.imwrite(str(output / filename), image):
                    raise OSError(f"could not write {filename}")
                slides.append({"file": filename, "timestamp_seconds": time,
                               "stable_since_seconds": stable_since,
                               "width": image.shape[1], "height": image.shape[0]})
                emitted = fingerprint
                save_manifest()
                print(f"{timestamp(time)}  {filename}", flush=True)
        previous_time = time
    if detector is None:
        raise ValueError("video has no decodable frames with timestamps")
    manifest["last_sample_seconds"] = previous_time
    save_manifest()
    return slides


def slug_value(value):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value) or len(value) > 100:
        raise argparse.ArgumentTypeError("slug must be 1–100 lowercase letters/digits separated by hyphens")
    return value


def output_folder(parent, title, video_id=None, slug=None):
    if slug is not None:
        name = slug_value(slug)
    else:
        ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", errors="ignore").decode()
        name = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")[:80].rstrip("-") or "lecture"
        if video_id:
            name += "-" + re.sub(r"[^a-zA-Z0-9_-]", "", video_id)[:50]
    return Path(parent).expanduser() / name


def check_output(directory):
    if (directory / "slides.json").exists() or any(directory.glob("slide-*.png")):
        raise ValueError(f"{directory} already contains slides; choose a new parent directory")


def caption_language(info, language):
    # Prefer human captions, including regional variants, over automatic captions.
    for key in ("subtitles", "automatic_captions"):
        available = info.get(key) or {}
        matches = [code for code in available if code == language or code.startswith(language + "-")]
        if matches:
            code = language if language in matches else sorted(matches)[0]
            return code, key == "automatic_captions"
    return None, False


def save_transcript(info, output, language, automatic):
    subtitle = (info.get("requested_subtitles") or {}).get(language, {})
    path = Path(subtitle["filepath"]) if subtitle.get("filepath") else None
    if path is None or not path.is_file() or subtitle.get("ext") != "json3":
        print("Warning: transcript could not be downloaded in JSON3 format; continuing with slides.", file=sys.stderr)
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        segments = []
        for event in data.get("events", []):
            text = " ".join("".join(seg.get("utf8", "") for seg in event.get("segs", [])).split())
            if not text:
                continue
            start = event.get("tStartMs", 0) / 1000
            end = start + event.get("dDurationMs", 0) / 1000
            # Automatic captions can repeat words across overlapping rolling cues.
            if segments and start < segments[-1]["end_seconds"]:
                previous, words = segments[-1]["text"].split(), text.split()
                for count in range(min(len(previous), len(words)), 0, -1):
                    if previous[-count:] == words[:count]:
                        text = " ".join(words[count:])
                        break
            if text:
                segments.append({"start_seconds": start, "end_seconds": end, "text": text})
        if not segments:
            raise ValueError("caption track contains no text")
        transcript = {"title": info.get("title"), "language": language,
                      "automatic": automatic, "segments": segments}
        transcript["provider"] = "youtube"
        write_transcript(output, transcript)
        print(f"Saved transcript ({language}) to {output}")
    except (ValueError, OSError, TypeError, AttributeError) as error:
        print(f"Warning: could not export transcript: {error}; continuing with slides.", file=sys.stderr)


def download(url, directory, cookie_browser=None, language="en", preview=False,
             slug=None, media_directory=None):
    options = {
        "format": "bestvideo/best",
        "format_sort": ["res", "fps"],
        "noplaylist": True,
        "writeinfojson": False,
        # Subtitle failures must not prevent the video and slides from being saved.
        "ignoreerrors": True,
        "js_runtimes": {"deno": {}, "node": {}},
    }
    if cookie_browser:
        options["cookiesfrombrowser"] = (cookie_browser,)
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=False)
        if not info or info.get("_type") in ("playlist", "multi_video"):
            raise ValueError("could not load a single video; use an individual video URL")
        output = output_folder(directory, info.get("title") or info["id"], info["id"], slug)
        metadata_path = output / "lecture.json"
        if metadata_path.exists() and json.loads(metadata_path.read_text())["id"] != info["id"]:
            raise ValueError("this slug belongs to another video; choose a different --slug")
        if not preview:
            check_output(output)
        output.mkdir(parents=True, exist_ok=True)
        code, automatic = caption_language(info, language)
        media = Path(media_directory) if media_directory is not None else output / "video"
        downloader.params.update({
            "outtmpl": {"default": str(media).replace("%", "%%") + "/%(id)s.%(ext)s"},
            "writesubtitles": bool(code), "writeautomaticsub": bool(code),
            "subtitleslangs": [code] if code else [], "subtitlesformat": "json3",
        })
        info = downloader.process_ie_result(info, download=True)
        if not info:
            raise ValueError("video download failed")
        path = Path(downloader.prepare_filename(info))
        if not path.is_file():
            raise ValueError("video download failed; see downloader warnings above")
        metadata = {"id": info["id"], "title": info.get("title"), "source": url,
                    "width": info.get("width"), "height": info.get("height"),
                    "duration": info.get("duration")}
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if code:
            save_transcript(info, output, code, automatic)
        else:
            print(f"Warning: no captions available for {language!r}; continuing with slides. No speech-to-text is run.", file=sys.stderr)
    return path, output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", help="YouTube URL or local video path")
    parser.add_argument("-o", "--output", type=Path, default=Path("~/Downloads"), help="parent directory; results go in a lecture-slug subfolder (default: ~/Downloads)")
    parser.add_argument("--slug", type=slug_value, help="human/agent-chosen search-friendly folder name, e.g. grok-bot-always-on-agents")
    parser.add_argument("--keep-video", action="store_true", help="retain downloaded video; otherwise temporary video is deleted, including on failure")
    parser.add_argument("--build-viewer", type=Path, metavar="FOLDER", help="build/rebuild index.html for existing slides, without downloading video")
    parser.add_argument("--language", default="en", help="transcript language code, e.g. en, nl, fr (default: en)")
    parser.add_argument("--interval", type=positive, default=1.0, help="seconds between samples (default: 1)")
    parser.add_argument("--settle", type=positive, default=2.0, help="seconds a slide must remain stable (default: 2)")
    parser.add_argument("--change", type=fraction, default=0.015, help="changed area fraction to count as a new slide (default: .015)")
    parser.add_argument("--stability", type=fraction, default=0.003, help="allowed motion fraction while settling (default: .003)")
    parser.add_argument("--ignore", action="append", type=rectangle, default=[], help="ignore presenter region for detection only: x,y,w,h or bottom-right etc.; repeatable")
    parser.add_argument("--crop", type=rectangle, default=(0, 0, 1, 1), help="slide region to save, in original-video fractions: x,y,w,h")
    parser.add_argument("--preview", action="store_true", help="save first frame as preview.png without extracting slides")
    parser.add_argument("--cookies-from-browser", metavar="BROWSER", help="explicitly use browser cookies for downloads, e.g. firefox")
    args = parser.parse_args()
    if args.stability >= args.change:
        parser.error("--stability must be less than --change")
    if not args.build_viewer and not args.source:
        parser.error("provide SOURCE, or use --build-viewer FOLDER")
    args.output = args.output.expanduser()
    try:
        if args.build_viewer:
            output = args.build_viewer.expanduser().resolve()
            manifest = json.loads((output / "slides.json").read_text(encoding="utf-8"))
            metadata_path = output / "lecture.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
            source = metadata.get("source") or manifest.get("source")
            ensure_transcript(source, output, args.language)
            print(build_viewer(output, title=metadata.get("title"), source=source))
            return
        with ExitStack() as stack:
            local = Path(args.source).expanduser()
            if local.is_file():
                video = local.resolve()
                output = output_folder(args.output, video.stem, slug=args.slug)
                if not args.preview:
                    check_output(output)
                    print("Note: local input has no YouTube captions; no transcript will be downloaded.", file=sys.stderr)
            elif args.source.startswith(("https://", "http://")):
                media = None if args.keep_video else Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="lecture-slides-")))
                video, output = download(args.source, args.output, args.cookies_from_browser,
                                         language=args.language, preview=args.preview,
                                         slug=args.slug, media_directory=media)
                ensure_transcript(args.source, output, args.language)
            else:
                raise ValueError("source must be an existing local video or an HTTP(S) URL")
            if args.preview:
                output.mkdir(parents=True, exist_ok=True)
                _, frame = next(sample_frames(video, args.interval))
                path = output / "preview.png"
                if not cv2.imwrite(str(path), frame):
                    raise OSError(f"could not write {path}")
                print(path)
                return
            slides = extract(video, output, interval=args.interval, settle=args.settle,
                             change=args.change, stability=args.stability, crop=args.crop,
                             ignored=args.ignore, source=args.source,
                             video_retained=local.is_file() or args.keep_video)
            metadata_path = output / "lecture.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
            print(build_viewer(output, title=metadata.get("title"), source=args.source))
            print(f"Saved {len(slides)} slides to {output}")
            if not slides:
                print("No stable slides found. Check --ignore or lower --settle / raise --stability.", file=sys.stderr)
    except (ValueError, OSError, av.error.FFmpegError, yt_dlp.utils.DownloadError, StopIteration) as error:
        parser.exit(1, f"Error: {error or 'no video frames found'}\n")


if __name__ == "__main__":
    main()
