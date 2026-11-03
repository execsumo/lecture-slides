"""Timed transcript export and optional Supadata fallback (no SDK dependency)."""

import json
import math
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


def write_transcript(output, transcript):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    lines = []
    for segment in transcript["segments"]:
        milliseconds = round(segment["start_seconds"] * 1000)
        hours, milliseconds = divmod(milliseconds, 3_600_000)
        minutes, milliseconds = divmod(milliseconds, 60_000)
        seconds, milliseconds = divmod(milliseconds, 1000)
        lines.append(f"[{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}] {segment['text']}")
    for name, text in (
        ("transcript.txt", "\n".join(lines) + "\n"),
        ("transcript.json", json.dumps(transcript, ensure_ascii=False, indent=2) + "\n"),
    ):
        path = output / name
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)


def has_transcript(output):
    path = Path(output) / "transcript.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        segments = data["segments"]
        return isinstance(segments, list) and bool(segments) and all(
            isinstance(s, dict) and isinstance(s.get("text"), str) and bool(s["text"].strip())
            and isinstance(s.get("start_seconds"), (int, float)) and math.isfinite(s["start_seconds"])
            and isinstance(s.get("end_seconds"), (int, float)) and math.isfinite(s["end_seconds"])
            and 0 <= s["start_seconds"] <= s["end_seconds"] for s in segments
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def normalize_supadata(data, *, source=None):
    """Supadata offset/duration are milliseconds, not seconds."""
    content = data.get("content")
    if not isinstance(content, list) or not content:
        raise ValueError("Supadata returned no timestamped transcript")
    segments = []
    for chunk in content:
        text = " ".join(chunk["text"].split())
        if not text:
            continue
        start, duration = float(chunk["offset"]) / 1000, float(chunk["duration"]) / 1000
        if not math.isfinite(start) or not math.isfinite(duration) or start < 0 or duration < 0:
            raise ValueError("invalid Supadata timestamps")
        segments.append({"start_seconds": start, "end_seconds": start + duration, "text": text})
    if not segments:
        raise ValueError("Supadata returned an empty transcript")
    segments.sort(key=lambda s: s["start_seconds"])
    return {"provider": "supadata", "mode": "native", "source": source,
            "language": data.get("lang") or content[0].get("lang"), "segments": segments}


def ensure_transcript(source, output, language="en"):
    """Reuse existing text, otherwise try existing-caption retrieval via Supadata."""
    output = Path(output)
    if has_transcript(output):
        if not (output / "transcript.txt").is_file():
            write_transcript(output, json.loads((output / "transcript.json").read_text(encoding="utf-8")))
        return True
    if not isinstance(source, str):
        return False
    try:
        parsed = urlparse(source)
    except ValueError:
        return False
    if parsed.username or parsed.password or parsed.scheme not in ("http", "https") or parsed.hostname not in (
        "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
    ):
        return False
    key = os.environ.get("SUPADATA_API_KEY")
    if not key:
        print("Warning: no transcript available; set SUPADATA_API_KEY to enable Supadata fallback.", file=sys.stderr)
        return False
    # File URLs force AI generation even in native mode; accept YouTube URLs only.
    query = urlencode({"url": source, "lang": language, "text": "false", "mode": "native"})
    request = Request("https://api.supadata.ai/v1/transcript?" + query,
                      headers={"x-api-key": key, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=45) as response:
            if response.status != 200:
                raise ValueError(f"Supadata returned HTTP {response.status}; native captions unavailable")
            body = response.read(16_000_001)
            if len(body) > 16_000_000:
                raise ValueError("Supadata transcript exceeds 16 MB")
            transcript = normalize_supadata(json.loads(body), source=source)
        write_transcript(output, transcript)
        if transcript["language"] and transcript["language"] != language:
            print(f"Warning: Supadata returned {transcript['language']!r}, not requested {language!r}.", file=sys.stderr)
        print(f"Saved Supadata transcript to {output}")
        return True
    except HTTPError as error:
        print(f"Warning: Supadata HTTP {error.code}; continuing without transcript.", file=sys.stderr)
    except (URLError, OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        # Never include request headers, API keys, or provider response bodies in logs.
        print(f"Warning: Supadata transcript unavailable ({type(error).__name__}); continuing with slides.", file=sys.stderr)
    return False
