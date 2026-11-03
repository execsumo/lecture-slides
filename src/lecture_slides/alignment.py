"""Local, approximate sentence alignment shared by the reader and exports."""

from bisect import bisect_right
import html
import json
from pathlib import Path
import re
from urllib.parse import quote


_TIMING_NOTE = (
    "Sentence alignment is approximate: sentence times use character offsets within "
    "provider cues, capped at the next cue start when cues overlap. Slides are assigned "
    "at sentence starts, not mid-sentence transitions. A sentence crossing a slide "
    "boundary remains associated with the slide where it began. Read the unchanged raw "
    "[transcript.json](transcript.json) for original provider timing."
)
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e",
    "fig", "no", "inc", "approx", "dept", "a.m", "p.m",
}
_ENDING = re.compile(r'''[.!?]+["'”’»\)\]]*(?=\s|$)''')


def _sentence_ranges(text):
    """Keep punctuation/quotes; a trailing unpunctuated fragment is not a new boundary."""
    start = 0
    for match in _ENDING.finditer(text):
        punctuation = match.group().rstrip('"\'”’») ]')
        if punctuation == "." and match.end() < len(text):
            token = re.search(r"([\w.]+)\.$", text[:match.start() + 1])
            word = token[1].lower() if token else ""
            # shortcut: initials and common abbreviations are conservative non-boundaries.
            if word in _ABBREVIATIONS or re.fullmatch(r"(?:[a-z]\.)*[a-z]", word):
                continue
        end = match.end()
        yield start, end
        start = end
        while start < len(text) and text[start].isspace():
            start += 1
    if start < len(text):
        yield start, len(text)


def _transcript(segments):
    pieces, spans = [], []
    offset = 0
    for index, cue in enumerate(segments):
        text = " ".join(cue["text"].split())
        if not text:
            continue
        if pieces:
            pieces.append(" ")
            offset += 1
        end = cue["end_seconds"]
        if index + 1 < len(segments):
            end = min(end, segments[index + 1]["start_seconds"])
        spans.append((offset, offset + len(text), cue["start_seconds"], end))
        pieces.append(text)
        offset += len(text)
    return "".join(pieces), spans


def _wrap(text, start, end):
    """Wrap an oversized unit without asserting any additional sentence boundaries."""
    while end - start > 650:
        cut = text.rfind(" ", start, start + 651)
        if cut <= start:
            cut = text.find(" ", start + 650, end)
        if cut < 0:
            break
        yield start, cut
        start = cut + 1
    if start < end:
        yield start, end


def align_lecture(slides, segments, *, title, source, duration):
    """Return paragraphs and all slide windows from already validated, sorted inputs.

    Paragraph slide_index values are zero-based (None with no slides). Introductory
    speech belongs to the first slide. Inputs, including raw cue text, are untouched.
    """
    text, spans = _transcript(segments)
    offsets = [span[0] for span in spans]
    starts = [slide["stable_since_seconds"] for slide in slides]

    def time_at(position):
        left, right, start, end = spans[max(0, bisect_right(offsets, position) - 1)]
        return start + (end - start) * min(1, (position - left) / (right - left))

    paragraphs = []
    pending = None
    count = 0
    for left, right in _sentence_ranges(text):
        sentence_slide = max(0, bisect_right(starts, time_at(left)) - 1) if slides else None
        for part_left, part_right in _wrap(text, left, right):
            if (pending is not None and pending[2] == sentence_slide and count < 3
                    and part_right - pending[0] <= 650):
                pending = (pending[0], part_right, sentence_slide)
                count += 1
            else:
                if pending is not None:
                    paragraphs.append(pending)
                pending = (part_left, part_right, sentence_slide)
                count = 1
    if pending is not None:
        paragraphs.append(pending)

    result = []
    for left, right, index in paragraphs:
        result.append({
            "start_seconds": time_at(left), "end_seconds": time_at(right),
            "text": text[left:right], "slide_index": index,
            "timestamp": not result or result[-1]["slide_index"] != index,
        })
    sections = [{
        "number": i + 1, "image": slide["url"],
        "start_seconds": slide["stable_since_seconds"],
        "end_seconds": starts[i + 1] if i + 1 < len(slides) else duration,
        "captured_at_seconds": slide["timestamp_seconds"], "paragraphs": [],
    } for i, slide in enumerate(slides)]
    for paragraph in result:
        if paragraph["slide_index"] is not None:
            sections[paragraph["slide_index"]]["paragraphs"].append(paragraph)
    return {
        "title": title, "source": source, "duration_seconds": duration,
        "timing_note": _TIMING_NOTE, "paragraphs": result, "slides": sections,
    }


def _markdown_text(value):
    # Escape Markdown too: HTML escaping alone still permits attacker-supplied links.
    value = html.escape(" ".join(str(value).split()), quote=True)
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", value)


def _clock(seconds):
    hours, remainder = divmod(int(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def write_lecture(output, lecture):
    """Write aligned companions and readable transcript.txt; preserve transcript.json."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    lines = [f"# {_markdown_text(lecture['title'])}", "",
             f"Source: {_markdown_text(lecture['source'] or 'Not provided')}", "",
             f"Duration: {_clock(lecture['duration_seconds'])}", "", lecture["timing_note"], ""]

    def add_paragraphs(paragraphs):
        for paragraph in paragraphs:
            marker = f"[{_clock(paragraph['start_seconds'])}] " if paragraph["timestamp"] else ""
            lines.extend([marker + _markdown_text(paragraph["text"]), ""])

    for slide in lecture["slides"]:
        lines.extend([
            f"## Slide {slide['number']} · {_clock(slide['start_seconds'])}–{_clock(slide['end_seconds'])}",
            "", f"![Slide {slide['number']}]({quote(slide['image'], safe='/%')})", "",
        ])
        if slide["paragraphs"]:
            add_paragraphs(slide["paragraphs"])
        else:
            lines.extend(["No sentence starts on this slide; speech may continue across its transition "
                          "in another slide section, or no transcript is available.", ""])
    if not lecture["slides"]:
        lines.extend(["## Transcript", ""])
        add_paragraphs(lecture["paragraphs"])
    files = [
        ("lecture-aligned.json", json.dumps(lecture, ensure_ascii=False, allow_nan=False, indent=2) + "\n"),
        ("lecture.md", "\n".join(lines)),
    ]
    if lecture["paragraphs"]:
        readable = []
        for paragraph in lecture["paragraphs"]:
            marker = f"[{_clock(paragraph['start_seconds'])}] " if paragraph["timestamp"] else ""
            readable.append(marker + paragraph["text"])
        files.append(("transcript.txt", "\n\n".join(readable) + "\n"))
    for name, content in files:
        destination = output / name
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(destination)
