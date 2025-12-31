# -*- coding: utf-8 -*-
"""
Functional test for the docsend_scraping action.

**WARNING:** This test performs a live scraping session against the real DocSend platform.
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

# Add the src directory to the path to allow importing the action
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))

from actions import docsend_scraping

@pytest.mark.slow
def test_docsend_scraping_live():
    """
    Performs a live functional test of the docsend_scraping action.
    It will access a DocSend link, enter an email, and scrape the document.
    """
    # --- Test Configuration ---
    DOCSEND_URL = os.environ.get('DOCSEND_URL', 'https://quantilight.docsend.com/view/78vyywqbgjctw959')
    USER_EMAIL = os.environ.get('USER_EMAIL', 'ylm@aaf.lu')
    DOCUMENT_NAME = os.environ.get('DOCUMENT_NAME', '20251231 Quantilight Pitch Deck') # Default name if not set

    # Use C:/temp as the base for test outputs to avoid long path issues
    base_path = 'C:/temp'
    test_output_dir = os.path.join(base_path, 'test_output_docsend')
    
    if os.path.exists(test_output_dir):
        shutil.rmtree(test_output_dir, ignore_errors=True)

    os.makedirs(test_output_dir, exist_ok=True)

    # --- Action Parameters ---
    params = {
        "url": DOCSEND_URL,
        "user_email": USER_EMAIL,
        "document_name": DOCUMENT_NAME
    }
    
    job_id = str(uuid.uuid4())
    
    # --- Mock callback function ---
    result_holder = {}
    def mock_write_result(job_id, result_data):
        result_holder['result'] = result_data

    # --- Execute the Action ---
    try:
        docsend_scraping.execute(job_id, params, test_output_dir, mock_write_result)
    finally:
        # --- Assertions and Cleanup ---
        result = result_holder.get('result')
        print("--- Functional Test Result ---")
        # Print result without base64 content for readability
        if result and 'result' in result and 'downloaded_files' in result['result']:
            result_copy = copy.deepcopy(result)
            if result_copy['result']['downloaded_files']:
                result_copy['result']['downloaded_files'][0].pop('content_base64', None)
            print(json.dumps(result_copy, indent=2))
        else:
            print(json.dumps(result, indent=2))


        assert result is not None, "The action did not return a result."
        assert result.get("status") == "complete", f"The action failed with error: {result.get('error')}"
        assert "result" in result, "The 'result' key is missing from the successful response."

        action_result = result.get("result")
        assert "downloaded_files" in action_result, "The 'downloaded_files' key is missing from the action result."
        assert len(action_result["downloaded_files"]) == 1, "Expected one downloaded file."

        downloaded_file_info = action_result["downloaded_files"][0]
        expected_pdf_filename = f"{DOCUMENT_NAME}.pdf"
        expected_pdf_path = os.path.join(test_output_dir, expected_pdf_filename)

        # Normalize path separators for cross-platform compatibility
        actual_path = downloaded_file_info["path"].replace("\\", "/")
        normalized_expected_path = expected_pdf_path.replace("\\", "/")

        assert downloaded_file_info["filename"] == expected_pdf_filename, "Filename in result does not match expected."
        assert actual_path == normalized_expected_path, "File path in result does not match expected."
        assert downloaded_file_info["size_bytes"] > 0, "File size in result is not greater than zero."
        assert "content_base64" in downloaded_file_info, "The 'content_base64' key is missing."
        
        # Verify that the base64 content is valid
        try:
            decoded_content = base64.b64decode(downloaded_file_info["content_base64"])
            assert len(decoded_content) == downloaded_file_info["size_bytes"], "Decoded content size does not match reported size."
        except (TypeError, ValueError):
            pytest.fail("The 'content_base64' field contains invalid Base64 data.")


        # Verify file existence and size on disk as a final check
        assert os.path.exists(expected_pdf_path), f"The expected PDF was not created at {expected_pdf_path}"
        assert os.path.getsize(expected_pdf_path) > 0, "The created PDF file is empty on disk."

if __name__ == '__main__':
    pytest.main([__file__, '-s', '-m', 'slow'])
