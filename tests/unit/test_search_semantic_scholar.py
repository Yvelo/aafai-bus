import pytest
from unittest.mock import MagicMock, patch
import tempfile
import shutil
from src.actions.search_semantic_scholar import execute, _build_semantic_scholar_url
from selenium.common.exceptions import NoSuchElementException


@patch('src.actions.search_semantic_scholar._get_total_estimated_results', return_value=50)
class TestSearchSemanticScholarUnit:

    @patch('src.actions.search_semantic_scholar._get_author_details')
    @patch('src.actions.search_semantic_scholar._setup_driver')
    def test_execute_with_basic_query(self, mock_setup_driver, mock_get_author_details, mock_get_total_estimated_results):
        """
        Tests the search_semantic_scholar action with a basic query, mocking Selenium.
        """
        mock_driver = MagicMock()
        mock_setup_driver.return_value = mock_driver
        mock_driver.get.return_value = None

        # Mock the next page button to not be found, preventing pagination
        mock_driver.find_element.side_effect = NoSuchElementException

        # Mock window handles for _get_author_details
        mock_driver.current_window_handle = "main_window"
        mock_driver.window_handles = ["main_window", "new_window"]

        # Mock _get_author_details
        mock_get_author_details.return_value = {
            "affiliation": "Test University",
            "total_citations": "5000",
            "h_index": "42"
        }

        # --- Mock for Article 1 ---
        mock_article1 = MagicMock()
        mock_title1 = MagicMock(text="Test Title 1", get_attribute=lambda x: "http://example.com/article1")
        mock_snippet1 = MagicMock(text="This is a snippet for the first test article.")
        mock_author1 = MagicMock(text="Author A", get_attribute=lambda x: "http://example.com/authorA")
        mock_pdf1 = MagicMock(get_attribute=lambda x: "http://example.com/pdf1.pdf")
        mock_venue1 = MagicMock(text="Journal of Tests,")
        mock_pubdate1 = MagicMock(text="2023")
        mock_citations1 = MagicMock(text="123")

        mock_article1.find_element.side_effect = [
            mock_title1,        # title
            mock_snippet1,      # snippet
            mock_venue1,        # venue
            mock_pubdate1,      # pubdate
            mock_pdf1,          # pdf link
            mock_citations1     # citations
        ]
        mock_article1.find_elements.return_value = [mock_author1]  # author-list

        # --- Mock for Article 2 ---
        mock_article2 = MagicMock()
        mock_title2 = MagicMock(text="Test Title 2", get_attribute=lambda x: "http://example.com/article2")
        mock_snippet2 = MagicMock(text="This is a snippet for the second test article.")
        mock_author2 = MagicMock(text="Author B", get_attribute=lambda x: "http://example.com/authorB")
        mock_venue2 = MagicMock(text="Conference of Mocks")
        mock_pubdate2 = MagicMock(text="2022")
        mock_citations2 = MagicMock(text="456")

        mock_article2.find_element.side_effect = [
            mock_title2,
            mock_snippet2,
            mock_venue2,
            mock_pubdate2,
            # Simulate NoSuchElementException for PDF link
            NoSuchElementException,
            mock_citations2
        ]
        mock_article2.find_elements.return_value = [mock_author2]

        # Configure mock_driver.find_elements to return our mocked articles
        mock_driver.find_elements.return_value = [mock_article1, mock_article2]

        job_id = "test-semantic-scholar-job-123"
        params = {
            "query": {"all_words": "test query"},
            "fetch_author_details": "all",
        }

        temp_download_dir = tempfile.mkdtemp()
        mock_write_result = MagicMock()

        try:
            execute(job_id, params, temp_download_dir, mock_write_result)

            mock_write_result.assert_called_once()
            _, result = mock_write_result.call_args[0]

            assert result['status'] == 'complete'
            assert len(result['result']['articles']) == 2

            # Results are sorted by citation count (desc), so article 2 should be first.
            article2_res = result['result']['articles'][0]
            assert article2_res['title'] == "Test Title 2"
            assert article2_res['pdf_link'] is None
            assert article2_res['citations'] == 456

            article1_res = result['result']['articles'][1]
            assert article1_res['title'] == "Test Title 1"
            assert article1_res['link'] == "http://example.com/article1"
            assert article1_res['snippet'] == "This is a snippet for the first test article."
            assert article1_res['pdf_link'] == "http://example.com/pdf1.pdf"
            assert article1_res['publication_details'] == "Journal of Tests, 2023"
            assert article1_res['citations'] == 123
            assert len(article1_res['authors']) == 1
            assert article1_res['authors'][0]['name'] == "Author A"
            assert article1_res['authors'][0]['author_url'] == "http://example.com/authorA"
            assert article1_res['authors'][0]['affiliation'] == "Test University"
            assert article1_res['authors'][0]['total_citations'] == "5000"
            assert article1_res['authors'][0]['h_index'] == "42"

        finally:
            shutil.rmtree(temp_download_dir)

    @patch('src.actions.search_semantic_scholar._setup_driver')
    def test_execute_no_results(self, mock_setup_driver, mock_get_total_estimated_results):
        """Tests the action when no results are found."""
        mock_driver = MagicMock()
        mock_setup_driver.return_value = mock_driver
        mock_driver.get.return_value = None
        mock_driver.find_elements.return_value = []  # No articles found

        job_id = "test-job-no-results"
        params = {"query": {"all_words": "nonexistent query"}}
        temp_download_dir = tempfile.mkdtemp()
        mock_write_result = MagicMock()

        try:
            execute(job_id, params, temp_download_dir, mock_write_result)

            mock_write_result.assert_called_once()
            _, result = mock_write_result.call_args[0]

            assert result['status'] == 'complete'
            assert len(result['result']['articles']) == 0
            assert result['result']['total_results_scraped'] == 0
        finally:
            shutil.rmtree(temp_download_dir)

    def test_build_url_all_params(self, mock_get_total_estimated_results):
        """Tests _build_semantic_scholar_url with all possible parameters."""
        query_params = {
            "all_words": "machine learning",
            "exact_phrase": "reinforcement learning",
            "without_words": "robotics",
            "author": "Geoffrey Hinton",
            "date_range": {"start_year": 2020, "end_year": 2023},
        }
        url = _build_semantic_scholar_url(query_params)
        assert "q=machine+learning+%22reinforcement+learning%22+Geoffrey+Hinton+-robotics" in url
        assert "author=" not in url
        assert "year=2020-2023" in url

    def test_build_url_only_author(self, mock_get_total_estimated_results):
        """Tests _build_semantic_scholar_url with only an author."""
        query_params = {"author": "Yann LeCun"}
        url = _build_semantic_scholar_url(query_params)
        assert "q=Yann+LeCun" in url
        assert "author=" not in url

    def test_build_url_empty_query(self, mock_get_total_estimated_results):
        """Tests _build_semantic_scholar_url with an empty query."""
        url = _build_semantic_scholar_url({})
        assert url == "https://www.semanticscholar.org/search?q=&sort=relevance"
