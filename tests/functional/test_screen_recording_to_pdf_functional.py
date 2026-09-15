# -*- coding: utf-8 -*-
"""
Functional tests for the screen_recording_to_pdf action.

Synthetic screen recordings (.wmv) of a known slide deck are generated, served over a local HTTP
server and reconstructed; the reconstructed pages are then compared with the original slides.

The live test on a real screen recording is marked as 'slow':
    pytest -m slow tests/functional/test_screen_recording_to_pdf_functional.py
It uses the recording given by the RECORDING_PATH environment variable.
"""

import base64
import copy
import functools
import http.server
import json
import os
import shutil
import threading
import time
import uuid
from urllib.parse import quote

import cv2
import numpy as np
import pytest

from src.actions import screen_recording_to_pdf
from src.server import process_inbound_queue

FPS = 20
PAGE_WIDTH = 620
PAGE_HEIGHT = 349
GAP = 12
MARGIN = 10
TOOLBAR_HEIGHT = 20
VIEWPORT_HEIGHT = 360
BACKGROUND = (45, 45, 45)
TEMPLATE_BLUE = (90, 30, 10)
FONT = cv2.FONT_HERSHEY_SIMPLEX

# Mean abs difference (grey levels) between a reconstructed page and its original slide.
MAX_PAGE_DIFFERENCE = 12.0


# ---------------------------------------------------------------------------
# Synthetic recordings
# ---------------------------------------------------------------------------

def _make_slide(number):
    """A slide of a deck sharing the same template: only the title and the body differ."""
    rng = np.random.default_rng(number)
    slide = np.full((PAGE_HEIGHT, PAGE_WIDTH, 3), 255, dtype=np.uint8)
    cv2.rectangle(slide, (0, 0), (PAGE_WIDTH - 1, 50), TEMPLATE_BLUE, -1)
    cv2.putText(slide, f"Slide {number}: market overview", (15, 35), FONT, 0.8, (255, 255, 255), 2)
    for line in range(5):
        cv2.putText(slide, f"Key point {number}.{line} growth drivers", (20, 90 + 45 * line), FONT, 0.5, (40, 40, 40), 1)
    for _ in range(4):
        x, y = int(rng.integers(330, 520)), int(rng.integers(70, 250))
        color = tuple(int(c) for c in rng.integers(0, 220, 3))
        cv2.rectangle(slide, (x, y), (x + int(rng.integers(30, 90)), y + int(rng.integers(20, 70))), color, -1)
    cv2.rectangle(slide, (0, PAGE_HEIGHT - 24), (PAGE_WIDTH - 1, PAGE_HEIGHT - 1), TEMPLATE_BLUE, -1)
    cv2.putText(slide, str(number), (PAGE_WIDTH - 40, PAGE_HEIGHT - 7), FONT, 0.5, (255, 255, 255), 1)
    return slide


def _draw_cursor(frame, x, y):
    points = np.array([[x, y], [x, y + 16], [x + 4, y + 12], [x + 11, y + 12]], dtype=np.int32)
    cv2.fillPoly(frame, [points], (255, 255, 255))
    cv2.polylines(frame, [points], True, (0, 0, 0), 1)


def _open_writer(path, width, height):
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'WMV2'), FPS, (width, height))
    if not writer.isOpened():
        pytest.skip("OpenCV cannot write WMV videos on this platform.")
    return writer


def _write_scrolling_recording(path, slides):
    """Records a vertical document viewer: static toolbar, grey margins and gaps, eased scrolling with pauses."""
    gap = np.full((GAP, PAGE_WIDTH + 2 * MARGIN, 3), BACKGROUND, dtype=np.uint8)
    parts = [gap]
    for slide in slides:
        parts += [cv2.copyMakeBorder(slide, 0, 0, MARGIN, MARGIN, cv2.BORDER_CONSTANT, value=BACKGROUND), gap]
    document = np.vstack(parts)
    max_scroll = document.shape[0] - VIEWPORT_HEIGHT
    period = PAGE_HEIGHT + GAP

    # Scroll page by page, go back up once, then continue to the end of the document.
    targets = [period, 2 * period, int(1.5 * period), 3 * period] + [k * period for k in range(4, len(slides))]
    positions = [0] * FPS
    for target in targets:
        start, target = positions[-1], min(target, max_scroll)
        steps = int(FPS * 0.6)
        positions += [int(round(start + (target - start) * (1 - np.cos(np.pi * k / steps)) / 2)) for k in range(1, steps + 1)]
        positions += [target] * int(FPS * 0.7)

    width = PAGE_WIDTH + 2 * MARGIN
    writer = _open_writer(path, width, TOOLBAR_HEIGHT + VIEWPORT_HEIGHT)
    try:
        for index, position in enumerate(positions):
            frame = np.empty((TOOLBAR_HEIGHT + VIEWPORT_HEIGHT, width, 3), dtype=np.uint8)
            frame[:TOOLBAR_HEIGHT] = (30, 30, 30)
            cv2.putText(frame, "document viewer  -  100%", (10, 14), FONT, 0.4, (200, 200, 200), 1)
            frame[TOOLBAR_HEIGHT:] = document[position:position + VIEWPORT_HEIGHT]
            _draw_cursor(frame, 200 + int(150 * np.sin(index / 15.0)), 150 + int(60 * np.cos(index / 23.0)))
            writer.write(frame)
    finally:
        writer.release()


def _write_slideshow_recording(path, slides):
    """Records a slide show: hard cuts, a cross-fade and going back to a previous slide."""
    size = (PAGE_WIDTH + 20, VIEWPORT_HEIGHT)
    screens = [cv2.resize(slide, size, interpolation=cv2.INTER_AREA) for slide in slides]

    frames = []
    def show(screen, seconds):
        frames.extend([screen] * int(FPS * seconds))

    show(screens[0], 1.0)
    show(screens[1], 1.0)                                        # hard cut
    for k in range(1, int(FPS * 0.5)):                           # cross-fade
        alpha = k / (FPS * 0.5)
        frames.append(cv2.addWeighted(screens[1], 1 - alpha, screens[2], alpha, 0))
    show(screens[2], 1.0)
    show(screens[1], 1.0)                                        # back to a previous slide
    show(screens[2], 0.6)
    show(screens[3], 1.5)

    writer = _open_writer(path, size[0], size[1])
    try:
        for index, screen in enumerate(frames):
            frame = screen.copy()
            _draw_cursor(frame, 300 + int(100 * np.sin(index / 10.0)), 200)
            writer.write(frame)
    finally:
        writer.release()
    return [screens[0], screens[1], screens[2], screens[3]]


def _page_difference(page_image, expected_bgr):
    page = cv2.cvtColor(np.array(page_image), cv2.COLOR_RGB2BGR)
    page = cv2.resize(page, (expected_bgr.shape[1], expected_bgr.shape[0]), interpolation=cv2.INTER_AREA)
    grey = lambda image: cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return float(np.abs(grey(page) - grey(expected_bgr)).mean())


def _assert_pages_match(pages, expected_slides):
    assert len(pages) == len(expected_slides), f"Expected {len(expected_slides)} pages, got {len(pages)}."
    for number, (page, expected) in enumerate(zip(pages, expected_slides), start=1):
        differences = [_page_difference(page, slide) for slide in expected_slides]
        print(f"Page {number}: size {page.size}, difference with its slide {differences[number - 1]:.2f}")
        assert int(np.argmin(differences)) == number - 1, f"Page {number} does not show slide {number}."
        assert differences[number - 1] < MAX_PAGE_DIFFERENCE, f"Page {number} is not faithfully reconstructed."


def _pdf_page_count(pdf_bytes):
    return pdf_bytes.count(b'/Type /Page') - pdf_bytes.count(b'/Type /Pages')


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def recordings_server(tmp_path):
    """Serves the files of a temporary directory over HTTP. Yields `(directory, base url)`."""
    directory = tmp_path / 'served'
    directory.mkdir()
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(_QuietHandler, directory=str(directory)))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield directory, f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_scrolling_recording_is_reconstructed_from_its_url(recordings_server, tmp_path):
    directory, base_url = recordings_server
    slides = [_make_slide(number) for number in range(1, 7)]
    _write_scrolling_recording(str(directory / 'Scrolling deck.wmv'), slides)
    download_dir = tmp_path / 'downloads'
    download_dir.mkdir()

    results = {}
    screen_recording_to_pdf.execute('job-scroll', {'url': f"{base_url}/{quote('Scrolling deck.wmv')}"},
                                    str(download_dir), lambda job_id, result: results.update({job_id: result}))

    result = results['job-scroll']
    assert result['status'] == 'Completed', result.get('error')
    assert result['result']['page_count'] == len(slides)
    downloaded = result['result']['downloaded_files'][0]
    assert downloaded['filename'] == 'Scrolling deck.pdf'
    pdf_bytes = base64.b64decode(downloaded['content_base64'])
    assert len(pdf_bytes) == downloaded['size_bytes']
    assert _pdf_page_count(pdf_bytes) == len(slides)
    assert os.listdir(download_dir) == ['Scrolling deck.pdf']

    # The pages themselves must be the original slides, in order.
    _assert_pages_match(screen_recording_to_pdf.reconstruct_pages(str(directory / 'Scrolling deck.wmv')), slides)


def test_slideshow_recording_keeps_each_slide_once(recordings_server, tmp_path):
    directory, base_url = recordings_server
    slides = [_make_slide(number) for number in range(1, 5)]
    expected = _write_slideshow_recording(str(directory / 'slideshow.wmv'), slides)

    results = {}
    screen_recording_to_pdf.execute('job-slides', {'url': f"{base_url}/slideshow.wmv", 'document_name': 'Slides'},
                                    str(tmp_path), lambda job_id, result: results.update({job_id: result}))

    result = results['job-slides']
    assert result['status'] == 'Completed', result.get('error')
    assert result['result']['page_count'] == len(expected)
    assert result['result']['downloaded_files'][0]['filename'] == 'Slides.pdf'

    _assert_pages_match(screen_recording_to_pdf.reconstruct_pages(str(directory / 'slideshow.wmv')), expected)


def test_missing_recording_url_fails(recordings_server, tmp_path):
    _, base_url = recordings_server
    results = {}
    screen_recording_to_pdf.execute('job-404', {'url': f"{base_url}/missing.wmv"}, str(tmp_path),
                                    lambda job_id, result: results.update({job_id: result}))

    assert results['job-404']['status'] == 'failed'
    assert '404' in results['job-404']['error']


def test_action_through_the_server_queue(client, app, recordings_server):
    directory, base_url = recordings_server
    slides = [_make_slide(number) for number in range(1, 4)]
    _write_scrolling_recording(str(directory / 'queued.wmv'), slides)
    document_name = f"queued_{uuid.uuid4().hex}"

    response = client.post('/inbound', json={
        'action': 'screen_recording_to_pdf',
        'params': {'url': f"{base_url}/queued.wmv", 'document_name': document_name}
    })
    assert response.status_code == 200
    job_id = response.get_json()['job_id']

    process_inbound_queue(app, threading.Event())

    data = client.get(f'/outbound?job_id={job_id}').get_json()
    downloaded = data.get('result', {}).get('downloaded_files', [{}])[0]
    try:
        assert data['status'] == 'Completed', data.get('error')
        assert data['result']['page_count'] == len(slides)
        assert downloaded['filename'] == f"{document_name}.pdf"
    finally:
        if downloaded.get('path') and os.path.exists(downloaded['path']):
            os.remove(downloaded['path'])


@pytest.mark.slow
def test_live_screen_recording(tmp_path):
    """
    Reconstructs a real screen recording served over HTTP.
    RECORDING_PATH: the .wmv file; EXPECTED_MIN_PAGES: the number of pages browsed through.
    """
    recording_path = os.environ.get('RECORDING_PATH', '')
    if not os.path.isfile(recording_path):
        pytest.skip("Set RECORDING_PATH to a screen recording to run this test.")
    expected_min_pages = int(os.environ.get('EXPECTED_MIN_PAGES', '1'))
    kept_output_dir = os.environ.get('KEPT_OUTPUT_DIR', 'C:/temp/screen_recording_test_output')

    directory = os.path.dirname(os.path.abspath(recording_path))
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(_QuietHandler, directory=directory))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/{quote(os.path.basename(recording_path))}"
        results = {}
        started = time.time()
        screen_recording_to_pdf.execute(str(uuid.uuid4()), {'url': url}, str(tmp_path),
                                        lambda job_id, result: results.update({'result': result}))
        print(f"Reconstruction took {time.time() - started:.1f}s")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()

    result = results['result']
    printable = copy.deepcopy(result)
    for file_info in printable.get('result', {}).get('downloaded_files', []):
        file_info.pop('content_base64', None)
    print(json.dumps(printable, indent=2))

    assert result['status'] == 'Completed', result.get('error')
    downloaded = result['result']['downloaded_files'][0]
    assert result['result']['page_count'] >= expected_min_pages
    assert _pdf_page_count(base64.b64decode(downloaded['content_base64'])) == result['result']['page_count']

    os.makedirs(kept_output_dir, exist_ok=True)
    kept_path = os.path.join(kept_output_dir, downloaded['filename'])
    shutil.copy2(downloaded['path'], kept_path)
    print(f"Kept a copy of the reconstructed document at: {kept_path}")
