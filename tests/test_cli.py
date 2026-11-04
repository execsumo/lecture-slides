import json
import sys
from pathlib import Path

import pytest

import lecture_slides


@pytest.mark.parametrize("outcome", ["success", "failure", "download-failure", "interrupt", "preview"])
def test_temporary_video_is_cleaned(monkeypatch, tmp_path, outcome):
    seen = {}

    def fake_download(url, parent, *args, media_directory=None, **kwargs):
        seen["media"] = Path(media_directory)
        video = seen["media"] / "video.mp4"
        video.write_bytes(b"test")
        if outcome == "download-failure":
            (seen["media"] / "video.part").write_bytes(b"partial")
            raise ValueError("download failure")
        output = parent / "my-lecture"
        output.mkdir()
        return video, output

    def fake_extract(video, output, **kwargs):
        assert video.is_file()
        assert kwargs["video_retained"] is False
        if outcome == "failure":
            raise ValueError("test failure")
        if outcome == "interrupt":
            raise KeyboardInterrupt
        (output / "slides.json").write_text(json.dumps({"slides": []}))
        return []

    monkeypatch.setattr(lecture_slides, "download", fake_download)
    monkeypatch.setattr(lecture_slides, "extract", fake_extract)
    monkeypatch.setattr(lecture_slides, "ensure_transcript", lambda *args: False)
    monkeypatch.setattr(lecture_slides, "build_viewer", lambda output, **kwargs: output / "index.html")
    args = ["lecture-slides", "https://example.com/video", "-o", str(tmp_path)]
    if outcome == "preview":
        import numpy as np
        monkeypatch.setattr(lecture_slides, "sample_frames", lambda *args: iter([(0, np.zeros((10, 10, 3), dtype=np.uint8))]))
        args.append("--preview")
    monkeypatch.setattr(sys, "argv", args)
    if outcome in ("failure", "download-failure"):
        with pytest.raises(SystemExit):
            lecture_slides.main()
    elif outcome == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            lecture_slides.main()
    else:
        lecture_slides.main()
    assert not seen["media"].exists()


def test_keep_video_and_slug_are_forwarded(monkeypatch, tmp_path):
    def fake_download(url, parent, *args, **kwargs):
        assert kwargs["media_directory"] is None
        assert kwargs["slug"] == "grok-bot-always-on-agents"
        video = tmp_path / "retained.mp4"
        video.touch()
        return video, tmp_path

    def fake_extract(video, output, **kwargs):
        assert kwargs["video_retained"] is True
        return []

    monkeypatch.setattr(lecture_slides, "download", fake_download)
    monkeypatch.setattr(lecture_slides, "extract", fake_extract)
    monkeypatch.setattr(lecture_slides, "ensure_transcript", lambda *args: False)
    monkeypatch.setattr(lecture_slides, "build_viewer", lambda output, **kwargs: output / "index.html")
    monkeypatch.setattr(sys, "argv", ["lecture-slides", "https://example.com/video", "-o", str(tmp_path), "--slug", "grok-bot-always-on-agents", "--keep-video"])
    lecture_slides.main()
    assert (tmp_path / "retained.mp4").exists()


def test_local_inputs_are_never_deleted(monkeypatch, tmp_path):
    video = tmp_path / "input.mp4"
    video.touch()
    monkeypatch.setattr(lecture_slides, "extract", lambda *args, **kwargs: [])
    monkeypatch.setattr(lecture_slides, "build_viewer", lambda output, **kwargs: output / "index.html")
    monkeypatch.setattr(sys, "argv", ["lecture-slides", str(video), "-o", str(tmp_path / "output")])
    lecture_slides.main()
    assert video.exists()


@pytest.mark.parametrize("slug", ["../unsafe", "Uppercase", "a/b", "a--b", "-a", "a-", "a" * 101])
def test_invalid_slug(slug):
    import argparse
    with pytest.raises(argparse.ArgumentTypeError):
        lecture_slides.slug_value(slug)


def test_build_viewer_never_downloads_video(monkeypatch, tmp_path):
    (tmp_path / "slides.json").write_text(json.dumps({"source": "https://example.com/video", "slides": []}))
    seen = {}
    monkeypatch.setattr(lecture_slides, "ensure_transcript", lambda source, *args: seen.update(source=source))
    monkeypatch.setattr(lecture_slides, "build_viewer", lambda output, **kwargs: output / "index.html")
    monkeypatch.setattr(lecture_slides, "download", lambda *args, **kwargs: pytest.fail("should not download video"))
    monkeypatch.setattr(sys, "argv", ["lecture-slides", "--build-viewer", str(tmp_path)])
    lecture_slides.main()
    assert seen["source"] == "https://example.com/video"


def test_output_defaults_to_downloads(monkeypatch, tmp_path):
    import sys
    from pathlib import Path
    import lecture_slides
    seen = {}
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(lecture_slides, "output_folder", lambda parent, stem, slug=None: seen.setdefault("parent", parent) or (_ for _ in ()).throw(SystemExit(0)))
    video = tmp_path / "talk.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(sys, "argv", ["lecture-slides", str(video)])
    try:
        lecture_slides.main()
    except BaseException:
        pass
    assert seen["parent"] == tmp_path / "Downloads"
