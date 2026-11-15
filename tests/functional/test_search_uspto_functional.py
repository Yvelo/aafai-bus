import pytest
from unittest.mock import MagicMock
import tempfile
import shutil
from src.actions.search_uspto import execute


@pytest.mark.functional
class TestSearchUsptoFunctional:
    """
    Functional tests for the search_uspto action.
    These tests run against the live USPTO website using a real browser.
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
        params = {"queries":[["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer"],["cGAS; cGAMP; STING","mRNA"],["cGAS; cGAMP; STING","LNP; Lipid Nanoparticle"],["cGAS; cGAMP; STING","Innate Immunity; Innate Immune"],["cGAS; cGAMP; STING","Immunotherapy"],["cGAS; cGAMP; STING","Interferon; IFN"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","mRNA"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","LNP; Lipid Nanoparticle"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","Innate Immunity; Innate Immune"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","Immunotherapy"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","Interferon; IFN"],["cGAS; cGAMP; STING","mRNA","LNP; Lipid Nanoparticle"],["cGAS; cGAMP; STING","mRNA","Innate Immunity; Innate Immune"],["cGAS; cGAMP; STING","mRNA","Immunotherapy"],["cGAS; cGAMP; STING","mRNA","Interferon; IFN"],["cGAS; cGAMP; STING","LNP; Lipid Nanoparticle","Innate Immunity; Innate Immune"],["cGAS; cGAMP; STING","LNP; Lipid Nanoparticle","Immunotherapy"],["cGAS; cGAMP; STING","LNP; Lipid Nanoparticle","Interferon; IFN"],["cGAS; cGAMP; STING","Innate Immunity; Innate Immune","Immunotherapy"],["cGAS; cGAMP; STING","Innate Immunity; Innate Immune","Interferon; IFN"],["cGAS; cGAMP; STING","Immunotherapy","Interferon; IFN"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","mRNA","LNP; Lipid Nanoparticle"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","mRNA","Innate Immunity; Innate Immune"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","mRNA","Immunotherapy"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","mRNA","Interferon; IFN"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","LNP; Lipid Nanoparticle","Innate Immunity; Innate Immune"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","LNP; Lipid Nanoparticle","Immunotherapy"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","LNP; Lipid Nanoparticle","Interferon; IFN"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","Innate Immunity; Innate Immune","Immunotherapy"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","Innate Immunity; Innate Immune","Interferon; IFN"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","Immunotherapy","Interferon; IFN"],["cGAS; cGAMP; STING","mRNA","LNP; Lipid Nanoparticle","Innate Immunity; Innate Immune"],["cGAS; cGAMP; STING","mRNA","LNP; Lipid Nanoparticle","Immunotherapy"],["cGAS; cGAMP; STING","mRNA","LNP; Lipid Nanoparticle","Interferon; IFN"],["cGAS; cGAMP; STING","mRNA","Innate Immunity; Innate Immune","Immunotherapy"],["cGAS; cGAMP; STING","mRNA","Innate Immunity; Innate Immune","Interferon; IFN"],["cGAS; cGAMP; STING","mRNA","Immunotherapy","Interferon; IFN"],["cGAS; cGAMP; STING","LNP; Lipid Nanoparticle","Innate Immunity; Innate Immune","Immunotherapy"],["cGAS; cGAMP; STING","LNP; Lipid Nanoparticle","Innate Immunity; Innate Immune","Interferon; IFN"],["cGAS; cGAMP; STING","LNP; Lipid Nanoparticle","Immunotherapy","Interferon; IFN"],["cGAS; cGAMP; STING","Innate Immunity; Innate Immune","Immunotherapy","Interferon; IFN"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","mRNA","LNP; Lipid Nanoparticle","Innate Immunity; Innate Immune"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","mRNA","LNP; Lipid Nanoparticle","Immunotherapy"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","mRNA","LNP; Lipid Nanoparticle","Interferon; IFN"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","mRNA","Innate Immunity; Innate Immune","Immunotherapy"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","mRNA","Innate Immunity; Innate Immune","Interferon; IFN"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","mRNA","Immunotherapy","Interferon; IFN"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","LNP; Lipid Nanoparticle","Innate Immunity; Innate Immune","Immunotherapy"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","LNP; Lipid Nanoparticle","Innate Immunity; Innate Immune","Interferon; IFN"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","LNP; Lipid Nanoparticle","Immunotherapy","Interferon; IFN"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","Innate Immunity; Innate Immune","Immunotherapy","Interferon; IFN"],["cGAS; cGAMP; STING","mRNA","LNP; Lipid Nanoparticle","Innate Immunity; Innate Immune","Immunotherapy"],["cGAS; cGAMP; STING","mRNA","LNP; Lipid Nanoparticle","Innate Immunity; Innate Immune","Interferon; IFN"],["cGAS; cGAMP; STING","mRNA","LNP; Lipid Nanoparticle","Immunotherapy","Interferon; IFN"],["cGAS; cGAMP; STING","mRNA","Innate Immunity; Innate Immune","Immunotherapy","Interferon; IFN"],["cGAS; cGAMP; STING","LNP; Lipid Nanoparticle","Innate Immunity; Innate Immune","Immunotherapy","Interferon; IFN"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","mRNA","LNP; Lipid Nanoparticle","Innate Immunity; Innate Immune","Immunotherapy"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","mRNA","LNP; Lipid Nanoparticle","Innate Immunity; Innate Immune","Interferon; IFN"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","mRNA","LNP; Lipid Nanoparticle","Immunotherapy","Interferon; IFN"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","mRNA","Innate Immunity; Innate Immune","Immunotherapy","Interferon; IFN"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","LNP; Lipid Nanoparticle","Innate Immunity; Innate Immune","Immunotherapy","Interferon; IFN"],["cGAS; cGAMP; STING","mRNA","LNP; Lipid Nanoparticle","Innate Immunity; Innate Immune","Immunotherapy","Interferon; IFN"],["cGAS; cGAMP; STING","Hepatocellular Carcinoma; HCC; Liver Cancer","mRNA","LNP; Lipid Nanoparticle","Innate Immunity; Innate Immune","Immunotherapy","Interferon; IFN"]],"max_number_of_patents":100}
        mock_write_result = MagicMock()

        execute(job_id, params, temp_dir, mock_write_result)

        mock_write_result.assert_called_once()
        _, result = mock_write_result.call_args[0]

        assert result['job_id'] == job_id
        assert result['status'] == 'Completed'
        assert 'error' not in result

        patents = result['result']['patents']
        assert len(patents) > 0
        assert len(patents) <= 10000
