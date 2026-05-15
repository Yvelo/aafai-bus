import pytest
from unittest.mock import MagicMock, patch
import tempfile
import shutil
from src.actions.search_wipo import execute
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By


class TestSearchWipoUnit:

    @patch('src.actions.search_wipo.WebDriverWait')
    @patch('src.actions.search_wipo._setup_driver')
    def test_execute_with_basic_query(self, mock_setup_driver, mock_wait):
        """
        Tests the search_wipo action with a basic query, mocking Selenium.
        """
        mock_driver = MagicMock()
        mock_setup_driver.return_value = mock_driver
        mock_driver.get.return_value = None

        # --- Mock driver's find_element and find_elements ---
        mock_total_patents_element = MagicMock(text="2 results")
        
        def driver_find_element_side_effect(by, selector):
            if by == By.ID and selector == "psCaptchaForm":
                raise NoSuchElementException
            if selector == "span.results-count":
                return mock_total_patents_element
            if selector == "div.patent-abstract":
                return MagicMock(text="This is the abstract.")
            if by == By.XPATH:
                if "Application Date" in selector or "Filing Date" in selector:
                    return MagicMock(text="2023-01-01")
                if "Application Number" in selector or "Publication Number" in selector:
                    return MagicMock(text="APP123")
                if "Inventors" in selector:
                    return MagicMock(text="Test Inventor")
                if "Applicants" in selector:
                    return MagicMock(text="Test Applicant")
            return MagicMock()

        mock_driver.find_element.side_effect = driver_find_element_side_effect

        # --- Mock WebDriverWait ---
        mock_wait_instance = mock_wait.return_value
        mock_search_input = MagicMock()
        
        mock_wait_instance.until.side_effect = [
            MagicMock(),  # Cookie banner
            mock_search_input,
            MagicMock(), # Search button
            MagicMock(), # results-container
            mock_total_patents_element,
            MagicMock(), # patent result rows
            MagicMock(), # patent detail page
            MagicMock(), # patent detail page
        ]

        # --- Mock Patent Elements ---
        def create_patent_mock(patent_number, title):
            mock_patent = MagicMock()
            mock_patent.get_attribute.return_value = patent_number
            
            def find_element_side_effect(by, selector):
                if selector == 'span.ps-patent-result--title--title':
                    return MagicMock(text=title)
                return MagicMock(text="some data")
            mock_patent.find_element.side_effect = find_element_side_effect
            return mock_patent

        mock_patent1 = create_patent_mock("WO2023000001", "Test Patent 1")
        mock_patent2 = create_patent_mock("WO2023000002", "Test Patent 2")

        mock_driver.find_elements.side_effect = [
            [mock_patent1, mock_patent2],
            [] # Stop pagination
        ]

        # --- Execute Test ---
        job_id = "test-wipo-job-123"
        params = {"queries": [["keyword1", "keyword2"]], "max_number_of_patents": 10}
        temp_download_dir = tempfile.mkdtemp()
        mock_write_result = MagicMock()

        try:
            execute(job_id, params, temp_download_dir, mock_write_result)

            # --- Assertions ---
            mock_write_result.assert_called_once()
            _, result = mock_write_result.call_args[0]

            assert result['status'] == 'complete'
            assert len(result['result']['patents']) == 2

            patents = sorted(result['result']['patents'], key=lambda p: p['patent_number'])
            
            assert patents[0]['title'] == "Test Patent 1"
            assert patents[0]['patent_number'] == "WO2023000001"
            assert patents[0]['abstract'] == "This is the abstract."
            assert patents[0]['filing_date'] == "2023-01-01"
            assert patents[0]['application_number'] == "APP123"

        finally:
            shutil.rmtree(temp_download_dir)

    @patch('src.actions.search_wipo.WebDriverWait')
    @patch('src.actions.search_wipo._setup_driver')
    def test_execute_no_results(self, mock_setup_driver, mock_wait):
        """Tests the action when no results are found."""
        mock_driver = MagicMock()
        mock_setup_driver.return_value = mock_driver
        mock_driver.get.return_value = None

        def find_element_side_effect(by, selector):
            if by == By.ID and selector == "psCaptchaForm":
                raise NoSuchElementException
            if selector == "span.results-count":
                return MagicMock(text="0 results")
            return MagicMock()
        
        mock_driver.find_element.side_effect = find_element_side_effect

        mock_wait_instance = mock_wait.return_value
        mock_wait_instance.until.side_effect = [
            MagicMock(),  # Cookie banner
            MagicMock(),  # Search input
            MagicMock(),  # Search button
            MagicMock(),  # results-container
            MagicMock(text="0 results"), # total patents element
        ]

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
