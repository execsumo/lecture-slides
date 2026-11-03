from copy import deepcopy
import json
from urllib.parse import quote

import pytest

from lecture_slides.alignment import align_lecture, write_lecture


def slide(start, name="slide.png", captured=None):
    return {"file": name, "url": "./" + quote(name, safe="/"),
            "stable_since_seconds": start,
            "timestamp_seconds": start if captured is None else captured}


def cue(start, end, text):
    return {"start_seconds": start, "end_seconds": end, "text": text}


def align(slides, segments, duration=100, **kwargs):
    return align_lecture(slides, segments, title=kwargs.get("title", "Lecture"),
                         source=kwargs.get("source", "https://example.com/watch"), duration=duration)


def words(lecture):
    return " ".join(p["text"] for p in lecture["paragraphs"])


def test_provider_fragments_join_without_rewriting_or_mutation():
    slides = [slide(0)]
    segments = [cue(0, 2, "  This is"), cue(2, 4, "a whole sentence."),
                cue(4, 8, "And another one!  ")]
    original = deepcopy((slides, segments))
    lecture = align(slides, segments)
    assert words(lecture) == "This is a whole sentence. And another one!"
    assert len(lecture["paragraphs"]) == 1
    assert (slides, segments) == original


def test_transition_inside_sentence_is_deferred_to_next_sentence():
    lecture = align([slide(0), slide(3)], [cue(0, 4, "A sentence"),
                                        cue(4, 8, "continues here."), cue(8, 10, "Next sentence.")])
    assert [p["text"] for p in lecture["paragraphs"]] == [
        "A sentence continues here.", "Next sentence."]
    assert [p["slide_index"] for p in lecture["paragraphs"]] == [0, 1]
    assert [p["start_seconds"] for p in lecture["paragraphs"]] == [0, 8]
    assert all(p["timestamp"] for p in lecture["paragraphs"])


def test_multiple_slides_inside_one_sentence_leave_empty_sections(tmp_path):
    lecture = align([slide(0), slide(2), slide(4), slide(6)],
                    [cue(0, 8, "One uninterrupted sentence."), cue(8, 10, "Then this.")])
    assert [len(s["paragraphs"]) for s in lecture["slides"]] == [1, 0, 0, 1]
    write_lecture(tmp_path, lecture)
    markdown = (tmp_path / "lecture.md").read_text()
    assert markdown.count("No sentence starts on this slide") == 2
    assert markdown.count("One uninterrupted sentence") == 1


def test_sentence_time_uses_character_offset_in_cue():
    lecture = align([slide(0), slide(5)], [cue(0, 10, "One. Two.")])
    assert len(lecture["paragraphs"]) == 2
    assert lecture["paragraphs"][1]["start_seconds"] == pytest.approx(10 * 5 / 9)


def test_overlapping_provider_cues_have_monotonic_sentence_times():
    lecture = align([slide(i) for i in range(10)], [
        cue(0, 100, "First. Second. Third."), cue(3, 4, "Fourth. Fifth."),
        cue(4, 20, "Sixth. Seventh."), cue(5, 6, "Eighth.")])
    paragraphs = lecture["paragraphs"]
    times = [p["start_seconds"] for p in paragraphs]
    assert times == sorted(times)
    assert all(p["start_seconds"] <= p["end_seconds"] for p in paragraphs)
    assert all(a["end_seconds"] <= b["start_seconds"] for a, b in zip(paragraphs, paragraphs[1:]))
    assert "First. Second. Third. Fourth. Fifth. Sixth. Seventh. Eighth." == words(lecture)


@pytest.mark.parametrize("segments", [[], [cue(0, 2, " \n ")]])
def test_no_transcript_keeps_all_slide_windows(segments, tmp_path):
    lecture = align([slide(2, captured=3), slide(10)], segments, duration=10)
    assert lecture["paragraphs"] == []
    assert [(s["start_seconds"], s["end_seconds"]) for s in lecture["slides"]] == [(2, 10), (10, 10)]
    assert lecture["slides"][0]["captured_at_seconds"] == 3
    write_lecture(tmp_path, lecture)
    assert (tmp_path / "lecture.md").read_text().count("No sentence starts on this slide") == 2


def test_abbreviations_initials_and_decimals_do_not_create_slide_markers():
    text = "Dr. A. Smith uses e.g. 3.14 units, etc. in this example. Next sentence."
    lecture = align([slide(0), slide(1)], [cue(0, 20, text)])
    assert [p["text"] for p in lecture["paragraphs"]] == [
        "Dr. A. Smith uses e.g. 3.14 units, etc. in this example.", "Next sentence."]
    assert words(lecture) == text


@pytest.mark.parametrize("text", ['He said, "Stop!" Next sentence.', 'He said, “Stop!” Next sentence.',
                                       "Is it done? Yes."])
def test_sentence_punctuation_and_closing_quotes(text):
    lecture = align([slide(0), slide(1)], [cue(0, 10, text)])
    assert len(lecture["paragraphs"]) == 2
    assert words(lecture) == text


def test_three_sentence_paragraph_limit_and_marker_only_once():
    lecture = align([slide(0)], [cue(0, 10, "One. Two. Three. Four. Five. Six. Seven.")])
    assert [p["text"] for p in lecture["paragraphs"]] == [
        "One. Two. Three.", "Four. Five. Six.", "Seven."]
    assert [p["timestamp"] for p in lecture["paragraphs"]] == [True, False, False]


def test_punctuation_poor_wrapping_never_invents_slide_boundary():
    text = " ".join(f"word{i}" for i in range(300))
    lecture = align([slide(0), slide(2), slide(4)], [cue(0, 20, text)])
    assert len(lecture["paragraphs"]) > 2
    assert all(len(p["text"]) <= 650 for p in lecture["paragraphs"])
    assert all(p["slide_index"] == 0 for p in lecture["paragraphs"])
    assert sum(p["timestamp"] for p in lecture["paragraphs"]) == 1
    assert words(lecture) == text
    assert not lecture["slides"][1]["paragraphs"]


def test_wrapping_defers_transition_until_a_real_sentence_boundary():
    first = " ".join(["continuing"] * 160) + "."
    lecture = align([slide(0), slide(2), slide(4)], [cue(0, 20, first + " A new sentence.")])
    assert all(p["slide_index"] == 0 for p in lecture["paragraphs"][:-1])
    assert lecture["paragraphs"][-1]["text"] == "A new sentence."
    assert lecture["paragraphs"][-1]["slide_index"] == 2
    assert lecture["paragraphs"][-1]["timestamp"] is True
    assert words(lecture) == first + " A new sentence."


def test_character_limit_breaks_at_sentence_boundary_when_possible():
    sentences = ["a" * 300 + ".", "b" * 300 + ".", "c" * 300 + "."]
    lecture = align([slide(0)], [cue(0, 10, " ".join(sentences))])
    assert [p["text"] for p in lecture["paragraphs"]] == [" ".join(sentences[:2]), sentences[2]]


def test_intro_before_first_slide_and_first_represented_slide_marker():
    intro = align([slide(5)], [cue(0, 2, "Introduction.")])
    assert intro["paragraphs"][0]["slide_index"] == 0
    later = align([slide(0), slide(5)], [cue(6, 8, "Later speech.")])
    assert later["paragraphs"][0]["slide_index"] == 1
    assert later["paragraphs"][0]["timestamp"] is True
    assert later["slides"][0]["paragraphs"] == []


def test_machine_schema_and_shared_paragraphs():
    lecture = align([slide(2, captured=3), slide(10)], [cue(2, 6, "Speech.")], duration=20)
    assert set(lecture) == {"title", "source", "duration_seconds", "timing_note", "paragraphs", "slides"}
    assert set(lecture["slides"][0]) == {"number", "image", "start_seconds", "end_seconds",
                                         "captured_at_seconds", "paragraphs"}
    assert set(lecture["paragraphs"][0]) == {"start_seconds", "end_seconds", "text", "slide_index", "timestamp"}
    assert lecture["slides"][0]["paragraphs"][0] is lecture["paragraphs"][0]
    assert "approximate" in lecture["timing_note"]
    assert "[transcript.json](transcript.json)" in lecture["timing_note"]


def test_markdown_links_images_safely_and_preserves_raw_json(tmp_path):
    filename = 'nested/slide #?%() <tag>你好.png'
    attack = '<script>alert(1)</script> [click](javascript:alert(1)) ![x](evil)'
    segments = [cue(0, 8, attack)]
    raw = json.dumps({"segments": segments}, ensure_ascii=False).encode()
    (tmp_path / "transcript.json").write_bytes(raw)
    lecture = align([slide(0, filename)], segments, title=attack, source=attack)
    write_lecture(tmp_path, lecture)
    markdown = (tmp_path / "lecture.md").read_text()
    assert f"![Slide 1](./{quote(filename, safe='/')})" in markdown
    assert "<script>" not in markdown
    assert "[click](javascript:" not in markdown
    assert "&lt;script&gt;" in markdown
    assert (tmp_path / "transcript.json").read_bytes() == raw
    assert json.loads((tmp_path / "lecture-aligned.json").read_text()) == lecture
    assert lecture["title"] == attack
    assert words(lecture) == attack
    assert attack in (tmp_path / "transcript.txt").read_text()


def test_no_slides_retains_transcript_and_writes_markdown(tmp_path):
    lecture = align([], [cue(0, 1, "Speech without images.")])
    assert lecture["slides"] == []
    assert lecture["paragraphs"][0]["slide_index"] is None
    write_lecture(tmp_path, lecture)
    assert "Speech without images" in (tmp_path / "lecture.md").read_text()


def test_readable_text_timestamps_only_at_new_slide_sentence(tmp_path):
    lecture = align([slide(0), slide(3)], [cue(0, 4, "A sentence"),
                                        cue(4, 8, "continues here."), cue(8, 10, "Next sentence.")])
    write_lecture(tmp_path, lecture)
    assert (tmp_path / "transcript.txt").read_text() == (
        "[00:00:00] A sentence continues here.\n\n[00:00:08] Next sentence.\n"
    )


def test_zero_duration_empty_lecture():
    lecture = align([slide(0)], [], duration=0)
    assert lecture["slides"][0]["end_seconds"] == 0
    assert lecture["paragraphs"] == []
