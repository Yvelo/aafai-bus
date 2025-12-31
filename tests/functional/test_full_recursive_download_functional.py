import pytest
from unittest.mock import MagicMock
import tempfile
import shutil
import os
from src.actions.full_recursive_download import execute
import time

@pytest.mark.functional
class TestFullRecursiveDownloadFunctional:
    """
    Functional tests for the full_recursive_download action.
    These tests run against live websites using a real browser.
    They are marked as 'functional' and may be slower to run.
    """

    @pytest.fixture
    def temp_dir(self):
        """
        Pytest fixture to create and clean up a temporary directory for tests.
        This directory will be used for downloads and for webdriver-manager caching.
        """
        temp_download_dir = tempfile.mkdtemp()

        # Store the original WDM_HOME value if it exists
        original_wdm_home = os.environ.get('WDM_HOME')

        # Set WDM_HOME to the temporary directory to ensure we have permissions
        os.environ['WDM_HOME'] = temp_download_dir

        try:
            yield temp_download_dir
        finally:
            # Add a delay before cleanup to ensure file locks are released
            time.sleep(2)
            shutil.rmtree(temp_download_dir, ignore_errors=True)
            # Restore the original WDM_HOME value
            if original_wdm_home:
                os.environ['WDM_HOME'] = original_wdm_home
            elif 'WDM_HOME' in os.environ:
                del os.environ['WDM_HOME']

    @staticmethod
    def _run_test(job_id, params, temp_dir):
        """Helper function to run a download test."""
        mock_write_result = MagicMock()

        execute(job_id, params, temp_dir, mock_write_result)

        mock_write_result.assert_called_once()
        _, result = mock_write_result.call_args[0]
        print(result)

        assert result['job_id'] == job_id
        assert result['status'] == 'complete'
        assert 'error' not in result

        # Verify that the job-specific directory was created
        download_dir = os.path.join(temp_dir, job_id)
        assert os.path.exists(download_dir)

    def test_download_from_google_scholar(self, temp_dir):
        """
        Tests a real download from Google Scholar to verify the scraper can handle
        a live download task.
        """
        job_id = "functional-test-download-google-scholar"
        start_url = "https://scholar.google.com/scholar?as_q=&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=Olivier+Lantz&as_publication=&as_ylo=&as_yhi=&hl=en&as_sdt=0%2C5"
        params = {
            "url": start_url,
            "max_depth": 0
        }
        self._run_test(job_id, params, temp_dir)

    def test_download_from_mit(self, temp_dir):
        """
        Tests a real download from the arXiv website to verify the scraper can handle
        a live download task.
        """
        job_id = "functional-test-download-mit"
        start_url = "https://mit.edu"
        params = {
            "url": start_url,
            "max_depth": 0
        }
        self._run_test(job_id, params, temp_dir)
