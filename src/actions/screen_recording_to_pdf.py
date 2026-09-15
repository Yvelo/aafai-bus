# -*- coding: utf-8 -*-
"""
Action: screen_recording_to_pdf

Reconstructs a PDF document from the screen recording (e.g. a `.wmv` file) of a presentation
or a document that has been browsed through on screen.

Two browsing styles are supported, and they may be mixed in the same recording:

- Scrolling viewers (PDF readers, DocSend / Papermark vertical viewers, ...): consecutive
  frames are vertically registered against each other and stitched into one tall canvas,
  which is then split into pages on the gaps the viewer draws between pages.
- Slide shows: every time the screen content is replaced and settles, the new content is
  appended as a new page. Slides that are displayed again later are not duplicated.

The video is decoded with OpenCV (which bundles FFmpeg), so no external binary is required.
"""

import os
import re
import base64
import shutil
import logging
from urllib.parse import urlparse, parse_qs, unquote

import cv2
import numpy as np
import requests
from bs4 import BeautifulSoup
from PIL import Image

# --- Download ---
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 60
DEFAULT_VIDEO_FILENAME = 'screen_recording.wmv'

# --- Static border (window chrome) detection ---
BORDER_SAMPLE_FRAMES = 300
STATIC_ACTIVITY_THRESHOLD = 2.0   # mean temporal std (grey levels) of a row/column that never changes
STATIC_RELATIVE_ACTIVITY = 0.1    # ...or that changes 10 times less than the content does
ACTIVE_ACTIVITY_THRESHOLD = 10.0  # the recording must contain at least this much motion to crop anything
MAX_BORDER_RATIO = 0.15

# --- Frame registration ---
SIGNATURE_WIDTH = 96              # frames are compared on a horizontally downscaled grey image
COARSE_ROW_STEP = 4
COARSE_COLUMN_STEP = 4
DUPLICATE_THRESHOLD = 1.0         # mean abs grey difference under which two frames show the same content
MATCH_THRESHOLD = 8.0             # max mean abs grey difference of a valid scroll registration
SCROLL_GAIN_RATIO = 0.5           # a scroll must fit at least twice as well as staying in place
SAME_CONTENT_THRESHOLD = 4.0      # max mean abs grey difference of the same content displayed again
CHANGED_CELL_LEVEL = 25           # grey difference of a changed signature cell...
CHANGED_CELL_RATIO = 0.005        # ...and max ratio of changed cells of the same content displayed again
DISTANCE_PENALTY = 0.002          # favours the smallest shift among equally good registrations
MAX_SHIFT_RATIO = 0.75
MIN_OVERLAP_RATIO = 0.25
REVISIT_OVERLAP_RATIO = 0.9
SETTLE_SECONDS = 0.25

# --- Canvas composition ---
STILL_RUN_SECONDS = 1.0
STILLNESS_WEIGHT = 4.0

# --- Page splitting ---
SINGLE_PAGE_RATIO = 1.15
SEPARATOR_MAX_RATIO = 0.1
SEPARATOR_PERCENTILE = 2
SEPARATOR_UNIFORMITY = 12
SEPARATOR_COLOR_DISTANCE = 24     # runs closer than this (max channel difference) share the same colour
MIN_SEPARATOR_LENGTH = 3
MIN_PERIOD_RATIO = 0.25
PERIOD_TOLERANCE = 3
PERIOD_DRIFT_RATIO = 0.01
SUBPERIOD_RATIO = 0.7
MIN_PAGE_RATIO = 0.05
ROW_CHUNK = 256

PDF_RESOLUTION = 96.0


def execute(job_id, params, download_dir, write_result_to_outbound):
    """
    Main entry point for the screen_recording_to_pdf action.
    """
    url = params.get('url')
    result = {}

    if not url:
        result = {"job_id": job_id, "status": "failed", "error": "Missing required parameter: url."}
        write_result_to_outbound(job_id, result)
        return

    work_dir = os.path.join(download_dir, f"screen_recording_{job_id}")
    try:
        page_height = _optional_int(params.get('page_height'))
        os.makedirs(work_dir, exist_ok=True)
        video_path = _download_video(url, work_dir)
        document_name = _safe_filename(
            params.get('document_name') or os.path.splitext(os.path.basename(video_path))[0]
        )

        pages = reconstruct_pages(video_path, page_height=page_height)

        if pages:
            output_pdf_path = os.path.join(download_dir, f"{document_name}.pdf")
            _compile_pdf(pages, output_pdf_path)
            with open(output_pdf_path, "rb") as pdf_file:
                encoded_string = base64.b64encode(pdf_file.read()).decode('utf-8')
            result = {
                "job_id": job_id,
                "status": "Completed",
                "result": {
                    "page_count": len(pages),
                    "downloaded_files": [
                        {
                            "filename": os.path.basename(output_pdf_path),
                            "path": output_pdf_path,
                            "size_bytes": os.path.getsize(output_pdf_path),
                            "text": "PDF content is image-based and cannot be extracted as text.",
                            "content_base64": encoded_string
                        }
                    ]
                }
            }
        else:
            result = {"job_id": job_id, "status": "failed",
                      "error": "No stable screen content could be found in the recording."}

    except Exception as e:
        logging.error(f"An error occurred while reconstructing the screen recording: {e}", exc_info=True)
        result = {"job_id": job_id, "status": "failed", "error": str(e)}

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        if result:
            write_result_to_outbound(job_id, result)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _download_video(url, destination_dir):
    """Downloads the recording behind `url` into `destination_dir` and returns the local file path."""
    if urlparse(url).scheme not in ('http', 'https'):
        raise ValueError("The url must be an http(s) link to the screen recording.")

    download_url = _to_direct_download_url(url)
    logging.info(f"Downloading screen recording from: {download_url}")
    session = requests.Session()
    response = session.get(download_url, stream=True, timeout=DOWNLOAD_TIMEOUT_SECONDS)
    response.raise_for_status()

    if _is_html_response(response):
        confirmation = _extract_download_confirmation(response.text, response.url)
        response.close()
        if not confirmation:
            raise ValueError("The url returned a web page instead of a video file. "
                             "Make sure the link is a public, direct download link.")
        confirm_url, confirm_params = confirmation
        logging.info("Download confirmation page detected, confirming the download.")
        response = session.get(confirm_url, params=confirm_params, stream=True, timeout=DOWNLOAD_TIMEOUT_SECONDS)
        response.raise_for_status()
        if _is_html_response(response):
            response.close()
            raise ValueError("The url returned a web page instead of a video file. "
                             "Make sure the link is a public, direct download link.")

    video_path = os.path.join(destination_dir, _filename_from_response(response, download_url))
    with response, open(video_path, 'wb') as video_file:
        for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
            if chunk:
                video_file.write(chunk)

    size = os.path.getsize(video_path)
    if not size:
        raise ValueError("The downloaded screen recording is empty.")
    logging.info(f"Downloaded {size} bytes to {video_path}")
    return video_path


def _to_direct_download_url(url):
    """Turns the share links of common file hosting services into direct download links."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    if host.endswith('drive.google.com'):
        match = re.search(r'/file/d/([^/]+)', parsed.path)
        file_id = match.group(1) if match else parse_qs(parsed.query).get('id', [None])[0]
        if file_id:
            return f"https://drive.google.com/uc?export=download&id={file_id}"

    if host.endswith('dropbox.com'):
        query = re.sub(r'(^|&)dl=0(&|$)', r'\1dl=1\2', parsed.query)
        if 'dl=1' not in query and 'raw=1' not in query:
            query = f"{query}&dl=1" if query else 'dl=1'
        return parsed._replace(query=query).geturl()

    return url


def _is_html_response(response):
    return 'text/html' in response.headers.get('Content-Type', '').lower()


def _extract_download_confirmation(html, page_url):
    """
    Reads the "download anyway" form that some hosts (e.g. Google Drive for large files) display
    instead of the file. Returns `(url, params)` of the confirmed download, or None.
    """
    soup = BeautifulSoup(html, 'html.parser')
    for form in soup.find_all('form'):
        action = form.get('action') or ''
        if 'download' not in action.lower():
            continue
        params = {field.get('name'): field.get('value', '')
                  for field in form.find_all('input') if field.get('name')}
        return requests.compat.urljoin(page_url, action), params
    return None


def _filename_from_response(response, url):
    """Returns a safe filename for the downloaded video, from the headers or the url."""
    disposition = response.headers.get('Content-Disposition', '')
    match = (re.search(r"filename\*\s*=\s*[^']*''([^;]+)", disposition)
             or re.search(r'filename\s*=\s*"([^"]+)"', disposition)
             or re.search(r'filename\s*=\s*([^;]+)', disposition))
    filename = unquote(match.group(1).strip()) if match else unquote(os.path.basename(urlparse(url).path))
    filename = _safe_filename(filename)
    if not os.path.splitext(filename)[1]:
        return DEFAULT_VIDEO_FILENAME
    return filename


def _safe_filename(name):
    """Removes the characters that are not allowed in file names."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', str(name)).strip(' .')
    return name or os.path.splitext(DEFAULT_VIDEO_FILENAME)[0]


def _optional_int(value):
    if value in (None, ''):
        return None
    value = int(value)
    if value <= 0:
        raise ValueError("page_height must be a positive integer.")
    return value


# ---------------------------------------------------------------------------
# Reconstruction
# ---------------------------------------------------------------------------

def reconstruct_pages(video_path, page_height=None):
    """
    Reconstructs the pages browsed through in the screen recording at `video_path`.
    `page_height` optionally forces the height (in video pixels) of the pages of a scrolled document.
    Returns a list of RGB PIL Images, in document order.
    """
    fps, frame_count, width, height = _probe_video(video_path)
    logging.info(f"Screen recording: {width}x{height}, {fps:.2f} fps, {frame_count} frames.")

    crop, background = _detect_static_borders(video_path, frame_count)
    logging.info(f"Content area (top, bottom, left, right): {crop}")

    registration = _register_frames(video_path, crop, fps)
    full_frame = (0, height, 0, width)
    if not registration['scrolled'] and crop != full_frame:
        # Without scrolling the static borders are part of the slides themselves (e.g. a template header).
        crop, background = full_frame, None
        registration = _register_frames(video_path, crop, fps)

    if registration['mosaic'].height == 0:
        return []

    canvas = _compose_canvas(video_path, crop, registration, fps)
    top = registration['mosaic'].top
    breaks = sorted({b - top for b in registration['breaks']} | {0})
    content_height = crop[1] - crop[0]

    pages = []
    for start, end in zip(breaks, breaks[1:] + [canvas.shape[0]]):
        if end > start:
            pages.extend(_split_segment(canvas[start:end], content_height, page_height, background))

    logging.info(f"Reconstructed {len(pages)} page(s).")
    return [Image.fromarray(cv2.cvtColor(page, cv2.COLOR_BGR2RGB)) for page in pages]


def _probe_video(video_path):
    capture = cv2.VideoCapture(video_path)
    try:
        if not capture.isOpened():
            raise ValueError(f"Could not open the video file: {os.path.basename(video_path)}")
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not fps or fps != fps or fps > 1000:
            fps = 25.0
        return (fps,
                int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0),
                int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    finally:
        capture.release()


def _iter_frames(video_path, step=1):
    """Yields `(index, BGR frame)` for every `step`-th frame of the video."""
    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        raise ValueError(f"Could not open the video file: {os.path.basename(video_path)}")
    try:
        index = 0
        while True:
            if index % step:
                if not capture.grab():
                    break
            else:
                ok, frame = capture.read()
                if not ok:
                    break
                yield index, frame
            index += 1
    finally:
        capture.release()


def _detect_static_borders(video_path, frame_count):
    """
    Detects the rows and columns at the edges of the frame that never change (window chrome,
    toolbars, borders) so that only the moving content area is registered.
    Returns `(crop, background)`: crop is `(top, bottom, left, right)` and background the mean BGR
    colour of the static borders (None without borders), which is usually the colour of the viewer
    background drawn between the pages.
    """
    step = max(1, frame_count // BORDER_SAMPLE_FRAMES) if frame_count > 0 else 1
    total = squares = colors = None
    samples = 0
    for _, frame in _iter_frames(video_path, step):
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float64)
        if total is None:
            total = np.zeros_like(grey)
            squares = np.zeros_like(grey)
            colors = np.zeros(frame.shape, dtype=np.float64)
        total += grey
        squares += grey * grey
        colors += frame
        samples += 1

    if not samples:
        raise ValueError("The video does not contain any readable frame.")

    crop = _static_borders_from_stats(total, squares, samples)
    return crop, _border_color(colors / samples, crop)


def _border_color(mean_frame, crop):
    """Returns the mean BGR colour of the pixels outside of the crop, or None when nothing is cropped."""
    top, bottom, left, right = crop
    outside = np.ones(mean_frame.shape[:2], dtype=bool)
    outside[top:bottom, left:right] = False
    if not outside.any():
        return None
    return tuple(float(c) for c in mean_frame[outside].mean(axis=0))


def _static_borders_from_stats(total, squares, samples):
    height, width = total.shape
    mean = total / samples
    std = np.sqrt(np.maximum(squares / samples - mean * mean, 0))
    row_activity = std.mean(axis=1)
    column_activity = std.mean(axis=0)

    if samples < 2 or max(row_activity.max(), column_activity.max()) < ACTIVE_ACTIVITY_THRESHOLD:
        return 0, height, 0, width

    def static_count(activity, content_activity):
        threshold = max(STATIC_ACTIVITY_THRESHOLD, content_activity * STATIC_RELATIVE_ACTIVITY)
        limit = int(len(activity) * MAX_BORDER_RATIO)
        count = 0
        while count < limit and activity[count] < threshold:
            count += 1
        return count

    row_content = float(np.median(row_activity))
    column_content = float(np.median(column_activity))
    return (static_count(row_activity, row_content),
            height - static_count(row_activity[::-1], row_content),
            static_count(column_activity, column_content),
            width - static_count(column_activity[::-1], column_content))


def _signature(frame, crop):
    top, bottom, left, right = crop
    grey = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2GRAY)
    return cv2.resize(grey, (SIGNATURE_WIDTH, bottom - top), interpolation=cv2.INTER_AREA).astype(np.float32)


class _Mosaic:
    """
    A growable, vertically unbounded strip of frame signatures addressed in document coordinates.
    Rows are only written once so that the registration reference never drifts.
    """

    def __init__(self, width):
        self._data = np.zeros((0, width), dtype=np.float32)
        self._written = np.zeros(0, dtype=bool)
        self._origin = 0     # array index of document row 0
        self.top = 0
        self.bottom = 0

    @property
    def height(self):
        return self.bottom - self.top

    def _ensure(self, start, end):
        grow_top = max(0, -(self._origin + start))
        grow_bottom = max(0, self._origin + end - self._data.shape[0])
        if grow_top or grow_bottom:
            extra = max(self._data.shape[0], 1024)
            grow_top = grow_top + extra if grow_top else 0
            grow_bottom = grow_bottom + extra if grow_bottom else 0
            width = self._data.shape[1]
            self._data = np.concatenate([np.zeros((grow_top, width), np.float32), self._data,
                                         np.zeros((grow_bottom, width), np.float32)])
            self._written = np.concatenate([np.zeros(grow_top, bool), self._written, np.zeros(grow_bottom, bool)])
            self._origin += grow_top

    def view(self):
        """Returns `(signatures, written mask)` of the rows between `top` and `bottom`."""
        return (self._data[self.top + self._origin:self.bottom + self._origin],
                self._written[self.top + self._origin:self.bottom + self._origin])

    def write(self, offset, signature):
        end = offset + signature.shape[0]
        self._ensure(offset, end)
        data = self._data[offset + self._origin:end + self._origin]
        written = self._written[offset + self._origin:end + self._origin]
        data[~written] = signature[~written]
        written[:] = True
        if self.height == 0:
            self.top, self.bottom = offset, end
        else:
            self.top, self.bottom = min(self.top, offset), max(self.bottom, end)


def _difference(a, b):
    return float(np.abs(a - b).mean())


def _aligned_rows(signature, reference, written, reference_top, offset, min_overlap, row_step=1, column_step=1):
    """
    Returns the `(signature, reference)` values of the already written rows they share when the first
    row of `signature` is placed at document row `offset`, or None when they overlap too little.
    """
    start = max(offset, reference_top)
    end = min(offset + signature.shape[0], reference_top + reference.shape[0])
    if end <= start:
        return None
    mask = written[start - reference_top:end - reference_top:row_step]
    if mask.sum() * row_step < min_overlap:
        return None
    return (signature[start - offset:end - offset:row_step, ::column_step][mask],
            reference[start - reference_top:end - reference_top:row_step, ::column_step][mask])


def _placement_error(signature, reference, written, reference_top, offset, min_overlap, row_step=1, column_step=1):
    aligned = _aligned_rows(signature, reference, written, reference_top, offset, min_overlap, row_step, column_step)
    return float('inf') if aligned is None else _difference(*aligned)


def _is_same_content(signature, reference, written, reference_top, offset, min_overlap):
    """Tells whether the signature shows the same content as the reference at `offset`, up to compression noise."""
    aligned = _aligned_rows(signature, reference, written, reference_top, offset, min_overlap)
    if aligned is None:
        return False
    difference = np.abs(aligned[0] - aligned[1])
    return (difference.mean() < SAME_CONTENT_THRESHOLD
            and (difference > CHANGED_CELL_LEVEL).mean() < CHANGED_CELL_RATIO)


def _best_offset(signature, reference, written, reference_top, low, high, min_overlap, preferred):
    """
    Finds where `signature` best fits in `reference` (whose first row is at `reference_top`) for a
    first row between `low` and `high`, using a coarse search refined at full resolution.
    Returns `(offset, error)`, or `(None, inf)` when no placement has enough overlap.
    """
    height = signature.shape[0]
    reference_bottom = reference_top + reference.shape[0]
    low = max(low, reference_top - height + min_overlap)
    high = min(high, reference_bottom - min_overlap)
    if low > high:
        return None, float('inf')

    def search(offsets, row_step, column_step):
        best = (float('inf'), None, float('inf'))
        for offset in offsets:
            error = _placement_error(signature, reference, written, reference_top, offset, min_overlap,
                                     row_step, column_step)
            score = error + DISTANCE_PENALTY * abs(offset - preferred)
            if score < best[0]:
                best = (score, offset, error)
        return best

    _, coarse_offset, _ = search(range(low, high + 1, COARSE_ROW_STEP), COARSE_ROW_STEP, COARSE_COLUMN_STEP)
    if coarse_offset is None:
        return None, float('inf')
    refine = range(max(low, coarse_offset - COARSE_ROW_STEP), min(high, coarse_offset + COARSE_ROW_STEP) + 1)
    _, offset, error = search(refine, 1, 1)
    return offset, error


def _register_frames(video_path, crop, fps):
    """
    Places every frame of the recording in document coordinates.

    Returns a dict with:
    - `offsets`: document row of the first content row of each frame (None when the frame is not used),
    - `still`: whether each frame shows the same content as the first frame of its run,
    - `breaks`: document rows where a new, unconnected part of the document starts,
    - `scrolled`: whether any vertical scrolling has been detected,
    - `mosaic`: the registration reference.
    """
    content_height = crop[1] - crop[0]
    max_shift = int(content_height * MAX_SHIFT_RATIO)
    min_overlap = max(1, int(content_height * MIN_OVERLAP_RATIO))
    revisit_overlap = max(1, int(content_height * REVISIT_OVERLAP_RATIO))
    settle_frames = max(2, int(round(fps * SETTLE_SECONDS)))

    mosaic = _Mosaic(SIGNATURE_WIDTH)
    offsets, still_flags, breaks = [], [], []
    scrolled = False
    run_reference = None      # first frame of the current run of identical frames
    anchor = None             # first frame displayed at the current position
    settle_reference = None   # first frame of the current attempt of unconnected content to settle
    settled = 0
    previous_offset = None

    for index, frame in _iter_frames(video_path):
        signature = _signature(frame, crop)
        still = run_reference is not None and _difference(signature, run_reference) < DUPLICATE_THRESHOLD
        if not still:
            run_reference = signature
        offset = None

        if previous_offset is not None:
            offset = previous_offset if still else _track_frame(
                signature, anchor, mosaic, previous_offset, max_shift, min_overlap)
            if offset is None:
                logging.info(f"Frame {index}: the screen content changed, waiting for it to settle.")
            elif offset != previous_offset:
                scrolled = True
                anchor = signature

        if offset is None:
            # The content is not connected to the document: wait until it has settled.
            if settle_reference is not None and _difference(signature, settle_reference) < DUPLICATE_THRESHOLD:
                settled += 1
            else:
                settle_reference, settled = signature, 0
            if settled >= settle_frames:
                offset = _place_settled_frame(signature, mosaic, revisit_overlap, breaks)
                anchor = signature

        if offset is not None:
            settle_reference, settled = None, 0
            mosaic.write(offset, signature)

        offsets.append(offset)
        still_flags.append(still)
        previous_offset = offset

    return {'offsets': offsets, 'still': still_flags, 'breaks': breaks, 'scrolled': scrolled, 'mosaic': mosaic}


def _track_frame(signature, anchor, mosaic, previous_offset, max_shift, min_overlap):
    """
    Follows the displayed content from its previous position.
    Returns the new offset, or None when the screen shows other content.
    """
    reference, written = mosaic.view()
    offset, error = _best_offset(signature, reference, written, mosaic.top,
                                 previous_offset - max_shift, previous_offset + max_shift,
                                 min_overlap, previous_offset)
    if offset is None or error >= MATCH_THRESHOLD:
        return None

    if offset == previous_offset:
        # Not scrolled: make sure it is not another, similar looking slide.
        full_mask = np.ones(signature.shape[0], dtype=bool)
        return offset if _is_same_content(signature, anchor, full_mask, 0, 0, min_overlap) else None

    staying_error = _placement_error(signature, reference, written, mosaic.top, previous_offset, min_overlap)
    return offset if error <= staying_error * SCROLL_GAIN_RATIO else None


def _place_settled_frame(signature, mosaic, revisit_overlap, breaks):
    """Places settled, unconnected content: on the same content seen before, or as a new part of the document."""
    if mosaic.height:
        reference, written = mosaic.view()
        offset, _ = _best_offset(signature, reference, written, mosaic.top,
                                 mosaic.top, mosaic.bottom, revisit_overlap, mosaic.top)
        if offset is not None and _is_same_content(signature, reference, written, mosaic.top, offset, revisit_overlap):
            return offset
    offset = mosaic.bottom
    breaks.append(offset)
    return offset


def _compose_canvas(video_path, crop, registration, fps):
    """
    Builds the full resolution document canvas. Every document row is taken from the frame that
    shows it best: preferably a frame the viewer rested on, then with the row close to the centre.
    """
    top, bottom, left, right = crop
    content_height = bottom - top
    mosaic = registration['mosaic']
    offsets = registration['offsets']

    runs = _still_runs(offsets, registration['still'])
    still_run_cap = max(1, int(round(fps * STILL_RUN_SECONDS)))
    half = content_height / 2.0
    centrality = 1.0 - np.abs(np.arange(content_height) + 0.5 - half) / half

    best_score = np.full(mosaic.height, -np.inf)
    best_frame = np.full(mosaic.height, -1, dtype=np.int64)
    for index, offset in enumerate(offsets):
        if offset is None:
            continue
        run_length, run_position = runs[index]
        score = (STILLNESS_WEIGHT * min(run_length, still_run_cap) / still_run_cap
                 + 0.5 * (run_position + 1) / run_length + centrality)
        rows = slice(offset - mosaic.top, offset - mosaic.top + content_height)
        better = score > best_score[rows]
        best_score[rows][better] = score[better]
        best_frame[rows][better] = index

    canvas = np.full((mosaic.height, right - left, 3), 255, dtype=np.uint8)
    needed = set(np.unique(best_frame[best_frame >= 0]).tolist())
    for index, frame in _iter_frames(video_path):
        if index not in needed:
            continue
        start = offsets[index] - mosaic.top
        rows = np.nonzero(best_frame[start:start + content_height] == index)[0]
        canvas[start + rows] = frame[top:bottom, left:right][rows]
    return canvas


def _still_runs(offsets, still):
    """Returns, for every frame, `(length, position)` of the run of identical frames it belongs to."""
    runs = [(1, 0)] * len(offsets)
    start = 0
    for index in range(1, len(offsets) + 1):
        continues = (index < len(offsets) and still[index]
                     and offsets[index] is not None and offsets[index] == offsets[index - 1])
        if not continues:
            length = index - start
            for position in range(length):
                runs[start + position] = (length, position)
            start = index
    return runs


# ---------------------------------------------------------------------------
# Page splitting
# ---------------------------------------------------------------------------

def _split_segment(segment, frame_height, page_height=None, background=None):
    """Splits a stitched part of the document into pages, on the gaps drawn between the pages."""
    height = segment.shape[0]
    if page_height is None and height <= frame_height * SINGLE_PAGE_RATIO:
        return [segment]

    runs = _separator_runs(segment, max(MIN_SEPARATOR_LENGTH, int(frame_height * SEPARATOR_MAX_RATIO)))
    chain = _separator_chain(runs, int(frame_height * MIN_PERIOD_RATIO), height, page_height, background)
    if chain is None:
        return [segment]

    period, cuts, color = chain
    pages = []
    for start, end in zip([0] + cuts, cuts + [height]):
        page = _trim_separator(segment[start:end], color)
        if page is not None and page.shape[0] >= period * MIN_PAGE_RATIO:
            pages.append(page)
    return pages


def _color_distance(a, b):
    return max(abs(float(x) - float(y)) for x, y in zip(a, b))


def _row_uniformity(segment):
    """Returns, for every row, whether it has a uniform colour (a few pixels may differ) and its median colour."""
    uniform = np.zeros(segment.shape[0], dtype=bool)
    colors = np.zeros((segment.shape[0], segment.shape[2]))
    for start in range(0, segment.shape[0], ROW_CHUNK):
        chunk = segment[start:start + ROW_CHUNK]
        low, median, high = np.percentile(chunk, [SEPARATOR_PERCENTILE, 50, 100 - SEPARATOR_PERCENTILE], axis=1)
        uniform[start:start + len(chunk)] = (high - low).max(axis=1) <= SEPARATOR_UNIFORMITY
        colors[start:start + len(chunk)] = median
    return uniform, colors


def _separator_runs(segment, max_length):
    """
    Returns `(start, end, colour)` of the runs of uniformly coloured rows (e.g. not counting the
    mouse pointer) that are thin enough to be the gap between two pages.
    """
    uniform, colors = _row_uniformity(segment)
    runs = []
    row = 0
    height = segment.shape[0]
    while row < height:
        if not uniform[row]:
            row += 1
            continue
        start = row
        color = colors[row]
        while row < height and uniform[row] and np.abs(colors[row] - color).max() <= SEPARATOR_UNIFORMITY:
            row += 1
        color = tuple(int(c) for c in color)
        previous = runs[-1] if runs else None
        # Video compression shades the edges of a gap: glue the touching runs of a similar colour.
        if previous and start - previous[1] <= 1 and _color_distance(color, previous[2]) <= SEPARATOR_COLOR_DISTANCE:
            longest = previous[2] if previous[1] - previous[0] >= row - start else color
            runs[-1] = (previous[0], row, longest)
        else:
            runs.append((start, row, color))
    return [run for run in runs if run[1] - run[0] <= max_length]


def _separator_chain(runs, min_period, max_period, forced_period=None, background=None):
    """
    Finds the page gaps among the uniform rows: the gaps share the same colour, preferably the colour
    of the viewer background, and repeat with the page height.
    Returns `(period, cut rows, colour)` or None.
    """
    groups = []
    for run in runs:
        for group in groups:
            if _color_distance(run[2], group[0][2]) <= SEPARATOR_COLOR_DISTANCE:
                group.append(run)
                break
        else:
            groups.append([run])

    best = None
    for members in groups:
        centers = np.array([(start + end) / 2.0 for start, end, _ in members])
        color = max(members, key=lambda run: run[1] - run[0])[2]
        is_background = background is not None and _color_distance(color, background) <= SEPARATOR_COLOR_DISTANCE
        if forced_period and not is_background:
            # A known page height is only aligned on real viewer gaps, never on bands inside the pages.
            continue

        period = forced_period or _estimate_period(centers, min_period, max_period)
        if period is not None:
            anchors = _aligned_centers(centers, period)
            if len(anchors) < (1 if forced_period else 2):
                continue
            candidate = ((is_background, len(anchors)), period, _cuts_from_anchors(anchors, period, max_period), color)
        elif is_background:
            # A single gap (two pages) has no period: trust the runs of the viewer background colour.
            cuts = [int((start + end) // 2) for start, end, _ in members
                    if end - start >= MIN_SEPARATOR_LENGTH and 0 < start and end < max_period]
            if not cuts:
                continue
            candidate = ((True, len(cuts)), max_period, cuts, color)
        else:
            continue

        if best is None or candidate[0] > best[0]:
            best = candidate

    if best is not None:
        return best[1:]
    if forced_period:
        return forced_period, list(range(forced_period, max_period, forced_period)), None
    return None


def _estimate_period(centers, min_period, max_period):
    """Returns the most frequent spacing between the centres, or None."""
    if len(centers) < 2:
        return None
    differences = np.abs(centers[:, None] - centers[None, :])
    differences = differences[(differences >= min_period) & (differences <= max_period)]
    if not differences.size:
        return None
    histogram = np.bincount(np.round(differences).astype(np.int64))
    smoothed = np.convolve(histogram, np.ones(2 * PERIOD_TOLERANCE + 1), mode='same')
    period = int(np.argmax(smoothed))
    # Gaps two pages apart are almost as frequent as consecutive gaps: prefer the smallest spacing.
    for divisor in range(max(1, period // max(1, min_period)), 1, -1):
        sub_period = int(round(period / divisor))
        if sub_period >= min_period and smoothed[sub_period] >= smoothed[period] * SUBPERIOD_RATIO:
            return sub_period
    return period


def _period_tolerance(period):
    return max(PERIOD_TOLERANCE, period * PERIOD_DRIFT_RATIO)


def _aligned_centers(centers, period):
    """
    Returns the largest chain of centres spaced by `period`. The chain follows each gap it finds,
    so that small page height rounding errors do not accumulate, and skips the missing gaps.
    """
    ordered = np.sort(centers)
    tolerance = _period_tolerance(period)
    best = []
    for anchor in ordered:
        chain = {float(anchor)}
        for direction in (1, -1):
            position = anchor
            while True:
                expected = position + direction * period
                if expected < ordered[0] - tolerance or expected > ordered[-1] + tolerance:
                    break
                nearest = ordered[np.argmin(np.abs(ordered - expected))]
                if abs(nearest - expected) <= tolerance:
                    chain.add(float(nearest))
                    position = nearest
                else:
                    position = expected
        if len(chain) > len(best):
            best = sorted(chain)
    return best


def _cuts_from_anchors(anchors, period, height):
    """Cuts on every detected gap, and extrapolates the missing gaps from the page height."""
    tolerance = _period_tolerance(period)
    position = anchors[0]
    while position - period > tolerance:
        position -= period
    cuts = []
    remaining = list(anchors)
    while position < height - tolerance:
        nearby = [a for a in remaining if abs(a - position) <= tolerance]
        if nearby:
            position = nearby[0]
            remaining.remove(position)
        if 0 < position < height:
            cuts.append(int(round(position)))
        position += period
    return sorted(set(cuts))


def _trim_separator(page, color):
    """Removes the rows and columns of the gap colour around a page. Returns None for an empty page."""
    if color is None:
        return page
    difference = np.abs(page.astype(np.int16) - np.array(color, dtype=np.int16)).max(axis=2) > SEPARATOR_COLOR_DISTANCE
    rows = np.nonzero(difference.mean(axis=1) > SEPARATOR_PERCENTILE / 100.0)[0]
    columns = np.nonzero(difference.mean(axis=0) > SEPARATOR_PERCENTILE / 100.0)[0]
    if not rows.size or not columns.size:
        return None
    return page[rows[0]:rows[-1] + 1, columns[0]:columns[-1] + 1]


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _compile_pdf(pages, output_pdf_path):
    """Writes the page images into a single PDF, one image per page."""
    first, rest = pages[0], pages[1:]
    first.save(output_pdf_path, "PDF", resolution=PDF_RESOLUTION, save_all=True, append_images=rest)
    logging.info(f"PDF with {len(pages)} page(s) saved to {output_pdf_path}")
