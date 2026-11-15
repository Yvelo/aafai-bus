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
            "queries": [["cGAS", "STING"], ["cGAS", "cGAMP"], ["cGAS", "mRNA"], ["cGAS", "lipid nanoparticle; LNP"],
                         ["cGAS", "nucleoside-modified mRNA"], ["cGAS", "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "STING", "cGAMP"], ["cGAS", "STING", "mRNA"],
                         ["cGAS", "STING", "lipid nanoparticle; LNP"], ["cGAS", "STING", "nucleoside-modified mRNA"],
                         ["cGAS", "STING", "constitutively active cGAS; auto-active cGAS"], ["cGAS", "cGAMP", "mRNA"],
                         ["cGAS", "cGAMP", "lipid nanoparticle; LNP"], ["cGAS", "cGAMP", "nucleoside-modified mRNA"],
                         ["cGAS", "cGAMP", "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "mRNA", "lipid nanoparticle; LNP"], ["cGAS", "mRNA", "nucleoside-modified mRNA"],
                         ["cGAS", "mRNA", "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "lipid nanoparticle; LNP", "nucleoside-modified mRNA"],
                         ["cGAS", "lipid nanoparticle; LNP", "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "nucleoside-modified mRNA", "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "STING", "cGAMP", "mRNA"], ["cGAS", "STING", "cGAMP", "lipid nanoparticle; LNP"],
                         ["cGAS", "STING", "cGAMP", "nucleoside-modified mRNA"],
                         ["cGAS", "STING", "cGAMP", "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "STING", "mRNA", "lipid nanoparticle; LNP"],
                         ["cGAS", "STING", "mRNA", "nucleoside-modified mRNA"],
                         ["cGAS", "STING", "mRNA", "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "STING", "lipid nanoparticle; LNP", "nucleoside-modified mRNA"],
                         ["cGAS", "STING", "lipid nanoparticle; LNP", "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "STING", "nucleoside-modified mRNA", "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "cGAMP", "mRNA", "lipid nanoparticle; LNP"],
                         ["cGAS", "cGAMP", "mRNA", "nucleoside-modified mRNA"],
                         ["cGAS", "cGAMP", "mRNA", "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "cGAMP", "lipid nanoparticle; LNP", "nucleoside-modified mRNA"],
                         ["cGAS", "cGAMP", "lipid nanoparticle; LNP", "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "cGAMP", "nucleoside-modified mRNA", "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "mRNA", "lipid nanoparticle; LNP", "nucleoside-modified mRNA"],
                         ["cGAS", "mRNA", "lipid nanoparticle; LNP", "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "mRNA", "nucleoside-modified mRNA", "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "lipid nanoparticle; LNP", "nucleoside-modified mRNA",
                          "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "STING", "cGAMP", "mRNA", "lipid nanoparticle; LNP"],
                         ["cGAS", "STING", "cGAMP", "mRNA", "nucleoside-modified mRNA"],
                         ["cGAS", "STING", "cGAMP", "mRNA", "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "STING", "cGAMP", "lipid nanoparticle; LNP", "nucleoside-modified mRNA"],
                         ["cGAS", "STING", "cGAMP", "lipid nanoparticle; LNP",
                          "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "STING", "cGAMP", "nucleoside-modified mRNA",
                          "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "STING", "mRNA", "lipid nanoparticle; LNP", "nucleoside-modified mRNA"],
                         ["cGAS", "STING", "mRNA", "lipid nanoparticle; LNP",
                          "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "STING", "mRNA", "nucleoside-modified mRNA",
                          "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "STING", "lipid nanoparticle; LNP", "nucleoside-modified mRNA",
                          "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "cGAMP", "mRNA", "lipid nanoparticle; LNP", "nucleoside-modified mRNA"],
                         ["cGAS", "cGAMP", "mRNA", "lipid nanoparticle; LNP",
                          "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "cGAMP", "mRNA", "nucleoside-modified mRNA",
                          "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "cGAMP", "lipid nanoparticle; LNP", "nucleoside-modified mRNA",
                          "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "mRNA", "lipid nanoparticle; LNP", "nucleoside-modified mRNA",
                          "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "STING", "cGAMP", "mRNA", "lipid nanoparticle; LNP", "nucleoside-modified mRNA"],
                         ["cGAS", "STING", "cGAMP", "mRNA", "lipid nanoparticle; LNP",
                          "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "STING", "cGAMP", "mRNA", "nucleoside-modified mRNA",
                          "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "STING", "cGAMP", "lipid nanoparticle; LNP", "nucleoside-modified mRNA",
                          "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "STING", "mRNA", "lipid nanoparticle; LNP", "nucleoside-modified mRNA",
                          "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "cGAMP", "mRNA", "lipid nanoparticle; LNP", "nucleoside-modified mRNA",
                          "constitutively active cGAS; auto-active cGAS"],
                         ["cGAS", "STING", "cGAMP", "mRNA", "lipid nanoparticle; LNP", "nucleoside-modified mRNA",
                          "constitutively active cGAS; auto-active cGAS"]], "max_number_of_patents": 100
        }
        params = {
            "queries": [["cGAS", "STING"], ["cGAS", "cGAMP"], ["cGAS", "mRNA"], ["cGAS", "lipid nanoparticle; LNP"]], "max_number_of_patents": 100
        }

        mock_write_result = MagicMock()

        execute(job_id, params, temp_dir, mock_write_result)

        mock_write_result.assert_called_once()
        _, result = mock_write_result.call_args[0]

        assert result['job_id'] == job_id
        assert result['status'] == 'Completed'
        assert 'error' not in result

        patents = result['result']['patents']
        assert len(patents) > 0
        # max_number_of_patents is per query, so total can be up to 15 * 2 = 30
        assert len(patents) <= params["max_number_of_patents"] * len(params["queries"])
