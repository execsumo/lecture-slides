import argparse
import json

import av
import cv2
import numpy as np
import pytest

import lecture_slides
from lecture_slides import Detector, download, extract, rectangle, sample_frames, timestamp


def make_lecture(path):
    """Three 4-second slides plus a moving bottom-right presenter, lossless."""
    with av.open(str(path), "w") as output:
        stream = output.add_stream("ffv1", rate=5)
        stream.width, stream.height, stream.pix_fmt = 640, 360, "bgr0"
        for i in range(60):
            frame = np.full((360, 640, 3), 245, dtype=np.uint8)
            slide = i // 20
            cv2.putText(frame, f"SLIDE {slide}", (40, 90), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 4)
            cv2.rectangle(frame, (40, 130), (180 + slide * 130, 260), (30, 30, 30), -1)
            frame[252:, 448:] = (i * 71) % 256
            encoded = av.VideoFrame.from_ndarray(frame, format="bgr24")
            for packet in stream.encode(encoded):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)


def test_native_resolution_timestamps_and_presenter_mask(tmp_path):
    video = tmp_path / "lecture.mkv"
    make_lecture(video)
    slides = extract(video, tmp_path / "slides", interval=0.5, settle=1,
                     ignored=[rectangle("bottom-right")])
    assert len(slides) == 3
    assert [s["timestamp_seconds"] for s in slides] == pytest.approx([1.2, 5.4, 9.6])
    for slide in slides:
        image = cv2.imread(str(tmp_path / "slides" / slide["file"]))
        assert image.shape == (360, 640, 3)
        assert timestamp(slide["timestamp_seconds"]) in slide["file"]
    manifest = json.loads((tmp_path / "slides/slides.json").read_text())
    assert manifest["slides"] == slides
    with pytest.raises(ValueError, match="already contains"):
        extract(video, tmp_path / "slides")


def test_crop_preserves_native_pixels_and_ignores_external_regions():
    detector = Detector(1000, 600, (0, 0, .7, 1), [rectangle("bottom-right")])
    frame = np.zeros((600, 1000, 3), dtype=np.uint8)
    assert detector.image(frame).shape == (600, 700, 3)
    a = detector.fingerprint(frame)
    frame[420:, 700:] = 255
    assert detector.difference(a, detector.fingerprint(frame)) == 0


def test_mask_removes_motion_but_keeps_slide_content():
    detector = Detector(640, 360, (0, 0, 1, 1), [rectangle("bottom-right")])
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    a = detector.fingerprint(frame)
    frame[252:, 448:] = 255
    assert detector.difference(a, detector.fingerprint(frame)) == 0
    frame[40:180, 40:300] = 255
    assert detector.difference(a, detector.fingerprint(frame)) > .1


@pytest.mark.parametrize("value", ["0,0,0,1", "0,0,2,1", "nan,0,.1,.1", "0,0,.1", "-1,0,1,1"])
def test_bad_rectangle(value):
    with pytest.raises(argparse.ArgumentTypeError):
        rectangle(value)


def test_fully_masked_region():
    with pytest.raises(ValueError, match="entire"):
        Detector(640, 360, (0, 0, 1, 1), [(0, 0, 1, 1)])


def test_sampling_uses_video_timestamps(tmp_path):
    video = tmp_path / "lecture.mkv"
    make_lecture(video)
    times = [t for t, _ in sample_frames(video, 1)]
    assert times == pytest.approx(list(range(12)))


def test_timestamp_carry():
    assert timestamp(3599.9999) == "01-00-00.000"


def test_download_requests_native_best_video(monkeypatch, tmp_path):
    seen = {}

    class Downloader:
        def __init__(self, options):
            seen.update(options)
            self.params = options

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download):
            assert download is False
            return {"id": "lecture", "title": "A lecture"}

        def process_ie_result(self, info, download):
            assert download is True
            (tmp_path / "lecture.webm").touch()
            return info

        def prepare_filename(self, info):
            return str(tmp_path / "lecture.webm")

    monkeypatch.setattr(lecture_slides.yt_dlp, "YoutubeDL", Downloader)
    video, output = download("https://www.youtube.com/watch?v=test", tmp_path)
    assert video == tmp_path / "lecture.webm"
    assert output == tmp_path / "a-lecture-lecture"
    assert seen["format"] == "bestvideo/best"
    assert seen["format_sort"][0] == "res"
    assert seen["noplaylist"] is True
    assert "cookiesfrombrowser" not in seen


def test_transition_frame_is_not_saved(monkeypatch, tmp_path):
    a = np.full((360, 640, 3), 255, dtype=np.uint8)
    b = a.copy()
    b[50:250, 50:400] = 0
    transition = np.full_like(a, 100)
    frames = [(0, a), (1, a), (2, a), (3, transition), (4, b), (5, b), (6, b)]
    monkeypatch.setattr(lecture_slides, "sample_frames", lambda *_: iter(frames))
    slides = extract("unused", tmp_path, settle=2)
    assert [s["timestamp_seconds"] for s in slides] == [2, 6]


def test_short_clip_writes_empty_manifest(monkeypatch, tmp_path):
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    monkeypatch.setattr(lecture_slides, "sample_frames", lambda *_: iter([(0, frame)]))
    assert extract("unused", tmp_path) == []
    assert json.loads((tmp_path / "slides.json").read_text())["slides"] == []
