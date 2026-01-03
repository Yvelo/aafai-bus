import pytest
from unittest.mock import MagicMock, patch
import tempfile
import shutil
from src.actions.search_espacenet import execute
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By


class TestSearchEspacenetUnit:

    @patch('src.actions.search_espacenet.WebDriverWait')
    @patch('time.sleep', return_value=None)
    @patch('src.actions.search_espacenet._setup_driver')
    def test_execute_with_basic_query(self, mock_setup_driver, mock_sleep, mock_wait):
        """
        Tests the search_espacenet action with a basic query, mocking Selenium.
        """
        mock_driver = MagicMock()
        mock_setup_driver.return_value = mock_driver
        mock_driver.get.return_value = None
        
        temp_dir_for_mock = tempfile.mkdtemp()
        mock_driver.temp_dir = temp_dir_for_mock

        # --- Mocks for driver-level elements ---
        mock_search_input = MagicMock()
        mock_search_button = MagicMock()
        mock_scrollable_div = MagicMock()
        mock_first_result_for_wait = MagicMock()

        # --- Mock WebDriverWait ---
        mock_wait_instance = mock_wait.return_value
        mock_wait_instance.until.side_effect = [
            mock_search_input,
            mock_search_button,
            mock_first_result_for_wait,
            mock_scrollable_div,
        ]

        # --- Mock for Patent 1 ---
        mock_patent1 = MagicMock()
        mock_title1 = MagicMock(text="Test Patent 1")
        mock_subtitle1_container = MagicMock()
        mock_subtitle1_span = MagicMock(text="PN123")
        mock_subtitle1_container.find_element.return_value = mock_subtitle1_span
        mock_abstract1 = MagicMock(text="This is a snippet for the first test patent.")

        def patent1_find_element(by, selector):
            if selector == 'span[class*="item__content--title"]':
                return mock_title1
            if selector == 'div[class*="item__content--subtitle"]':
                return mock_subtitle1_container
            if selector == 'div[class*="item__content-abstract"]':
                return mock_abstract1
            return MagicMock(text=None)
        mock_patent1.find_element.side_effect = patent1_find_element

        # --- Mock for Patent 2 ---
        mock_patent2 = MagicMock()
        mock_title2 = MagicMock(text="Test Patent 2")
        mock_subtitle2_container = MagicMock()
        mock_subtitle2_span = MagicMock(text="PN456")
        mock_subtitle2_container.find_element.return_value = mock_subtitle2_span
        mock_abstract2 = MagicMock(text="This is a snippet for the second test patent.")

        def patent2_find_element(by, selector):
            if selector == 'span[class*="item__content--title"]':
                return mock_title2
            if selector == 'div[class*="item__content--subtitle"]':
                return mock_subtitle2_container
            if selector == 'div[class*="item__content-abstract"]':
                return mock_abstract2
            return MagicMock(text=None)
        mock_patent2.find_element.side_effect = patent2_find_element

        # Configure mock_driver.find_elements to return patents on the first call, then empty
        mock_driver.find_elements.side_effect = [
            [mock_patent1, mock_patent2],
            [mock_patent1, mock_patent2]  # Second call to stop the loop
        ]

        job_id = "test-espacenet-job-123"
        params = {"queries": [["keyword1", "keyword2"]]}
        temp_download_dir = tempfile.mkdtemp()
        mock_write_result = MagicMock()

        try:
            execute(job_id, params, temp_download_dir, mock_write_result)

            mock_write_result.assert_called_once()
            _, result = mock_write_result.call_args[0]

            assert result['status'] == 'complete'
            assert len(result['result']['patents']) == 2

            patents = sorted(result['result']['patents'], key=lambda p: p['patent_number'])
            assert patents[0]['title'] == "Test Patent 1"
            assert patents[0]['patent_number'] == "PN123"
            assert patents[0]['keyword_matches'] == 2
            assert patents[1]['title'] == "Test Patent 2"
            assert patents[1]['patent_number'] == "PN456"

        finally:
            shutil.rmtree(temp_download_dir)

    @patch('src.actions.search_espacenet.WebDriverWait')
    @patch('time.sleep', return_value=None)
    @patch('src.actions.search_espacenet._setup_driver')
    def test_execute_no_results(self, mock_setup_driver, mock_sleep, mock_wait):
        """Tests the action when no results are found."""
        mock_driver = MagicMock()
        mock_setup_driver.return_value = mock_driver
        mock_driver.get.return_value = None
        mock_driver.find_elements.return_value = []

        job_id = "test-job-no-results"
        params = {"queries": [["nonexistent query"]]}
        temp_download_dir = tempfile.mkdtemp()
        mock_write_result = MagicMock()

        # --- Mocks for driver-level elements ---
        mock_search_input = MagicMock()
        mock_search_button = MagicMock()

        # --- Mock WebDriverWait ---
        mock_wait_instance = mock_wait.return_value
        mock_wait_instance.until.side_effect = [
            mock_search_input,
            mock_search_button,
            TimeoutException("No results found")
        ]

        try:
            execute(job_id, params, temp_download_dir, mock_write_result)

            mock_write_result.assert_called_once()
            _, result = mock_write_result.call_args[0]

            assert result['status'] == 'complete'
            assert len(result['result']['patents']) == 0
            assert result['result']['total_patents_scraped'] == 0
        finally:
            shutil.rmtree(temp_download_dir)
