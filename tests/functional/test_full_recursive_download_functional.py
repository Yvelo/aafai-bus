import pytest
from unittest.mock import MagicMock
import tempfile
import shutil
import os
from src.actions.full_recursive_download import execute

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
            shutil.rmtree(temp_download_dir)
            # Restore the original WDM_HOME value
            if original_wdm_home:
                os.environ['WDM_HOME'] = original_wdm_home
            else:
                del os.environ['WDM_HOME']

    def test_download_from_arxiv(self, temp_dir):
        """
        Tests a real download from the arXiv website to verify the scraper can handle
        a live download task.
        """
        job_id = "functional-test-download-arxiv"
        # Using a page with known PDF links for testing.
        start_url = "https://arxiv.org/list/cs.AI/new"

        params = {
            "url": start_url,
            "max_depth": 1,
            "max_links": 5,
            "file_match_pattern": "\\.pdf$"
        }
        mock_write_result = MagicMock()

        execute(job_id, params, temp_dir, mock_write_result)

        mock_write_result.assert_called_once()
        _, result = mock_write_result.call_args[0]

        assert result['job_id'] == job_id
        assert result['status'] == 'complete'
        assert 'error' not in result

        # Verify that some files were downloaded
        download_dir = os.path.join(temp_dir, job_id, "downloads")
        assert os.path.exists(download_dir)
        downloaded_files = os.listdir(download_dir)
        assert len(downloaded_files) > 0
