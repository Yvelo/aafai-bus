# -*- coding: utf-8 -*-
"""
Functional test for the papermark_scraping action.

**WARNING:** This test performs a live scraping session against the real Papermark platform.
It is designed to be run manually or in a controlled CI environment. It is marked as 'slow'
to allow it to be skipped during normal, fast test runs.

To run only this test:
pytest -m slow

To skip this test:
pytest -m "not slow"
"""

import pytest
import os
import shutil
import sys
import uuid
import json
import base64
import copy
import re
import time
import random

# Add the src directory to the path to allow importing the action
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))
# ... and this directory, for the data room inventory module next to this file
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from actions import papermark_scraping
from test_papermark_file_list import PAPERMARK_DOCUMENTS

# Realistic desktop User-Agents representing varied browser identities (Chrome, Edge, Firefox, Safari on Windows & Mac)
USER_AGENTS = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    # Edge Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0",
    # Chrome Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    # Safari Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    # Firefox Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:129.0) Gecko/20100101 Firefox/129.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
]

# --- Data room download configuration (overridable through environment variables) ---
# Root of the local copy of the data room; the Papermark folder tree is recreated below it.
DATAROOM_OUTPUT_DIR = os.environ.get(
    'PAPERMARK_OUTPUT_DIR', 'C:/Temp/papermark_test_output')
# Papermark document types to download. 'sheet' (Excel viewer) and 'other' (TIF) are not
# page-image documents and are skipped by default; 'zip' cannot be viewed at all.
DOWNLOAD_TYPES = [t.strip() for t in os.environ.get('PAPERMARK_TYPES', 'pdf,image').split(',') if t.strip()]
# Optional filter: only documents whose folder starts with this prefix, e.g. '04_Technology_Science'
FOLDER_FILTER = os.environ.get('PAPERMARK_FOLDER', '')

_WINDOWS_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_name(name, max_length=150):
    """Makes a file or folder name valid on Windows (no : ? * etc., no trailing dot/space)."""
    cleaned = _WINDOWS_FORBIDDEN.sub('_', name).strip().rstrip('. ')
    return (cleaned or 'document')[:max_length]


def _long_path(path):
    """Allows paths longer than 260 characters on Windows (deep data room folders)."""
    path = os.path.abspath(path)
    if os.name == 'nt' and not path.startswith('\\\\?\\'):
        return '\\\\?\\' + path
    return path


def _target_pdf_path(doc_info):
    """Local path of a document: <output>/<papermark folder tree>/<document name>.pdf"""
    folder_parts = [_safe_name(part) for part in doc_info['folder'].split('/') if part]
    base_name = os.path.splitext(doc_info['document_name'])[0]
    return os.path.join(DATAROOM_OUTPUT_DIR, *folder_parts, _safe_name(base_name) + '.pdf')

@pytest.mark.slow
class TestPapermarkScrapingFunctional:
    """
    Functional tests for the papermark_scraping action.
    These tests will simulate real Papermark scraping scenarios.
    """

    @pytest.fixture
    def temp_dir(self):
        """
        Pytest fixture to create and clean up a temporary directory for tests.
        This directory will be used for downloads.
        """
        base_path = 'C:/temp' # Use C:/temp as the base for test outputs
        temp_download_dir = os.path.join(base_path, f'test_output_papermark_{uuid.uuid4()}')
        os.makedirs(temp_download_dir, exist_ok=True)
        try:
            yield temp_download_dir
        finally:
            time.sleep(1) # Give a moment for file handles to release
            shutil.rmtree(temp_download_dir, ignore_errors=True)

    # Directory where the produced PDFs are kept so that they can be inspected after the test run.
    KEPT_OUTPUT_DIR = 'C:/temp/papermark_test_output'

    @staticmethod
    def _get_pdf_page_count(pdf_path):
        """Returns the number of pages of a PDF file by counting its page objects."""
        with open(pdf_path, 'rb') as pdf_file:
            content = pdf_file.read()
        return content.count(b'/Type /Page') - content.count(b'/Type /Pages')

    @classmethod
    def _keep_downloaded_file(cls, pdf_path):
        """Copies the produced PDF outside of the temporary directory for manual inspection."""
        if not os.path.exists(pdf_path):
            return
        os.makedirs(cls.KEPT_OUTPUT_DIR, exist_ok=True)
        kept_path = os.path.join(cls.KEPT_OUTPUT_DIR, os.path.basename(pdf_path))
        shutil.copy2(pdf_path, kept_path)
        print(f"Kept a copy of the downloaded document at: {kept_path}")

    @classmethod
    def _assert_single_download_result(cls, job_id, result_holder, expected_document_name, temp_download_dir, expected_min_pages=1):
        """Helper function to assert the result of a single Papermark download."""
        result = result_holder.get('result')

        # Print result without base64 content for readability
        if result and 'result' in result and 'downloaded_files' in result['result']:
            result_copy = copy.deepcopy(result)
            if result_copy['result']['downloaded_files']:
                # Remove content_base64 for printing, but keep it for assertion later
                for f_info in result_copy['result']['downloaded_files']:
                    f_info.pop('content_base64', None)
            print(f"--- Functional Test Result for Job {job_id} ---")
            print(json.dumps(result_copy, indent=2))
        else:
            print(f"--- Functional Test Result for Job {job_id} ---")
            print(json.dumps(result, indent=2))

        assert result is not None, f"The action did not return a result for job {job_id}."
        assert result.get("status") == "Completed", f"The action failed for job {job_id} with error: {result.get('error')}"
        assert "result" in result, f"The 'result' key is missing from the successful response for job {job_id}."

        action_result = result.get("result")
        assert "downloaded_files" in action_result, f"The 'downloaded_files' key is missing from the action result for job {job_id}."
        assert len(action_result["downloaded_files"]) == 1, f"Expected one downloaded file for job {job_id}."

        downloaded_file_info = action_result["downloaded_files"][0]
        expected_pdf_filename = f"{expected_document_name}.pdf"
        expected_pdf_path = os.path.join(temp_download_dir, expected_pdf_filename)

        # Normalize path separators for cross-platform compatibility
        actual_path = downloaded_file_info["path"].replace("\\", "/")
        normalized_expected_path = expected_pdf_path.replace("\\", "/")

        assert downloaded_file_info["filename"] == expected_pdf_filename, f"Filename in result does not match expected for job {job_id}."
        assert actual_path == normalized_expected_path, f"File path in result does not match expected for job {job_id}."
        assert downloaded_file_info["size_bytes"] > 0, f"File size in result is not greater than zero for job {job_id}."
        assert "content_base64" in downloaded_file_info, f"The 'content_base64' key is missing for job {job_id}."

        # Verify that the base64 content is valid
        try:
            decoded_content = base64.b64decode(downloaded_file_info["content_base64"])
            assert len(decoded_content) == downloaded_file_info["size_bytes"], f"Decoded content size does not match reported size for job {job_id}."
        except (TypeError, ValueError):
            pytest.fail(f"The 'content_base64' field contains invalid Base64 data for job {job_id}.")

        # Verify file existence and size on disk as a final check
        assert os.path.exists(expected_pdf_path), f"The expected PDF was not created at {expected_pdf_path} for job {job_id}"
        assert os.path.getsize(expected_pdf_path) > 0, f"The created PDF file is empty on disk for job {job_id}."

        # The whole document must be captured, not only the first page.
        # Some documents legitimately contain a single page, hence the configurable minimum.
        page_count = cls._get_pdf_page_count(expected_pdf_path)
        print(f"The created PDF contains {page_count} page(s).")
        assert page_count >= expected_min_pages, (
            f"Only {page_count} page(s) were captured for job {job_id}; "
            f"at least {expected_min_pages} page(s) were expected, the document was not fully downloaded."
        )

        cls._keep_downloaded_file(expected_pdf_path)


    def test_single_papermark_scraping_live(self, temp_dir):
        """
        Performs a live functional test of the papermark_scraping action for a single document.
        It will access a Papermark link, enter an email, and scrape the document.
        """
        # --- Test Configuration ---
        PAPERMARK_URL = os.environ.get('PAPERMARK_URL', 'https://wm0skin9pxcl1neaoqut75.veladrop.app/ylm')
        USER_EMAIL = os.environ.get('USER_EMAIL', 'yvesloicmartin@aaf.lu')
        DOCUMENT_NAME = os.environ.get('DOCUMENT_NAME', '20260920 Vela Pitch Deck')
        EXPECTED_MIN_PAGES = int(os.environ.get('EXPECTED_MIN_PAGES', '13'))

        # --- Action Parameters ---
        params = {
            "url": PAPERMARK_URL,
            "user_email": USER_EMAIL,
            "document_name": DOCUMENT_NAME
        }

        job_id = str(uuid.uuid4())

        # --- Mock callback function ---
        result_holder = {}
        def mock_write_result(job_id_arg, result_data):
            result_holder['result'] = result_data

        # --- Execute the Action ---
        try:
            papermark_scraping.execute(job_id, params, temp_dir, mock_write_result)
        finally:
            self._assert_single_download_result(job_id, result_holder, DOCUMENT_NAME, temp_dir, EXPECTED_MIN_PAGES)

    def test_multiple_papermark_downloads(self, temp_dir):
        """
        Downloads every document of the data room (PAPERMARK_DOCUMENTS) and saves each PDF under
        DATAROOM_OUTPUT_DIR, recreating the Papermark folder tree.

        - A single Chrome session is used for the whole list: the email / passcode / verification
          code gate is passed once (type the code received by email in the Chrome window), then
          every other document of the data room opens directly with the session cookies.
        - Documents already present locally are skipped, so the test can simply be re-run to
          resume after an interruption or to retry failures.
        - One failing document does not stop the run: failures are collected and reported at
          the end, and written to _download_report.json in the output directory.
        - Environment variables: PAPERMARK_OUTPUT_DIR, PAPERMARK_TYPES (default 'pdf,image'),
          PAPERMARK_FOLDER (folder prefix filter), PAPERMARK_CODE_TIMEOUT (seconds allowed to
          type the verification code, default 600).
        """
        documents = [d for d in PAPERMARK_DOCUMENTS
                     if d['type'] in DOWNLOAD_TYPES and d['folder'].startswith(FOLDER_FILTER)]
        print(f"\n{len(documents)} document(s) selected out of {len(PAPERMARK_DOCUMENTS)}; "
              f"output: {DATAROOM_OUTPUT_DIR}")

        report = {'downloaded': [], 'already_present': [], 'failed': [],
                  'skipped_type': [f"{d['folder']}/{d['document_name']} ({d['type']})"
                                   for d in PAPERMARK_DOCUMENTS if d['type'] not in DOWNLOAD_TYPES]}

        to_download = []
        for doc_info in documents:
            target = _target_pdf_path(doc_info)
            if os.path.exists(_long_path(target)) and os.path.getsize(_long_path(target)) > 0:
                report['already_present'].append(target)
            else:
                to_download.append(doc_info)
        print(f"{len(report['already_present'])} already downloaded, {len(to_download)} to download.")

        user_agent = random.choice(USER_AGENTS)
        print(f"Browser identity for this run: {user_agent}")
        session = _PapermarkSession(temp_dir, user_agent=user_agent)
        try:
            for index, doc_info in enumerate(to_download, start=1):
                target = _target_pdf_path(doc_info)
                label = f"[{index}/{len(to_download)}] {doc_info['folder']}/{doc_info['document_name']}"
                work_pdf = os.path.join(temp_dir, f"{uuid.uuid4().hex[:8]}.pdf")
                print(f"\n--- {label} ---")
                download_success = False
                for attempt in range(1, 3):
                    try:
                        if attempt > 1:
                            print(f"Retrying download (attempt {attempt}/2)...")
                        page_count = session.download(doc_info, work_pdf)
                        assert os.path.exists(work_pdf) and os.path.getsize(work_pdf) > 0, "Empty or missing PDF."
                        os.makedirs(_long_path(os.path.dirname(target)), exist_ok=True)
                        shutil.copy2(_long_path(work_pdf), _long_path(target))
                        print(f"Saved ({page_count} page(s)): {target}")
                        report['downloaded'].append(target)
                        download_success = True
                        break
                    except Exception as error:
                        error_type = type(error).__name__
                        error_text = str(error).strip()
                        message = f"{error_type}: {error_text}" if error_text else error_type
                        if attempt < 2:
                            print(f"Attempt {attempt} failed ({message}). Re-trying with page reload...")
                            time.sleep(2)
                        else:
                            print(f"FAILED: {label}: {message}")
                            report['failed'].append({'document': f"{doc_info['folder']}/{doc_info['document_name']}",
                                                     'url': doc_info['url'], 'error': message})
                            session.save_error_screenshot(os.path.join(temp_dir, 'error_screenshot.png'))
                    finally:
                        if os.path.exists(work_pdf):
                            os.remove(work_pdf)
        finally:
            session.close()

        os.makedirs(_long_path(DATAROOM_OUTPUT_DIR), exist_ok=True)
        with open(_long_path(os.path.join(DATAROOM_OUTPUT_DIR, '_download_report.json')), 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"\n=== Data room download summary ===\n"
              f"Downloaded: {len(report['downloaded'])}  |  Already present: {len(report['already_present'])}  |  "
              f"Failed: {len(report['failed'])}  |  Skipped (type): {len(report['skipped_type'])}")
        for failure in report['failed']:
            print(f"  FAILED  {failure['document']}: {failure['error']}")

        assert not report['failed'], (
            f"{len(report['failed'])} document(s) failed, see _download_report.json; "
            f"re-run the test to retry them (downloaded files are skipped).")


class _PapermarkSession:
    """
    One Chrome session shared by all the documents of a data room.

    Papermark asks for the email, the passcode and a verification code sent by email the first
    time; the resulting session cookies then give access to every document of the data room.
    The browser is restarted automatically if it crashes (the gate is then passed again).
    """

    CODE_TIMEOUT = int(os.environ.get('PAPERMARK_CODE_TIMEOUT', '600'))

    def __init__(self, work_dir, user_agent=None):
        self.work_dir = work_dir
        self.user_agent = user_agent
        self.driver = None
        self.service = None

    def _start(self):
        self.close()
        self.driver, self.service = papermark_scraping._setup_driver(self.work_dir)
        if self.user_agent:
            try:
                self.driver.execute_cdp_cmd('Network.setUserAgentOverride', {'userAgent': self.user_agent})
            except Exception as e:
                print(f"Warning: Could not set custom User-Agent via CDP: {e}")

    def _alive(self):
        try:
            _ = self.driver.current_url
            return True
        except Exception:
            return False

    def download(self, doc_info, output_pdf_path):
        """Opens the document in the shared session, captures every page and writes the PDF."""
        if self.driver is None or not self._alive():
            self._start()
        driver = self.driver
        driver.get(doc_info['url'])

        state = self._wait_for_gate_or_viewer(timeout=30)
        if state == 'gate':
            print("Access form displayed: entering email and passcode.")
            papermark_scraping._navigate_and_authenticate(
                driver, doc_info['url'], doc_info['user_email'], doc_info.get('passcode'))
            self._wait_for_viewer_after_gate()
        elif state != 'viewer':
            raise TimeoutError("Neither the document viewer nor the access form appeared.")

        total_pages = papermark_scraping._get_total_pages_count(driver)
        pages = papermark_scraping._capture_all_pages(driver, total_pages)
        assert pages, "No pages were captured."
        papermark_scraping._compile_pdf(pages, output_pdf_path)
        if len(pages) < total_pages:
            print(f"WARNING: only {len(pages)}/{total_pages} page(s) captured.")
        return len(pages)

    def _wait_for_gate_or_viewer(self, timeout):
        """Returns 'viewer' when page images are displayed, 'gate' when the email form is shown."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if papermark_scraping._count_page_image_elements(self.driver) > 0:
                return 'viewer'
            try:
                if self.driver.execute_script(
                        "var e = document.getElementById('email'); return !!(e && e.offsetParent);"):
                    return 'gate'
            except Exception:
                pass
            time.sleep(0.5)
        return None

    def _wait_for_viewer_after_gate(self):
        """
        After the access form, Papermark may ask for the verification code sent by email.
        The code is typed by hand in the Chrome window; the test waits until the viewer shows up.
        """
        if self._wait_for_gate_or_viewer(timeout=20) == 'viewer':
            return
        print("\n" + "=" * 70 +
              "\n>>> Papermark asks for a verification code: type the code received by email"
              "\n>>> in the Chrome window (only once for the whole data room)."
              f"\n>>> Waiting up to {self.CODE_TIMEOUT // 60} minutes..."
              "\n" + "=" * 70)
        deadline = time.time() + self.CODE_TIMEOUT
        while time.time() < deadline:
            if papermark_scraping._count_page_image_elements(self.driver) > 0:
                print("Verification accepted, the session is open for the whole data room.")
                return
            time.sleep(1)
        raise TimeoutError("The document viewer did not appear (verification code not entered in time?).")

    def save_error_screenshot(self, path):
        try:
            if self.driver:
                self.driver.save_screenshot(path)
        except Exception:
            pass

    def close(self):
        driver, service = self.driver, self.service
        self.driver = self.service = None
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        if service:
            try:
                service.stop()
            except Exception:
                pass
        if driver and hasattr(driver, 'temp_dir'):
            time.sleep(1)
            shutil.rmtree(driver.temp_dir, ignore_errors=True)


# The __main__ block is adjusted to run pytest for the class
if __name__ == '__main__':
    pytest.main([__file__, '-s', '-m', 'slow'])