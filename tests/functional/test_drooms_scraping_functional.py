# -*- coding: utf-8 -*-
"""
Functional test for the drooms_scraping action.

**WARNING:** This test performs a live login and scraping session against the real D-Rooms platform.
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

from actions import drooms_scraping

@pytest.mark.slow
def test_drooms_scraping_live():
    """
    Performs a live functional test of the drooms_scraping action.
    It will log in, and attempt to scrape a small part of the data room.
    """
    # --- Test Configuration ---
    # IMPORTANT: In a real-world project, these credentials should not be hardcoded.
    # They should be loaded from environment variables or a secure vault.
    DROOMS_URL = os.environ.get('DROOMS_URL')
    DROOMS_USERNAME = os.environ.get('DROOMS_USERNAME')
    DROOMS_PASSWORD = os.environ.get('DROOMS_PASSWORD')

    # Create a temporary directory for the test output
    test_output_dir = os.path.join(os.path.dirname(__file__), 'test_output_drooms')
    
    # Robust cleanup: Handle cases where files might be locked by a previous run
    if os.path.exists(test_output_dir):
        try:
            shutil.rmtree(test_output_dir)
        except PermissionError:
            print(f"Warning: Could not remove old test directory {test_output_dir}. "
                  f"Files might be locked by a previous run. Retrying after a delay.")
            time.sleep(2)
            shutil.rmtree(test_output_dir, ignore_errors=True)

    # Use exist_ok=True to prevent an error if the directory still exists after cleanup attempt
    os.makedirs(test_output_dir, exist_ok=True)

    # --- Action Parameters ---
    params = {
        "url": DROOMS_URL,
        "username": DROOMS_USERNAME,
        "password": DROOMS_PASSWORD
    }
    
    # The job_context provides the output directory for the action
    job_context = {
        "job_output_dir": test_output_dir
    }

    # --- Execute the Action ---
    result = None
    try:
        result = drooms_scraping.run(params, job_context)
    finally:
        # --- Assertions and Cleanup ---
        print("--- Functional Test Result ---")
        print(result)

        # Basic assertion: Check if the action reported completion.
        assert result is not None, "The action did not return a result."
        assert result.get("status") == "complete", f"The action failed with message: {result.get('message')}"

        # Check that some output was actually created
        download_root = os.path.join(test_output_dir, 'drooms_download')
        assert os.path.exists(download_root), "The root download directory was not created."
        
        # Check if at least one PDF was created (this is a good sign)
        found_pdf = False
        for root, _, files in os.walk(download_root):
            if any(fname.endswith('.pdf') for fname in files):
                found_pdf = True
                break
        assert found_pdf, "No PDF files were found in the output directory."

if __name__ == '__main__':
    # This allows running the test directly for debugging.
    pytest.main([__file__, '-s', '-m', 'slow'])
