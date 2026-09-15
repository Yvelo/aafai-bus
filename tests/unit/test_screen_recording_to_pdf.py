# -*- coding: utf-8 -*-
"""Unit tests for the screen_recording_to_pdf action."""

import base64
import os
import sys

import cv2
import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.actions import screen_recording_to_pdf as action

BACKGROUND = (45, 45, 45)
HEADER = (90, 30, 10)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeResponse:
    """Minimal streamed `requests` response."""

    def __init__(self, content=b'', headers=None, url='https://example.com/video.wmv', text=''):
        self._content = content
        self.headers = headers or {}
        self.url = url
        self.text = text
        self.closed = False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=1):
        for start in range(0, len(self._content), chunk_size):
            yield self._content[start:start + chunk_size]

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FakeSession:
    """Returns the canned responses in order and records the requests."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def _pdf_page_count(pdf_bytes):
    return pdf_bytes.count(b'/Type /Page') - pdf_bytes.count(b'/Type /Pages')


def _texture(rng, height, width, channels=None):
    """Smooth random texture: registers unambiguously and has no uniform rows."""
    shape = (height, width) if channels is None else (height, width, channels)
    noise = rng.random(shape).astype(np.float32) * 255
    return cv2.GaussianBlur(noise, (0, 0), 2)


def _page(rng, height=120, width=200):
    page = np.clip(_texture(rng, height, width, 3) * 0.6 + 100, 0, 255).astype(np.uint8)
    page[:10] = HEADER   # template header band: a decoy separator repeating with the page height
    return page


def _document(pages, gap=8):
    gap_rows = np.full((gap, pages[0].shape[1], 3), BACKGROUND, dtype=np.uint8)
    parts = [gap_rows]
    for page in pages:
        parts += [page, gap_rows]
    return np.vstack(parts)


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------

def test_execute_fails_fast_without_url(tmp_path):
    results = {}
    action.execute('job-1', {}, str(tmp_path), lambda job_id, result: results.update({job_id: result}))

    assert results['job-1']['status'] == 'failed'
    assert 'Missing required parameter: url' in results['job-1']['error']


def test_execute_reports_download_errors_and_cleans_up(tmp_path, monkeypatch):
    def failing_download(url, destination_dir):
        raise ValueError("The url returned a web page instead of a video file.")

    monkeypatch.setattr(action, '_download_video', failing_download)
    results = {}
    action.execute('job-2', {'url': 'https://example.com/page'}, str(tmp_path),
                   lambda job_id, result: results.update({job_id: result}))

    assert results['job-2']['status'] == 'failed'
    assert 'web page' in results['job-2']['error']
    assert os.listdir(tmp_path) == []


def test_execute_rejects_invalid_page_height(tmp_path):
    results = {}
    action.execute('job-3', {'url': 'https://example.com/v.wmv', 'page_height': '-4'}, str(tmp_path),
                   lambda job_id, result: results.update({job_id: result}))

    assert results['job-3']['status'] == 'failed'
    assert 'page_height' in results['job-3']['error']


def test_execute_builds_a_pdf_from_the_reconstructed_pages(tmp_path, monkeypatch):
    received = {}

    def fake_download(url, destination_dir):
        path = os.path.join(destination_dir, 'Board meeting.wmv')
        with open(path, 'wb') as video:
            video.write(b'video')
        return path

    def fake_reconstruct(video_path, page_height=None):
        received['video_path'] = video_path
        received['page_height'] = page_height
        return [Image.new('RGB', (160, 90), color) for color in ('red', 'green', 'blue')]

    monkeypatch.setattr(action, '_download_video', fake_download)
    monkeypatch.setattr(action, 'reconstruct_pages', fake_reconstruct)
    results = {}
    action.execute('job-4', {'url': 'https://example.com/v.wmv', 'page_height': '870'}, str(tmp_path),
                   lambda job_id, result: results.update({job_id: result}))

    result = results['job-4']
    assert result['status'] == 'Completed', result.get('error')
    assert result['result']['page_count'] == 3
    assert received['page_height'] == 870
    assert received['video_path'].endswith('Board meeting.wmv')

    downloaded = result['result']['downloaded_files'][0]
    assert downloaded['filename'] == 'Board meeting.pdf'
    assert downloaded['path'] == os.path.join(str(tmp_path), 'Board meeting.pdf')
    pdf_bytes = base64.b64decode(downloaded['content_base64'])
    assert len(pdf_bytes) == downloaded['size_bytes'] == os.path.getsize(downloaded['path'])
    assert _pdf_page_count(pdf_bytes) == 3
    # The downloaded recording is removed, only the PDF is kept.
    assert os.listdir(tmp_path) == ['Board meeting.pdf']


def test_execute_fails_when_nothing_could_be_reconstructed(tmp_path, monkeypatch):
    monkeypatch.setattr(action, '_download_video', lambda url, directory: os.path.join(directory, 'v.wmv'))
    monkeypatch.setattr(action, 'reconstruct_pages', lambda video_path, page_height=None: [])
    results = {}
    action.execute('job-5', {'url': 'https://example.com/v.wmv', 'document_name': 'deck'}, str(tmp_path),
                   lambda job_id, result: results.update({job_id: result}))

    assert results['job-5']['status'] == 'failed'
    assert 'No stable screen content' in results['job-5']['error']


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('url, expected', [
    ('https://drive.google.com/file/d/ABC123/view?usp=sharing', 'https://drive.google.com/uc?export=download&id=ABC123'),
    ('https://drive.google.com/open?id=XYZ', 'https://drive.google.com/uc?export=download&id=XYZ'),
    ('https://www.dropbox.com/s/k/rec.wmv?dl=0', 'https://www.dropbox.com/s/k/rec.wmv?dl=1'),
    ('https://www.dropbox.com/s/k/rec.wmv', 'https://www.dropbox.com/s/k/rec.wmv?dl=1'),
    ('https://files.example.com/rec.wmv?token=1', 'https://files.example.com/rec.wmv?token=1'),
])
def test_share_links_are_turned_into_direct_download_links(url, expected):
    assert action._to_direct_download_url(url) == expected


@pytest.mark.parametrize('headers, url, expected', [
    ({'Content-Disposition': 'attachment; filename="Demo day.wmv"'}, 'https://x.com/download', 'Demo day.wmv'),
    ({'Content-Disposition': "attachment; filename*=UTF-8''Pr%C3%A9sentation.wmv"}, 'https://x.com/d', 'Présentation.wmv'),
    ({}, 'https://x.com/videos/Screen%20Recording.wmv?x=1', 'Screen Recording.wmv'),
    ({}, 'https://x.com/uc?export=download', action.DEFAULT_VIDEO_FILENAME),
    ({'Content-Disposition': 'attachment; filename="../../etc/rec?.wmv"'}, 'https://x.com/d', '_.._etc_rec_.wmv'),
])
def test_filename_is_read_from_the_response(headers, url, expected):
    assert action._filename_from_response(FakeResponse(headers=headers), url) == expected


def test_download_confirmation_form_is_extracted():
    html = """
    <html><body>
      <form id="download-form" action="https://drive.usercontent.google.com/download" method="get">
        <input type="hidden" name="id" value="ABC123">
        <input type="hidden" name="export" value="download">
        <input type="hidden" name="confirm" value="t">
        <input type="submit" value="Download anyway">
      </form>
    </body></html>
    """
    url, params = action._extract_download_confirmation(html, 'https://drive.google.com/uc?id=ABC123')

    assert url == 'https://drive.usercontent.google.com/download'
    assert params == {'id': 'ABC123', 'export': 'download', 'confirm': 't'}
    assert action._extract_download_confirmation('<html><p>Sign in</p></html>', 'https://x.com') is None


def test_download_video_streams_the_file(tmp_path, monkeypatch):
    content = os.urandom(3 * action.DOWNLOAD_CHUNK_SIZE + 17)
    session = FakeSession([FakeResponse(content, {'Content-Type': 'video/x-ms-wmv'})])
    monkeypatch.setattr(action.requests, 'Session', lambda: session)

    path = action._download_video('https://example.com/files/recording.wmv', str(tmp_path))

    assert path == os.path.join(str(tmp_path), 'recording.wmv')
    with open(path, 'rb') as video:
        assert video.read() == content
    assert session.calls[0][1]['stream'] is True


def test_download_video_confirms_the_download_page(tmp_path, monkeypatch):
    warning = FakeResponse(headers={'Content-Type': 'text/html; charset=utf-8'},
                           url='https://drive.google.com/uc?export=download&id=ABC',
                           text='<form action="/download"><input name="id" value="ABC"><input name="confirm" value="t"></form>')
    video = FakeResponse(b'wmv-bytes', {'Content-Type': 'application/octet-stream',
                                        'Content-Disposition': 'attachment; filename="pitch.wmv"'})
    session = FakeSession([warning, video])
    monkeypatch.setattr(action.requests, 'Session', lambda: session)

    path = action._download_video('https://drive.google.com/file/d/ABC/view', str(tmp_path))

    assert os.path.basename(path) == 'pitch.wmv'
    assert warning.closed
    assert session.calls[0][0] == 'https://drive.google.com/uc?export=download&id=ABC'
    assert session.calls[1][0] == 'https://drive.google.com/download'
    assert session.calls[1][1]['params'] == {'id': 'ABC', 'confirm': 't'}


def test_download_video_rejects_web_pages(tmp_path, monkeypatch):
    session = FakeSession([FakeResponse(headers={'Content-Type': 'text/html'}, text='<p>Sign in</p>')])
    monkeypatch.setattr(action.requests, 'Session', lambda: session)

    with pytest.raises(ValueError, match='web page'):
        action._download_video('https://example.com/share/123', str(tmp_path))


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'C:/Users/me/video.wmv', 'ftp://example.com/v.wmv'])
def test_download_video_only_accepts_http_links(tmp_path, url):
    with pytest.raises(ValueError, match='http'):
        action._download_video(url, str(tmp_path))


# ---------------------------------------------------------------------------
# Static borders
# ---------------------------------------------------------------------------

def _accumulate(frames):
    total = np.zeros(frames[0].shape)
    squares = np.zeros(frames[0].shape)
    for frame in frames:
        total += frame
        squares += frame.astype(np.float64) ** 2
    return total, squares, len(frames)


def test_static_toolbar_and_borders_are_cropped():
    rng = np.random.default_rng(1)
    frames = []
    for _ in range(20):
        frame = rng.integers(0, 255, (60, 80)).astype(np.float64)
        frame[:6] = 30          # toolbar
        frame[:, :3] = 45       # left border
        frame[:, -1] = 45       # right border
        frames.append(frame)

    assert action._static_borders_from_stats(*_accumulate(frames)) == (6, 60, 3, 79)


def test_nothing_is_cropped_when_nothing_moves():
    frame = np.random.default_rng(2).integers(0, 255, (60, 80)).astype(np.float64)
    assert action._static_borders_from_stats(*_accumulate([frame] * 10)) == (0, 60, 0, 80)


def test_border_color_is_the_mean_colour_outside_of_the_crop():
    mean_frame = np.zeros((10, 10, 3))
    mean_frame[:2] = (40, 50, 60)
    assert action._border_color(mean_frame, (2, 10, 0, 10)) == (40.0, 50.0, 60.0)
    assert action._border_color(mean_frame, (0, 10, 0, 10)) is None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_mosaic_grows_in_both_directions_and_keeps_the_first_written_rows():
    mosaic = action._Mosaic(4)
    mosaic.write(0, np.full((10, 4), 1, np.float32))
    mosaic.write(5, np.full((10, 4), 2, np.float32))
    mosaic.write(-3000, np.full((10, 4), 3, np.float32))

    assert (mosaic.top, mosaic.bottom) == (-3000, 15)
    data, written = mosaic.view()
    assert data.shape == (3015, 4)
    assert (data[3000:3010] == 1).all() and (data[3010:3015] == 2).all() and (data[:10] == 3).all()
    assert written[:10].all() and not written[10:3000].any() and written[3000:].all()


@pytest.mark.parametrize('shift', [37, -52, 0])
def test_best_offset_recovers_the_scroll_shift(shift):
    document = _texture(np.random.default_rng(3), 800, action.SIGNATURE_WIDTH)
    mosaic = action._Mosaic(action.SIGNATURE_WIDTH)
    mosaic.write(300, document[300:500])
    reference, written = mosaic.view()

    offset, error = action._best_offset(document[300 + shift:500 + shift], reference, written, mosaic.top,
                                        150, 450, 50, 300)

    assert offset == 300 + shift
    assert error < 0.01


def test_track_frame_follows_scrolling():
    document = _texture(np.random.default_rng(4), 800, action.SIGNATURE_WIDTH)
    mosaic = action._Mosaic(action.SIGNATURE_WIDTH)
    mosaic.write(0, document[0:200])

    assert action._track_frame(document[23:223], document[0:200], mosaic, 0, 150, 50) == 23


def test_track_frame_keeps_the_position_of_the_same_content():
    rng = np.random.default_rng(5)
    slide = _texture(rng, 200, action.SIGNATURE_WIDTH)
    noisy = slide + rng.uniform(-0.8, 0.8, slide.shape).astype(np.float32)
    mosaic = action._Mosaic(action.SIGNATURE_WIDTH)
    mosaic.write(0, slide)

    assert action._track_frame(noisy, slide, mosaic, 0, 150, 50) == 0


def test_track_frame_detects_a_similar_looking_slide():
    rng = np.random.default_rng(6)
    slide = _texture(rng, 200, action.SIGNATURE_WIDTH)
    next_slide = slide.copy()
    next_slide[10:30, 10:60] += 80          # same template, another title
    mosaic = action._Mosaic(action.SIGNATURE_WIDTH)
    mosaic.write(0, slide)

    assert action._track_frame(next_slide, slide, mosaic, 0, 150, 50) is None


def test_settled_content_seen_before_is_not_duplicated():
    rng = np.random.default_rng(7)
    first, second = _texture(rng, 200, action.SIGNATURE_WIDTH), _texture(rng, 200, action.SIGNATURE_WIDTH)
    mosaic = action._Mosaic(action.SIGNATURE_WIDTH)
    breaks = []

    assert action._place_settled_frame(first, mosaic, 180, breaks) == 0
    mosaic.write(0, first)
    assert action._place_settled_frame(second, mosaic, 180, breaks) == 200
    mosaic.write(200, second)
    assert action._place_settled_frame(first + 0.5, mosaic, 180, breaks) == 0
    assert breaks == [0, 200]


def test_still_runs():
    offsets = [None, 0, 0, 0, 5, 5, 5, None]
    still = [False, True, True, True, False, True, False, True]

    assert action._still_runs(offsets, still) == [
        (1, 0), (3, 0), (3, 1), (3, 2), (2, 0), (2, 1), (1, 0), (1, 0)
    ]


# ---------------------------------------------------------------------------
# Page splitting
# ---------------------------------------------------------------------------

def test_pages_are_cut_on_the_viewer_gaps_rather_than_on_repeated_template_bands():
    rng = np.random.default_rng(8)
    pages = [_page(rng) for _ in range(6)]

    result = action._split_segment(_document(pages), frame_height=100, background=BACKGROUND)

    assert len(result) == 6
    for expected, actual in zip(pages, result):
        assert np.array_equal(expected, actual)


def test_a_single_gap_is_cut_using_the_background_colour():
    rng = np.random.default_rng(9)
    pages = [_page(rng), _page(rng)]
    segment = _document(pages)[8:-8]    # no gap above the first and below the last page

    result = action._split_segment(segment, frame_height=100, background=BACKGROUND)

    assert len(result) == 2
    assert all(np.array_equal(e, a) for e, a in zip(pages, result))


def test_a_forced_page_height_splits_documents_without_gaps():
    rng = np.random.default_rng(10)
    pages = [_page(rng) for _ in range(3)]

    result = action._split_segment(np.vstack(pages), frame_height=100, page_height=120)

    assert len(result) == 3
    assert all(np.array_equal(e, a) for e, a in zip(pages, result))


def test_a_segment_of_the_screen_height_is_a_single_page():
    page = _page(np.random.default_rng(11))
    result = action._split_segment(page, frame_height=120, background=BACKGROUND)
    assert len(result) == 1 and result[0] is page


def test_gap_runs_split_by_compression_shading_are_glued():
    segment = np.full((40, 50, 3), 200, dtype=np.uint8)
    segment[:, ::2] = 0                                    # textured, non uniform rows
    segment[10:12] = (31, 39, 36)
    segment[12:20] = (46, 43, 44)
    segment[21:23] = (43, 45, 42)

    assert action._separator_runs(segment, max_length=20) == [(10, 23, (46, 43, 44))]


@pytest.mark.parametrize('centers, expected', [
    ([10, 110, 210, 310, 410], 100),
    ([10, 110, 310, 410, 510], 100),        # a gap was not detected
    ([10, 111, 211, 312, 412, 513], 100),   # rounding of the page height
])
def test_estimate_period(centers, expected):
    period = action._estimate_period(np.array(centers, dtype=float), 25, 600)
    assert abs(period - expected) <= action.PERIOD_TOLERANCE


def test_cuts_are_extrapolated_where_a_gap_is_missing():
    assert action._cuts_from_anchors([100.0, 200.0, 400.0], 100, 520) == [100, 200, 300, 400, 500]


def test_trim_separator_removes_the_gap_colour_around_the_page():
    page = np.full((30, 40, 3), BACKGROUND, dtype=np.uint8)
    page[5:25, 3:37] = (250, 250, 250)

    trimmed = action._trim_separator(page, BACKGROUND)

    assert trimmed.shape == (20, 34, 3)
    assert action._trim_separator(np.full((5, 5, 3), BACKGROUND, np.uint8), BACKGROUND) is None
    assert action._trim_separator(page, None) is page


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def test_compile_pdf_writes_one_page_per_image(tmp_path):
    output = tmp_path / 'deck.pdf'
    action._compile_pdf([Image.new('RGB', (100, 60), 'white'), Image.new('RGB', (100, 140), 'black')], str(output))

    assert _pdf_page_count(output.read_bytes()) == 2
