import pytest
from unittest.mock import MagicMock
import tempfile
import shutil
from src.actions.search_espacenet import execute


@pytest.mark.functional
class TestSearchEspacenetFunctional:
    """
    Functional tests for the search_espacenet action.
    These tests run against the live Espacenet website using a real browser.
    They are marked as 'functional' and may be slower to run.
    """

    @pytest.fixture
    def temp_dir(self):
        """Pytest fixture to create and clean up a temporary directory for tests."""
        temp_download_dir = tempfile.mkdtemp()
        try:
            yield temp_download_dir
        finally:
            shutil.rmtree(temp_download_dir)

    def test_search_by_keywords(self, temp_dir):
        """
        Tests a real search for patents by keywords to verify the scraper can handle
        a live query. We limit the results to keep the test quick.
        """
        job_id = "functional-test-keyword-search"
        params = {
            "queries": [
                ["neoantigen", "tumor", "irradiated", "CAR-T", "5FU"]
            ],
            "max_number_of_patents": 100
        }
        mock_write_result = MagicMock()

        execute(job_id, params, temp_dir, mock_write_result)

        mock_write_result.assert_called_once()
        _, result = mock_write_result.call_args[0]

        assert result['job_id'] == job_id
        assert result['status'] == 'complete'
        assert 'error' not in result

        patents = result['result']['patents']
        assert len(patents) > 0
        assert len(patents) <= 100
