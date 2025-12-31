import pytest
from unittest.mock import MagicMock
import tempfile
import shutil
from src.actions.search_google_scholar import execute


@pytest.mark.functional
class TestSearchGoogleScholarFunctional:
    """
    Functional tests for the search_google_scholar action.
    These tests run against the live Google Scholar website using a real browser.
    They are marked as 'functional' and may be slower to run.
    """

    @pytest.fixture
    def temp_dir(self):
        """
        Pytest fixture to create and clean up a temporary directory for tests.
        """
        temp_download_dir = tempfile.mkdtemp()
        try:
            yield temp_download_dir
        finally:
            shutil.rmtree(temp_download_dir)

    def test_search_by_author_name(self, temp_dir):
        """
        Tests a real search for an author to verify the scraper can handle
        a live author query. We limit the results to keep the test quick.
        """
        job_id = "functional-test-author-search"
        params = {
            "query": {
                "author": "Olivier Lantz"
            },
            "max_number_of_articles": 5,
            "fetch_author_details": "none",  # Keep test fast, don't fetch details
        }
        mock_write_result = MagicMock()

        execute(job_id, params, temp_dir, mock_write_result)

        mock_write_result.assert_called_once()
        _, result = mock_write_result.call_args[0]

        assert result['job_id'] == job_id
        assert result['status'] == 'complete'
        assert 'error' not in result

        articles = result['result']['articles']
        assert len(articles) > 0
        assert len(articles) <= 5

        # Check that the author appears in the results
        found_author = any("Lantz" in article['raw_author_line'] for article in articles)
        assert found_author, "Expected to find 'Lantz' in the author line of the results"

    def test_search_by_keyword(self, temp_dir):
        """
        Tests a real search for a keyword to verify the scraper can handle
        a live keyword query. We limit the results to keep the test quick.
        """
        job_id = "functional-test-keyword-search"
        params = {
            "query": {
                "all_words": "Neoantigen"
            },
            "max_number_of_articles": 5,
            "fetch_author_details": "none",
        }
        mock_write_result = MagicMock()

        execute(job_id, params, temp_dir, mock_write_result)

        mock_write_result.assert_called_once()
        _, result = mock_write_result.call_args[0]

        assert result['job_id'] == job_id
        assert result['status'] == 'complete'
        assert 'error' not in result

        articles = result['result']['articles']
        assert len(articles) > 0
        assert len(articles) <= 5

        # Check that the keyword appears in the results' titles or snippets
        found_keyword = any(
            "neoantigen" in article['title'].lower() or "neoantigen" in article['snippet'].lower()
            for article in articles
        )
        assert found_keyword, "Expected to find 'neoantigen' in the title or snippet of the results"
