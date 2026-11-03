import json
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

import lecture_slides.transcripts as transcripts
from lecture_slides.transcripts import ensure_transcript, normalize_supadata, write_transcript


DATA = {"lang": "en", "content": [{"text": "Hello world", "offset": 1500, "duration": 2500}]}
SOURCE = "https://www.youtube.com/watch?v=test"


class Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, limit):
        return json.dumps(DATA).encode()


def test_offsets_are_milliseconds():
    data = normalize_supadata(DATA)
    assert data["segments"] == [{"start_seconds": 1.5, "end_seconds": 4, "text": "Hello world"}]
    assert data["provider"] == "supadata"
    assert data["mode"] == "native"


def test_fallback_auth_and_native_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPADATA_API_KEY", "secret-test-key")

    def fake_open(request, timeout):
        assert request.headers["X-api-key"] == "secret-test-key"
        query = parse_qs(urlparse(request.full_url).query)
        assert query == {"url": [SOURCE], "text": ["false"], "mode": ["native"], "lang": ["en"]}
        assert "secret-test-key" not in request.full_url
        return Response()

    monkeypatch.setattr(transcripts, "urlopen", fake_open)
    assert ensure_transcript(SOURCE, tmp_path)
    assert json.loads((tmp_path / "transcript.json").read_text())["segments"][0]["start_seconds"] == 1.5
    assert "[00:00:01.500] Hello world" in (tmp_path / "transcript.txt").read_text()


def test_existing_transcript_does_not_call_api(monkeypatch, tmp_path):
    write_transcript(tmp_path, normalize_supadata(DATA))
    monkeypatch.setattr(transcripts, "urlopen", lambda *args, **kwargs: pytest.fail("must reuse transcript"))
    assert ensure_transcript(SOURCE, tmp_path)


def test_missing_credentials_nonfatal(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("SUPADATA_API_KEY", raising=False)
    assert not ensure_transcript(SOURCE, tmp_path)
    assert "SUPADATA_API_KEY" in capsys.readouterr().err


@pytest.mark.parametrize("status", [206, 202])
def test_noncontent_2xx_nonfatal(monkeypatch, tmp_path, status):
    monkeypatch.setenv("SUPADATA_API_KEY", "secret-test-key")
    response = Response()
    response.status = status
    monkeypatch.setattr(transcripts, "urlopen", lambda *args, **kwargs: response)
    assert not ensure_transcript(SOURCE, tmp_path)
    assert not (tmp_path / "transcript.json").exists()


@pytest.mark.parametrize("code", [401, 402, 429, 500])
def test_provider_errors_no_secret_logs(monkeypatch, tmp_path, capsys, code):
    monkeypatch.setenv("SUPADATA_API_KEY", "secret-test-key")

    def fail(*args, **kwargs):
        raise HTTPError("https://example.com", code, "secret-test-key", {}, None)

    monkeypatch.setattr(transcripts, "urlopen", fail)
    assert not ensure_transcript(SOURCE, tmp_path)
    error = capsys.readouterr().err
    assert str(code) in error
    assert "secret-test-key" not in error


@pytest.mark.parametrize("source", [None, "/local/video.mp4", "https://example.com/video.mp4", "file:///video.mp4", "https://[invalid", "https://user:secret@youtube.com/watch?v=x"])
def test_never_submit_file_urls_that_force_generation(monkeypatch, tmp_path, source):
    monkeypatch.setenv("SUPADATA_API_KEY", "secret-test-key")
    monkeypatch.setattr(transcripts, "urlopen", lambda *args, **kwargs: pytest.fail("must not submit this source"))
    assert not ensure_transcript(source, tmp_path)


@pytest.mark.parametrize("content", [[], "plain text", [{"text": "x", "offset": -1, "duration": 3}], [{"text": "x", "offset": float("nan"), "duration": 3}]])
def test_invalid_provider_data(content):
    with pytest.raises(ValueError):
        normalize_supadata({"content": content})
