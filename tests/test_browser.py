"""Optional real-browser checks: uv run --with playwright python -m pytest tests/test_browser.py."""

import json
import os

import cv2
import numpy as np
import pytest

from lecture_slides.viewer import build_viewer

playwright = pytest.importorskip("playwright.sync_api")


def test_modal_and_bidirectional_sync(tmp_path):
    slides = []
    for i in range(3):
        filename = f"slide-{i}.png"
        cv2.imwrite(str(tmp_path / filename), np.full((180, 320, 3), 80 + i * 60, dtype=np.uint8))
        slides.append({"file": filename, "timestamp_seconds": i * 20 + 2, "stable_since_seconds": i * 20})
    (tmp_path / "slides.json").write_text(json.dumps({"source": "https://www.youtube.com/watch?v=test123", "slides": slides}))
    (tmp_path / "transcript.json").write_text(json.dumps({"segments": [
        {"start_seconds": i, "end_seconds": i + 1, "text": f"Transcript segment {i}. " * 4}
        for i in range(60)
    ]}))
    build_viewer(tmp_path)
    with playwright.sync_playwright() as p:
        executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        browser = p.chromium.launch(headless=True, **({"executable_path": executable} if executable else {}))
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto((tmp_path / "index.html").as_uri())
        assert page.locator(".card").count() == 3
        page.locator(".card").nth(1).click()
        assert page.locator("#viewer").evaluate("e => e.open")
        assert "Slide 2 of 3" in page.locator("#modal-title").inner_text()
        assert page.locator(".segment[aria-current=true] time").inner_text() == "00:00:20"
        assert page.locator("#modal-source").get_attribute("href").endswith("&t=22s")
        assert page.locator("#large").evaluate("e => e.complete && e.naturalWidth") == 320
        page.evaluate("""() => {
            const reading=document.getElementById('reading'), line=document.querySelectorAll('.segment')[45];
            reading.scrollTop += line.getBoundingClientRect().top-reading.getBoundingClientRect().top-8;
        }""")
        page.wait_for_function("document.getElementById('modal-title').textContent.includes('Slide 3 of 3')")
        top = page.locator("#reading").evaluate("e => e.scrollTop")
        page.wait_for_timeout(150)
        assert abs(page.locator("#reading").evaluate("e => e.scrollTop") - top) < 1
        for key, expected in [("ArrowLeft", 2), ("ArrowDown", 1), ("ArrowUp", 2), ("ArrowRight", 3)]:
            page.keyboard.press(key)
            assert f"Slide {expected} of 3" in page.locator("#modal-title").inner_text()
        before = page.locator(".image-stage").bounding_box()["width"]
        page.locator("#transcript summary").click()
        assert page.locator(".image-stage").bounding_box()["width"] > before
        page.keyboard.press("Escape")
        assert not page.locator("#viewer").evaluate("e => e.open")
        assert page.locator(".card").nth(1).evaluate("e => e===document.activeElement")
        page.locator("#transcript summary").click()
        page.wait_for_function("document.getElementById('reading').scrollTop>0")
        page.locator("#reading").evaluate("e => e.scrollTop=0")
        page.wait_for_function("document.querySelector('.card[aria-current=true] strong').textContent==='1'")
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator(".card").nth(0).click()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not errors
        browser.close()
