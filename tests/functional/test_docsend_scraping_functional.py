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
import time

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
    DOCSEND_URL = os.environ.get('DOCSEND_URL')
    USER_EMAIL = os.environ.get('USER_EMAIL')
    DOCUMENT_NAME = os.environ.get('DOCUMENT_NAME', 'scraped_document') # Default name if not set

    # Create a temporary directory for the test output
    test_output_dir = os.path.join(os.path.dirname(__file__), 'test_output_docsend')
    
    if os.path.exists(test_output_dir):
        shutil.rmtree(test_output_dir, ignore_errors=True)

    os.makedirs(test_output_dir, exist_ok=True)

    # --- Action Parameters ---
    params = {
        "url": DOCSEND_URL,
        "user_email": USER_EMAIL,
        "document_name": DOCUMENT_NAME
    }
    
    job_context = {
        "job_output_dir": test_output_dir
    }

    # --- Execute the Action ---
    result = None
    try:
        result = docsend_scraping.run(params, job_context)
    finally:
        # --- Assertions and Cleanup ---
        print("--- Functional Test Result ---")
        print(result)

        assert result is not None, "The action did not return a result."
        assert result.get("status") == "complete", f"The action failed with message: {result.get('message')}"

        # Check that the PDF was actually created
        expected_pdf_path = os.path.join(test_output_dir, f"{DOCUMENT_NAME}.pdf")
        assert os.path.exists(expected_pdf_path), f"The expected PDF was not created at {expected_pdf_path}"
        
        # Check that the PDF file is not empty
        assert os.path.getsize(expected_pdf_path) > 0, "The created PDF file is empty."

if __name__ == '__main__':
    pytest.main([__file__, '-s', '-m', 'slow'])
