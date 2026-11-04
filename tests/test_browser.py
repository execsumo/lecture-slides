"""Optional real-browser checks: uv run --with playwright python -m pytest tests/test_browser.py."""

import json
import os

import cv2
import numpy as np
import pytest

from lecture_slides.viewer import build_viewer

playwright = pytest.importorskip("playwright.sync_api")


def make_lecture(tmp_path):
    slides = []
    starts = [0, 10, 40]
    for i in range(3):
        filename = f"slide-{i}.png"
        cv2.imwrite(str(tmp_path / filename), np.full((180, 320, 3), 80 + i * 60, dtype=np.uint8))
        slides.append({"file": filename, "timestamp_seconds": starts[i] + 2, "stable_since_seconds": starts[i]})
    (tmp_path / "slides.json").write_text(json.dumps({"source": "https://www.youtube.com/watch?v=test123", "slides": slides}))
    (tmp_path / "transcript.json").write_text(json.dumps({"title": "My <Lecture>", "segments": [
        {"start_seconds": i, "end_seconds": i + 1, "text": f"This is readable sentence {i} with enough words to exercise transcript scrolling."}
        for i in range(60)
    ]}))
    build_viewer(tmp_path)


def launch(p):
    executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    return p.chromium.launch(headless=True, **({"executable_path": executable} if executable else {}))


def title(page):
    return page.locator("#slide-label").inner_text()


def test_layout_sync_and_navigation(tmp_path):
    make_lecture(tmp_path)
    with playwright.sync_playwright() as p:
        browser = launch(p)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto((tmp_path / "index.html").as_uri())
        # Three regions under a header; the page itself never scrolls.
        assert page.locator("h1").inner_text() == "My <Lecture>"
        assert page.locator("#slide-count").inner_text() == "3"
        assert page.locator("#source").inner_text() == "Watch"
        assert page.locator("#source").evaluate("e => e.previousElementSibling.tagName") == "H1"
        assert page.locator("[data-theme-choice]").evaluate_all("(b)=>b.every(x=>x.textContent.trim()===''&&x.getAttribute('aria-label'))")
        assert page.locator(".card").count() == 3
        assert page.evaluate("document.documentElement.scrollHeight <= window.innerHeight")
        left, main, right = (page.locator(s).bounding_box() for s in ("#left", "main", "#right"))
        stage = page.locator("#stage").bounding_box()
        assert left["x"] + left["width"] == pytest.approx(main["x"], abs=1)
        assert main["x"] + main["width"] == pytest.approx(right["x"], abs=1)
        assert main["x"] < stage["x"] and stage["x"] + stage["width"] < right["x"]
        # The slide fits inside the stage without cropping or distortion.
        page.wait_for_function("document.getElementById('large').naturalWidth===320")
        image = page.locator("#large").bounding_box()
        assert image["width"] <= stage["width"] + 1 and image["height"] <= stage["height"] + 1
        assert page.locator("#large").evaluate("e => getComputedStyle(e).objectFit") == "contain"
        assert "Slide 1 of 3" in title(page)
        # Thumbnail selection, transcript sync and the timestamped source link.
        page.locator(".card").nth(1).click()
        assert "Slide 2 of 3" in title(page)
        assert page.locator(".segment[aria-current=true] time").inner_text() == "00:00:10"
        assert page.locator("#source").get_attribute("href").endswith("&t=12s")
        assert page.locator(".card[aria-current=true] strong").inner_text() == "2"
        assert page.locator("#timeline span").evaluate_all("(s)=>s.map(x=>Number(x.style.flexGrow))") == [10, 30, 20]
        assert float(page.locator("#timeline").get_attribute("aria-valuenow")) == pytest.approx(100 / 6)
        # Arrow mapping, including while a transcript line has focus.
        page.locator(".segment[aria-current=true]").click()
        for key, expected in [("ArrowLeft", 1), ("ArrowUp", 1), ("ArrowDown", 2), ("ArrowRight", 3),
                              ("ArrowRight", 3), ("Home", 1), ("End", 3)]:
            page.keyboard.press(key)
            assert f"Slide {expected} of 3" in title(page)
        # Clicking the weighted timeline jumps to a slide.
        page.locator("#timeline span").nth(0).click()
        assert "Slide 1 of 3" in title(page)
        # Scrolling the transcript selects the slide without oscillating.
        page.evaluate("""() => {
            const reading=document.getElementById('reading'), line=[...document.querySelectorAll('.segment')].find(e=>Number(e.dataset.start)>=45);
            reading.scrollTop += line.getBoundingClientRect().top-reading.getBoundingClientRect().top-8;
        }""")
        page.wait_for_function("document.getElementById('slide-label').textContent.includes('Slide 3 of 3')")
        top = page.locator("#reading").evaluate("e => e.scrollTop")
        page.wait_for_timeout(150)
        assert abs(page.locator("#reading").evaluate("e => e.scrollTop") - top) < 1
        page.locator("#reading").evaluate("e => e.scrollTop=0")
        page.wait_for_function("document.querySelector('.card[aria-current=true] strong').textContent==='1'")
        assert not errors
        browser.close()


def test_panels_collapse_and_stage_expands(tmp_path):
    make_lecture(tmp_path)
    with playwright.sync_playwright() as p:
        browser = launch(p)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto((tmp_path / "index.html").as_uri())
        widths = [page.locator("#stage").bounding_box()["width"]]
        page.locator("#toggle-left").click()
        page.wait_for_function("document.getElementById('left').getBoundingClientRect().width<1")
        widths.append(page.locator("#stage").bounding_box()["width"])
        assert page.locator("#toggle-left").get_attribute("aria-expanded") == "false"
        assert page.locator("#left").evaluate("e => e.inert")
        page.keyboard.press("]")
        page.wait_for_function("document.getElementById('right').getBoundingClientRect().width<1")
        widths.append(page.locator("#stage").bounding_box()["width"])
        assert widths[0] < widths[1] < widths[2]
        page.keyboard.press("[")
        page.keyboard.press("]")
        page.wait_for_function("document.getElementById('right').getBoundingClientRect().width>=372"
                               " && document.getElementById('left').getBoundingClientRect().width>=244")
        assert page.locator("#stage").bounding_box()["width"] == pytest.approx(widths[0], abs=2)
        # Reopened transcript is positioned at the current slide.
        page.locator(".card").nth(2).click()
        page.keyboard.press("]")
        page.keyboard.press("]")
        page.locator(".segment[aria-current=true]").wait_for()
        assert page.locator(".segment[aria-current=true] time").inner_text() == "00:00:40"
        browser.close()


def test_theme_toggle_is_persistent_and_follows_system(tmp_path):
    make_lecture(tmp_path)
    with playwright.sync_playwright() as p:
        browser = launch(p)
        context = browser.new_context(color_scheme="dark", viewport={"width": 1200, "height": 800})
        page = context.new_page()
        page.goto((tmp_path / "index.html").as_uri())

        def background():
            return page.evaluate("getComputedStyle(document.body).backgroundColor")

        assert page.locator("[data-theme-choice=system]").get_attribute("aria-pressed") == "true"
        system_dark = background()
        page.locator("[data-theme-choice=light]").click()
        assert page.evaluate("document.documentElement.dataset.theme") == "light"
        light = background()
        assert light != system_dark
        page.reload()
        assert page.locator("[data-theme-choice=light]").get_attribute("aria-pressed") == "true"
        assert background() == light
        page.locator("[data-theme-choice=dark]").click()
        assert background() == system_dark
        page.locator("[data-theme-choice=system]").click()
        assert page.evaluate("document.documentElement.dataset.theme") is None
        assert background() == system_dark
        page.emulate_media(color_scheme="light")
        assert background() == light
        browser.close()


def test_mobile_uses_single_drawers(tmp_path):
    make_lecture(tmp_path)
    with playwright.sync_playwright() as p:
        browser = launch(p)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto((tmp_path / "index.html").as_uri())
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert page.locator("#toggle-left").get_attribute("aria-expanded") == "false"
        assert page.locator("#toggle-right").get_attribute("aria-expanded") == "false"
        assert page.locator("#stage").bounding_box()["width"] > 360
        page.locator("#toggle-left").click()
        page.locator(".card").nth(1).wait_for(state="visible")
        page.locator(".card").nth(1).click()
        assert "Slide 2 of 3" in title(page)
        page.locator("#toggle-right").click()
        assert page.locator("#toggle-left").get_attribute("aria-expanded") == "false"
        page.keyboard.press("Escape")
        assert page.locator("#toggle-right").get_attribute("aria-expanded") == "false"
        browser.close()


def test_export_downloads_self_contained_package(tmp_path):
    make_lecture(tmp_path)
    with playwright.sync_playwright() as p:
        browser = launch(p)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        page.goto((tmp_path / "index.html").as_uri())
        assert page.locator(".theme").evaluate("e => e.nextElementSibling.id") == "export-btn"
        with page.expect_download() as info:
            page.locator("#export-btn").click()
        # Chrome ignores the download name for file:// pages; over http it applies.
        assert page.locator("#export-btn").get_attribute("download") == "my-lecture.zip"
        assert info.value.suggested_filename.endswith(".zip")
        assert info.value.path().stat().st_size > 0
        browser.close()


def test_wheel_scrolls_slides_only_over_main_area(tmp_path):
    make_lecture(tmp_path)
    with playwright.sync_playwright() as p:
        browser = launch(p)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto((tmp_path / "index.html").as_uri())
        stage = page.locator("#stage").bounding_box()
        page.mouse.move(stage["x"] + stage["width"] / 2, stage["y"] + stage["height"] / 2)
        page.mouse.wheel(0, 120)
        assert "Slide 2 of 3" in title(page)
        page.wait_for_timeout(350)
        page.mouse.wheel(0, 120)
        assert "Slide 3 of 3" in title(page)
        page.wait_for_timeout(350)
        page.mouse.wheel(0, 120)  # past the end: stays put
        assert "Slide 3 of 3" in title(page)
        page.wait_for_timeout(350)
        page.mouse.wheel(0, -120)
        assert "Slide 2 of 3" in title(page)
        # A burst of events (trackpad inertia) is one step, not many.
        page.wait_for_timeout(350)
        for _ in range(6):
            page.mouse.wheel(0, 50)
        assert "Slide 3 of 3" in title(page)
        # Over the transcript the wheel scrolls the text and leaves the slide alone.
        page.wait_for_timeout(350)
        before = page.locator("#reading").evaluate("e => e.scrollTop")
        right = page.locator("#reading").bounding_box()
        page.mouse.move(right["x"] + 100, right["y"] + 200)
        page.mouse.wheel(0, -300)
        page.wait_for_timeout(150)
        assert page.locator("#reading").evaluate("e => e.scrollTop") < before
        browser.close()
