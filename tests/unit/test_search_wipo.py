import pytest
from unittest.mock import MagicMock, patch
import tempfile
import shutil
from src.actions.search_wipo import execute
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By


class TestSearchWipoUnit:

    def create_text_mock(self, text_value):
        """
        Helper to create a mock with a .text attribute that holds a string.
        
        IMPORTANT: MagicMock(text="foo") does NOT work as expected. It creates a mock
        with the *name* 'text', but mock.text returns another MagicMock, leading
        to JSON serialization errors. The correct way is to assign the attribute
        after creation.
        """
        mock = MagicMock()
        mock.text = text_value
        return mock

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
        mock_total_patents_element = self.create_text_mock("2 results")

        def driver_find_element_side_effect(by, selector):
            if by == By.ID and selector == "psCaptchaForm":
                raise NoSuchElementException
            elif by == By.CSS_SELECTOR:
                if selector == "span.results-count":
                    return mock_total_patents_element
                if selector == "div.patent-abstract":
                    return self.create_text_mock("This is the abstract.")
            elif by == By.XPATH:
                if "Application Date" in selector or "Filing Date" in selector:
                    return self.create_text_mock("2023-01-01")
                if "Application Number" in selector or "Publication Number" in selector:
                    return self.create_text_mock("APP123")
                if "Inventors" in selector:
                    return self.create_text_mock("Test Inventor")
                if "Applicants" in selector:
                    return self.create_text_mock("Test Applicant")
                raise NoSuchElementException
            raise NoSuchElementException(f"Unhandled driver.find_element call: by={by}, selector='{selector}'")

        mock_driver.find_element.side_effect = driver_find_element_side_effect

        # --- Mock WebDriverWait ---
        mock_wait_instance = mock_wait.return_value
        mock_search_input = MagicMock()

        mock_wait_instance.until.side_effect = [
            MagicMock(),  # 1. Cookie banner
            mock_search_input, # 2. Search input
            MagicMock(), # 3. Search button
            MagicMock(), # 4. results-container
            mock_total_patents_element, # 5. results-count
            MagicMock(), # 6. patent result rows (tr[data-rk])
            MagicMock(), # 7. pagination spinner invisibility
            TimeoutException(), # 8. next button (to break the pagination loop)
            MagicMock(), # 9. patent detail page 1
            MagicMock(), # 10. patent detail page 2
        ]

        # --- Mock Patent Elements ---
        def create_patent_mock(patent_number, title):
            mock_patent = MagicMock()
            mock_patent.get_attribute.return_value = patent_number

            def find_element_side_effect(by, selector):
                if by == By.CSS_SELECTOR:
                    if selector == 'span.ps-patent-result--title--title':
                        return self.create_text_mock(title)
                    if selector == 'div.ps-patent-result--title--ctr-pubdate':
                        return self.create_text_mock("US - 15.02.2023")
                    if selector == 'span.ps-patent-result--inventor':
                        return self.create_text_mock("Initial Inventor")
                    if selector == 'span.ps-patent-result--applicant':
                        return self.create_text_mock("Initial Applicant")
                raise NoSuchElementException(f"Unhandled mock_patent.find_element: by={by}, sel='{selector}'")
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
            # The detail page mock for 'Publication Date' raises an exception,
            # so the value from the results page should be preserved.
            assert patents[0]['date_published'] == "15.02.2023"
            assert patents[0]['inventor'] == "Test Inventor"
            assert patents[0]['assignee'] == "Test Applicant"

        finally:
            shutil.rmtree(temp_download_dir)

    @patch('src.actions.search_wipo.WebDriverWait')
    @patch('src.actions.search_wipo._setup_driver')
    def test_execute_no_results(self, mock_setup_driver, mock_wait):
        """Tests the action when no results are found."""
        mock_driver = MagicMock()
        mock_setup_driver.return_value = mock_driver
        mock_driver.get.return_value = None

        mock_total_patents_element = self.create_text_mock("0 results")

        def find_element_side_effect(by, selector):
            if by == By.ID and selector == "psCaptchaForm":
                raise NoSuchElementException
            if by == By.CSS_SELECTOR and selector == "span.results-count":
                return mock_total_patents_element
            raise NoSuchElementException(f"Unhandled driver.find_element call: by={by}, selector='{selector}'")

        mock_driver.find_element.side_effect = find_element_side_effect

        mock_wait_instance = mock_wait.return_value
        # In the no-results case, the total patents element is waited for directly
        mock_wait_instance.until.side_effect = [
            MagicMock(),  # Cookie banner
            MagicMock(),  # Search input
            MagicMock(),  # Search button
            MagicMock(),  # results-container
            mock_total_patents_element, # total patents element
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