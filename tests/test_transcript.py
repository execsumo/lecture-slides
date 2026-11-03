import json
import sys

import pytest
import yt_dlp

import lecture_slides
from lecture_slides import caption_language, download, output_folder, save_transcript


def test_language_prefers_manual_and_regional_fallback():
    info = {"subtitles": {"en-GB": []}, "automatic_captions": {"en": []}}
    assert caption_language(info, "en") == ("en-GB", False)
    assert caption_language(info, "nl") == (None, False)
    assert caption_language({"automatic_captions": {"en": []}}, "en") == ("en", True)


def test_safe_folder_names(tmp_path):
    path = output_folder(tmp_path, "../../A lecture / with slash", "test123")
    assert path.parent == tmp_path
    assert path.name == "a-lecture-with-slash-test123"
    assert len(output_folder(tmp_path, "文" * 300, "abc").name.encode()) <= 255
    assert output_folder(tmp_path, "...").name == "lecture"
    assert output_folder(tmp_path, "Ignored title", "id", slug="grok-bot-always-on-agents").name == "grok-bot-always-on-agents"


def test_json3_timestamped_transcript(tmp_path):
    raw = tmp_path / "captions.json3"
    raw.write_text(json.dumps({"events": [
        {"tStartMs": 1000, "dDurationMs": 3000, "segs": [{"utf8": "Hello "}, {"utf8": "world"}]},
        {"tStartMs": 2000, "dDurationMs": 3000, "segs": [{"utf8": "world again"}]},
        {"tStartMs": 5000, "dDurationMs": 1000, "segs": [{"utf8": "again"}]},
        {"tStartMs": 6000, "segs": [{"utf8": "\n"}]},
    ]}))
    info = {"title": "Lecture", "requested_subtitles": {"en": {"filepath": str(raw), "ext": "json3"}}}
    save_transcript(info, tmp_path, "en", True)
    data = json.loads((tmp_path / "transcript.json").read_text())
    assert data["automatic"] is True
    assert [s["text"] for s in data["segments"]] == ["Hello world", "again", "again"]
    assert (tmp_path / "transcript.txt").read_text().startswith("[00:00:01.000] Hello world\n")


def test_subtitle_failure_is_nonfatal(tmp_path, capsys):
    save_transcript({}, tmp_path, "en", True)
    assert "Warning" in capsys.readouterr().err
    assert not (tmp_path / "transcript.txt").exists()


def test_real_downloader_processing_saves_video_and_captions(monkeypatch, tmp_path):
    """Use real yt-dlp metadata/output processing, but replace network I/O."""
    video_path = tmp_path / "input.webm"
    video_path.write_bytes(b"fake video for downloader plumbing")
    info = {
        "id": "abc123", "title": "100% lecture / intro", "extractor": "test",
        "webpage_url": "https://example.com/video", "extractor_key": "Test",
        "url": "https://example.com/video.webm", "ext": "webm", "vcodec": "vp9", "acodec": "none",
        "subtitles": {"en": [{"ext": "json3", "url": "https://example.com/en.json3",
            "data": json.dumps({"events": [{"tStartMs": 0, "dDurationMs": 1000,
                                            "segs": [{"utf8": "Welcome"}]}]})}]},
    }
    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", lambda *args, **kwargs: dict(info))

    def fake_dl(self, name, video_info, *args, **kwargs):
        from pathlib import Path
        Path(name).parent.mkdir(parents=True, exist_ok=True)
        Path(name).write_bytes(video_path.read_bytes())
        return True, True

    monkeypatch.setattr(yt_dlp.YoutubeDL, "dl", fake_dl)
    video, output = download("https://example.com/video", tmp_path / "chosen")
    assert output.name == "100-lecture-intro-abc123"
    assert output.parent == tmp_path / "chosen"
    assert video.is_file()
    assert (output / "transcript.txt").read_text() == "[00:00:00.000] Welcome\n"
    assert (output / "transcript.json").is_file()
    # A second run must stop before downloading or overwriting completed output.
    (output / "slides.json").write_text("{}")
    with pytest.raises(ValueError, match="already contains"):
        download("https://example.com/video", tmp_path / "chosen")


def test_caption_download_error_still_downloads_video(monkeypatch, tmp_path, capsys):
    info = {
        "id": "no-captions", "title": "Restricted captions", "extractor": "test",
        "webpage_url": "https://example.com/video", "extractor_key": "Test",
        "url": "https://example.com/video.webm", "ext": "webm", "vcodec": "vp9", "acodec": "none",
        "automatic_captions": {"en": [{"ext": "json3", "url": "https://example.com/en.json3"}]},
    }
    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", lambda *args, **kwargs: dict(info))

    def fake_dl(self, name, video_info, *args, **kwargs):
        from pathlib import Path
        if kwargs.get("subtitle"):
            raise yt_dlp.utils.DownloadError("captions blocked")
        Path(name).parent.mkdir(parents=True, exist_ok=True)
        Path(name).write_bytes(b"video")
        return True, True

    monkeypatch.setattr(yt_dlp.YoutubeDL, "dl", fake_dl)
    video, output = download("https://example.com/video", tmp_path)
    assert video.is_file()
    assert not (output / "transcript.txt").exists()
    assert "continuing with slides" in capsys.readouterr().err


def test_local_cli_uses_stem_folder(monkeypatch, tmp_path):
    video = tmp_path / "Local lecture.mkv"
    video.touch()
    chosen = tmp_path / "chosen"
    observed = {}

    def fake_extract(video, output, **kwargs):
        observed["output"] = output
        return []

    monkeypatch.setattr(lecture_slides, "extract", fake_extract)
    monkeypatch.setattr(lecture_slides, "build_viewer", lambda output, **kw: output / "index.html")
    monkeypatch.setattr(sys, "argv", ["lecture-slides", str(video), "-o", str(chosen)])
    lecture_slides.main()
    assert observed["output"] == chosen / "local-lecture"
