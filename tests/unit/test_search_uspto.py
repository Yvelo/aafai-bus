import pytest
from unittest.mock import MagicMock, patch
import tempfile
import shutil
from src.actions.search_uspto import execute
from selenium.common.exceptions import NoSuchElementException, TimeoutException


class TestSearchUsptoUnit:

    @patch('src.actions.search_uspto.ActionChains')
    @patch('src.actions.search_uspto.WebDriverWait')
    @patch('src.actions.search_uspto._setup_driver')
    def test_execute_with_basic_query(self, mock_setup_driver, mock_wait, mock_action_chains):
        """
        Tests the search_uspto action with a basic query, mocking Selenium.
        """
        mock_driver = MagicMock()
        mock_setup_driver.return_value = mock_driver
        mock_driver.get.return_value = None

        # --- Mock Patent Detail Page Elements ---
        mock_details_container = MagicMock()
        mock_detail_element = MagicMock()
        mock_detail_element.text = "Mocked Detail Text"
        mock_details_container.find_element.return_value = mock_detail_element
        mock_details_container.find_elements.return_value = [mock_detail_element]

        # --- Mock driver's find_element and find_elements ---
        mock_total_patents_element = MagicMock(text="2")
        mock_scrollable_element = MagicMock()

        def driver_find_element_side_effect(by, selector):
            if selector == ".resultNumber":
                return mock_total_patents_element
            if selector == "div.slick-viewport":
                return mock_scrollable_element
            if selector == "div.docMetadata":
                return mock_details_container
            return MagicMock()

        mock_driver.find_element.side_effect = driver_find_element_side_effect

        # --- Mock WebDriverWait and ActionChains ---
        mock_wait_instance = mock_wait.return_value
        mock_search_input = MagicMock()
        mock_abstract_container = MagicMock()
        mock_abstract_paragraph = MagicMock(text="This is the abstract.")
        mock_abstract_container.find_elements.return_value = [mock_abstract_paragraph]

        mock_wait_instance.until.side_effect = [
            # --- Main search ---
            MagicMock(),  # 1. Cookie disclaimer
            MagicMock(),  # 2. Close pop-up
            mock_search_input,  # 3. Search input
            MagicMock(),  # 4. Search button
            MagicMock(),  # 5. Search results loaded
            mock_scrollable_element,  # 6. Scrollable element

            # --- Abstract for Patent 1 ---
            mock_search_input,       # 7. Search input for patent 1
            MagicMock(),             # 8. Search button for patent 1
            TimeoutException(),      # 9. Cookie disclaimer (times out)
            TimeoutException(),      # 10. Close pop-up (times out)
            mock_abstract_container, # 11. Abstract container for patent 1

            # --- Abstract for Patent 2 ---
            mock_search_input,       # 12. Search input for patent 2
            MagicMock(),             # 13. Search button for patent 2
            TimeoutException(),      # 14. Cookie disclaimer (times out)
            TimeoutException(),      # 15. Close pop-up (times out)
            mock_abstract_container, # 16. Abstract container for patent 2
        ]
        mock_actions_instance = mock_action_chains.return_value
        mock_actions_instance.click.return_value = mock_actions_instance

        # --- Mock Patent Elements ---
        def create_patent_mock(patent_number, title):
            mock_patent = MagicMock()
            mock_checkbox = MagicMock()
            mock_checkbox.get_attribute.return_value = patent_number
            mock_title = MagicMock()
            mock_title.get_attribute.return_value = title
            mock_title.text = title

            def find_element_side_effect(by, selector):
                if selector == 'input.row-select-check':
                    return mock_checkbox
                if 'inventionTitle' in selector:
                    return mock_title
                return MagicMock(text="some data")
            mock_patent.find_element.side_effect = find_element_side_effect
            return mock_patent

        mock_patent1 = create_patent_mock("PN123", "Test Patent 1")
        mock_patent2 = create_patent_mock("PN456", "Test Patent 2")

        # Simulate scrolling: first find returns patents, second returns same to stop loop
        mock_driver.find_elements.side_effect = [
            [mock_patent1, mock_patent2],
            [mock_patent1, mock_patent2]
        ]

        # --- Execute Test ---
        job_id = "test-uspto-job-123"
        params = {"queries": [["keyword1", "keyword2"]]}
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
            assert patents[0]['patent_number'] == "PN123"
            assert patents[0]['keyword_matches'] == 2
            assert patents[0]['abstract'] == "This is the abstract."
            assert patents[0]['inventor'] == "Mocked Detail Text" # Check updated data

            assert patents[1]['title'] == "Test Patent 2"
            assert patents[1]['patent_number'] == "PN456"
            assert patents[1]['keyword_matches'] == 2
            assert patents[1]['abstract'] == "This is the abstract."
            assert patents[1]['inventor'] == "Mocked Detail Text" # Check updated data

        finally:
            shutil.rmtree(temp_download_dir)

    @patch('src.actions.search_uspto.ActionChains')
    @patch('src.actions.search_uspto.WebDriverWait')
    @patch('src.actions.search_uspto._setup_driver')
    def test_execute_no_results(self, mock_setup_driver, mock_wait, mock_action_chains):
        """Tests the action when no results are found."""
        mock_driver = MagicMock()
        mock_setup_driver.return_value = mock_driver
        mock_driver.get.return_value = None

        # Make the wait for search results time out
        mock_wait_instance = mock_wait.return_value
        mock_wait_instance.until.side_effect = [
            MagicMock(),  # Cookie disclaimer
            MagicMock(),  # Close pop-up
            MagicMock(),  # Search input
            MagicMock(),  # Search button
            TimeoutException("No results found"),  # Wait for results times out
        ]
        mock_action_chains.return_value.click.return_value.perform.return_value = None

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
