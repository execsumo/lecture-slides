import html
import json
import re

import pytest

from lecture_slides.viewer import build_viewer


def manifest(output, slides=None, source=None):
    if slides is None:
        slides = [slide()]
    (output / "slides.json").write_text(json.dumps({"slides": slides, "source": source}))


def slide(file="slide-0001.png", timestamp=12, stable=10):
    return {"file": file, "timestamp_seconds": timestamp, "stable_since_seconds": stable,
            "width": 1920, "height": 1080}


def read_viewer(output, **kwargs):
    path = build_viewer(output, **kwargs)
    assert path == output / "index.html"
    document = path.read_text(encoding="utf-8")
    raw = re.search(r'<script id="viewer-data" type="application/json">(.*?)</script>',
                    document, re.S)[1]
    return document, json.loads(raw)


def test_missing_transcript_is_offline_and_preserves_manifest(tmp_path):
    manifest(tmp_path, source="https://www.youtube.com/watch?v=abc123&t=7")
    original = (tmp_path / "slides.json").read_bytes()
    document, data = read_viewer(tmp_path)
    assert data["segments"] == []
    assert data["source"] == "https://www.youtube.com/watch?v=abc123"
    assert data["slides"][0]["url"] == "./slide-0001.png"
    assert "No transcript available" in document
    assert "fetch(" not in document
    assert not re.search(r'<(?:script|link)[^>]+(?:src|href)=', document)
    assert (tmp_path / "slides.json").read_bytes() == original


def test_untrusted_title_transcript_and_filename_cannot_terminate_script(tmp_path):
    attack = '</script><script>alert("x")</script>&\u2028\u2029'
    filename = 'sub/</script><img src=x onerror=alert(1)> #?%".png'
    manifest(tmp_path, [slide(filename)])
    (tmp_path / "transcript.json").write_text(json.dumps({"title": attack, "segments": [
        {"start_seconds": 10, "end_seconds": 13, "text": attack}]}))
    document, data = read_viewer(tmp_path)
    assert f"<title>{html.escape(attack)}</title>" in document
    assert attack not in document
    assert document.count("</script>") == 2
    assert data["segments"][0]["text"] == attack
    assert data["slides"][0]["file"] == filename
    assert data["slides"][0]["url"].startswith("./sub/%3C/script%3E")
    assert "%23%3F%25%22" in data["slides"][0]["url"]
    assert "text.textContent=segment.text" in document
    assert "innerHTML" not in document


def test_explicit_title_and_source_override_metadata(tmp_path):
    manifest(tmp_path, source="https://youtu.be/old")
    (tmp_path / "transcript.json").write_text(json.dumps({"title": "Old", "segments": []}))
    document, data = read_viewer(tmp_path, title="New __DATA__ <title>",
                                 source="https://youtu.be/new?t=1")
    assert "<title>New __DATA__ &lt;title&gt;</title>" in document
    assert data["source"] == "https://www.youtube.com/watch?v=new"


@pytest.mark.parametrize("source", [
    "javascript:alert(1)", "data:text/html,hello", "file:///tmp/video.mp4",
    "https://youtube.com.evil.test/watch?v=abc", "https://evil.test/youtube.com",
    "//www.youtube.com/watch?v=abc", "https://youtube.com@evil.test/watch?v=abc",
    "https://user:password@youtube.com/watch?v=abc", "https://youtube.com/watch?v=%22%3E",
    "https://[invalid", "https://www.youtube.com/", None,
])
def test_unsafe_or_non_youtube_source_has_no_link(tmp_path, source):
    manifest(tmp_path, source=source)
    _, data = read_viewer(tmp_path)
    assert data["source"] is None


@pytest.mark.parametrize("source", [
    "https://youtu.be/abc-123", "http://www.youtube.com/watch?v=abc-123&list=playlist",
    "https://m.youtube.com/watch?v=abc-123", "https://www.youtube.com/embed/abc-123",
    "https://youtube.com/shorts/abc-123", "https://youtube.com/live/abc-123",
])
def test_youtube_urls_are_canonicalized(tmp_path, source):
    manifest(tmp_path, source=source)
    _, data = read_viewer(tmp_path)
    assert data["source"] == "https://www.youtube.com/watch?v=abc-123"


@pytest.mark.parametrize("filename", [
    "../escape.png", "sub/../../escape.png", "/tmp/slide.png", "..\\escape.png",
    "sub\\slide.png", "", ".", "null\0.png",
])
def test_rejects_paths_outside_output(tmp_path, filename):
    manifest(tmp_path, [slide(filename)])
    with pytest.raises(ValueError, match="path"):
        build_viewer(tmp_path)
    assert not (tmp_path / "index.html").exists()


def test_rejects_symlink_escape(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "escaped").symlink_to(tmp_path, target_is_directory=True)
    manifest(output, [slide("escaped/private.png")])
    with pytest.raises(ValueError, match="within output"):
        build_viewer(output)


def test_subpaths_are_encoded_and_order_is_chronological(tmp_path):
    manifest(tmp_path, [slide("masked/slide #2.png", 22, 20),
                        slide("masked/slide 你好.png", 13, 10)])
    (tmp_path / "transcript.json").write_text(json.dumps({"segments": [
        {"start_seconds": 20, "end_seconds": 25, "text": "Second"},
        {"start_seconds": 10, "end_seconds": 15, "text": "First"}]}))
    _, data = read_viewer(tmp_path)
    assert [s["stable_since_seconds"] for s in data["slides"]] == [10, 20]
    assert data["slides"][0]["timestamp_seconds"] == 13
    assert data["slides"][1]["url"] == "./masked/slide%20%232.png"
    assert [s["text"] for s in data["segments"]] == ["First", "Second"]


@pytest.mark.parametrize("value", [-1, float("inf"), float("nan"), "10", True])
def test_invalid_timestamps_are_rejected(tmp_path, value):
    manifest(tmp_path, [slide(stable=value)])
    with pytest.raises(ValueError, match="timestamp"):
        build_viewer(tmp_path)


def test_empty_slides(tmp_path):
    manifest(tmp_path, [])
    document, data = read_viewer(tmp_path)
    assert data["slides"] == []
    assert "No slides available" in document


def test_missing_manifest_does_not_create_viewer(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_viewer(tmp_path)
    assert not (tmp_path / "index.html").exists()
