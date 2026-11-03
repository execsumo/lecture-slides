import cv2
import numpy as np

import lecture_slides


def test_4k_output_is_not_detection_thumbnail(monkeypatch, tmp_path):
    frame = np.full((2160, 3840, 3), 240, dtype=np.uint8)
    # A one-pixel feature would be lost if the detection thumbnail were saved.
    frame[100, 100] = [7, 23, 41]
    monkeypatch.setattr(lecture_slides, "sample_frames", lambda *_: iter([(0, frame), (2, frame)]))
    slides = lecture_slides.extract("unused", tmp_path)
    assert len(slides) == 1
    saved = cv2.imread(str(tmp_path / slides[0]["file"]))
    assert saved.shape == (2160, 3840, 3)
    assert np.array_equal(saved, frame)
