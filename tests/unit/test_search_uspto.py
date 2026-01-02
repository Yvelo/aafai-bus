import pytest
from unittest.mock import MagicMock, patch
import tempfile
import shutil
from src.actions.search_uspto import execute, _build_uspto_url
from selenium.common.exceptions import NoSuchElementException


class TestSearchUsptoUnit:

    @patch('src.actions.search_uspto._setup_driver')
    def test_execute_with_basic_query(self, mock_setup_driver):
        """
        Tests the search_uspto action with a basic query, mocking Selenium.
        """
        mock_driver = MagicMock()
        mock_setup_driver.return_value = mock_driver
        mock_driver.get.return_value = None

        # Mock the next page button to not be found, preventing pagination
        mock_driver.find_element.side_effect = NoSuchElementException

        # --- Mock for Patent 1 ---
        mock_patent1 = MagicMock()
        mock_title1 = MagicMock(text="Test Patent 1")
        mock_link1 = MagicMock()
        mock_link1.find_element.return_value.get_attribute.return_value = "http://example.com/doc/PN123/"
        mock_snippet1 = MagicMock(text="This is a snippet for the first test patent.")

        mock_patent1.find_element.side_effect = [
            mock_title1,
            mock_link1,
            mock_snippet1,
        ]

        # --- Mock for Patent 2 ---
        mock_patent2 = MagicMock()
        mock_title2 = MagicMock(text="Test Patent 2")
        mock_link2 = MagicMock()
        mock_link2.find_element.return_value.get_attribute.return_value = "http://example.com/doc/PN456/"
        mock_snippet2 = MagicMock(text="This is a snippet for the second test patent.")

        mock_patent2.find_element.side_effect = [
            mock_title2,
            mock_link2,
            mock_snippet2,
        ]

        # Configure mock_driver.find_elements to return our mocked patents
        mock_driver.find_elements.return_value = [mock_patent1, mock_patent2]

        job_id = "test-uspto-job-123"
        params = {
            "queries": [["keyword1", "keyword2"]],
        }

        temp_download_dir = tempfile.mkdtemp()
        mock_write_result = MagicMock()

        try:
            execute(job_id, params, temp_download_dir, mock_write_result)

            mock_write_result.assert_called_once()
            _, result = mock_write_result.call_args[0]

            assert result['status'] == 'complete'
            assert len(result['result']['patents']) == 2

            patent1_res = result['result']['patents'][0]
            assert patent1_res['title'] == "Test Patent 1"
            assert patent1_res['patent_number'] == "PN123"
            assert patent1_res['keyword_matches'] == 2

        finally:
            shutil.rmtree(temp_download_dir)

    @patch('src.actions.search_uspto._setup_driver')
    def test_execute_no_results(self, mock_setup_driver):
        """Tests the action when no results are found."""
        mock_driver = MagicMock()
        mock_setup_driver.return_value = mock_driver
        mock_driver.get.return_value = None
        mock_driver.find_elements.return_value = []  # No patents found

        job_id = "test-job-no-results"
        params = {"queries": [["nonexistent query"]]}
        temp_download_dir = tempfile.mkdtemp()
        mock_write_result = MagicMock()

        try:
            execute(job_id, params, temp_download_dir, mock_write_result)

            mock_write_result.assert_called_once()
            _, result = mock_write_result.call_args[0]

            assert result['status'] == 'complete'
            assert len(result['result']['patents']) == 0
            assert result['result']['total_patents_scraped'] == 0
        finally:
            shutil.rmtree(temp_download_dir)

    def test_build_url(self):
        """Tests _build_uspto_url."""
        keywords = ["machine learning", "AI"]
        url = _build_uspto_url(keywords)
        assert "query=%28machine+learning+AND+AI%29" in url
        assert "page=1" in url
        assert "sort=relevance" in url

    def test_build_url_empty_query(self):
        """Tests _build_uspto_url with an empty query."""
        url = _build_uspto_url([])
        assert url == "https://ppubs.uspto.gov/pubwebapp/external/patents/searchResults.html?query=%28%29&page=1&sort=relevance"
