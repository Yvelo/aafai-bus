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
import time

# Add the src directory to the path to allow importing the action
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))

from actions import papermark_scraping

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
        PAPERMARK_URL = os.environ.get('PAPERMARK_URL', 'https://www.papermark.com/view/cmtujk5820001jy041ql4mv92')
        USER_EMAIL = os.environ.get('USER_EMAIL', 'yvesloicmartin@aaf.lu')
        DOCUMENT_NAME = os.environ.get('DOCUMENT_NAME', '20260913 2NAFISH Pitch Deck')
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
        Tests processing a collection of Papermark downloads.
        """
        papermark_documents = [
            {"url": "https://www.papermark.com/view/cmtujk5820001jy041ql4mv92",
             "user_email": "yvesloicmartin@aaf.lu",
             "document_name": "07_Publications_BC-seq and metastasis signature",
             "passcode": ""}
        ]

        for doc_info in papermark_documents:
            job_id = str(uuid.uuid4())
            # Create a sub-directory for each job within the main temp_dir
            job_download_dir = os.path.join(temp_dir, job_id)
            os.makedirs(job_download_dir, exist_ok=True)

            params = {
                "url": doc_info["url"],
                "user_email": doc_info["user_email"],
                "document_name": doc_info["document_name"],
                "passcode": doc_info.get("passcode")
            }

            result_holder = {}
            def mock_write_result(job_id_arg, result_data):
                result_holder['result'] = result_data

            print(f"\n--- Starting Papermark download for: {doc_info['document_name']} (Job ID: {job_id}) ---")
            try:
                papermark_scraping.execute(job_id, params, job_download_dir, mock_write_result)
            finally:
                self._assert_single_download_result(job_id, result_holder, doc_info["document_name"], job_download_dir)
                print(f"--- Finished Papermark download for: {doc_info['document_name']} (Job ID: {job_id}) ---")

# The __main__ block is adjusted to run pytest for the class
if __name__ == '__main__':
    pytest.main([__file__, '-s', '-m', 'slow'])
