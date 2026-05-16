import pytest
from unittest.mock import MagicMock
import tempfile
import shutil
from src.actions.search_wipo import execute


@pytest.mark.functional
class TestSearchWipoFunctional:
    """
    Functional tests for the search_wipo action.
    These tests run against the live WIPO website using a real browser.
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
        job_id = "functional-test-keyword-search-wipo"
        params = {
            "queries": [
                ["quantum computing", "qubit", "superconducting"],
                ["blockchain", "decentralized", "finance", "solar"]
            ],
            "max_number_of_patents": 15,
        }
        params = {
            "queries": [
                ["Ultrasound", "Blood-Brain Barrier", "Microbubbles", "Transcranial"],
                ["Ultrasound", "Blood-Brain Barrier", "Microbubbles", "Intra-pulse dosimetry"],
                ["Ultrasound", "Blood-Brain Barrier", "Microbubbles", "Passive cavitation detector"],
                ["Ultrasound", "Blood-Brain Barrier", "Microbubbles", "Neuro-navigation"],
                ["Ultrasound", "Blood-Brain Barrier", "Microbubbles", "Robotic steering"],
                ["Ultrasound", "Blood-Brain Barrier", "Microbubbles", "Acoustic pressure monitoring"],
                ["Ultrasound", "Blood-Brain Barrier", "Microbubbles", "Sonication"],
                ["Ultrasound", "Blood-Brain Barrier", "Microbubbles", "Transcranial", "Intra-pulse dosimetry"],
                ["Ultrasound", "Blood-Brain Barrier", "Microbubbles", "Transcranial", "Passive cavitation detector"],
                ["Ultrasound", "Blood-Brain Barrier", "Microbubbles", "Transcranial", "Neuro-navigation"]
            ],
            "max_number_of_patents": 5
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
        # max_number_of_patents is per query, so total can be up to 15 * 2 = 30
        assert len(patents) <= params["max_number_of_patents"] * len(params["queries"])
