import pytest
from unittest.mock import MagicMock, patch
import tempfile
import shutil
import json
from src.actions.search_google_scholar import execute, _build_scholar_url, DEFAULT_MAX_NUMBER_OF_ARTICLES


# Mock the _get_total_estimated_results to return a consistent value for tests
@patch('src.actions.search_google_scholar._get_total_estimated_results', return_value=100)
class TestSearchGoogleScholarUnit:

    @patch('src.actions.search_google_scholar._get_scholar_profile_details')
    @patch('src.actions.search_google_scholar._setup_driver')
    def test_execute_with_basic_query(self, mock_setup_driver, mock_get_scholar_profile_details,
                                      mock_get_total_estimated_results):
        """
        Tests the search_google_scholar action with a basic query.
        This test focuses on the overall flow and result structure,
        mocking the actual Selenium interactions.
        """
        # Setup mock driver
        mock_driver = MagicMock()
        mock_setup_driver.return_value = mock_driver

        # Simulate driver.get() doesn't return anything
        mock_driver.get.return_value = None

        # Mock window handles for _get_scholar_profile_details
        mock_driver.current_window_handle = "main_window"
        mock_driver.window_handles = ["main_window", "new_window"]
        mock_driver.execute_script.return_value = None
        mock_driver.switch_to.window.return_value = None
        mock_driver.close.return_value = None

        # Mock _get_scholar_profile_details
        mock_get_scholar_profile_details.side_effect = [
            {"scholar_org": "Org A", "scholar_citations": "100"},  # For USER_A
            {"scholar_org": "Org B", "scholar_citations": "200"},  # For USER_B
        ]

        # Mock for author_info_container for article 1
        mock_author_info_container1 = MagicMock()
        mock_author_info_container1.text = "Author A - Publication X, 2023"  # The full text of the container

        # Mock for author links within the container
        mock_author_link1 = MagicMock(text="Author A",
                                      get_attribute=lambda x: "https://scholar.google.com/citations?user=USER_A&hl=en")

        # Mock for publication details span within the container
        mock_publication_span1 = MagicMock(text="Publication X, 2023")

        # Configure find_elements for mock_author_info_container1
        # The order of calls to find_elements matters: first for author links, then for publication span
        mock_author_info_container1.find_elements.side_effect = [
            [mock_author_link1],  # First call: 'a[href*="citations?user="]'
            [mock_publication_span1],  # Second call: 'span.gs_a_ext'
        ]

        # --- Mock for Article 1 ---
        mock_article1 = MagicMock()
        mock_article1.find_element.side_effect = [
            MagicMock(text="Test Title 1", get_attribute=lambda x: "http://example.com/article1"),  # h3.gs_rt a
            MagicMock(text="Test Snippet 1"),  # div.gs_rs
            mock_author_info_container1,  # div.gs_a
        ]
        mock_article1.find_elements.return_value = [
            MagicMock(get_attribute=lambda x: "http://example.com/pdf1.pdf")  # div.gs_ggs.gs_scl a
        ]

        # Mock for author_info_container for article 2
        mock_author_info_container2 = MagicMock()
        mock_author_info_container2.text = "Author B - Publication Y, 2022"  # Full text

        # Mock for author links within the container
        mock_author_link2 = MagicMock(text="Author B",
                                      get_attribute=lambda x: "https://scholar.google.com/citations?user=USER_B&hl=en")

        # Mock for publication details span within the container
        mock_publication_span2 = MagicMock(text="Publication Y, 2022")

        # Configure find_elements for mock_author_info_container2
        mock_author_info_container2.find_elements.side_effect = [
            [mock_author_link2],  # First call: 'a[href*="citations?user="]'
            [mock_publication_span2],  # Second call: 'span.gs_a_ext'
        ]

        # --- Mock for Article 2 ---
        mock_article2 = MagicMock()
        mock_article2.find_element.side_effect = [
            MagicMock(text="Test Title 2", get_attribute=lambda x: "http://example.com/article2"),  # title_element
            MagicMock(text="Test Snippet 2"),  # snippet_element
            mock_author_info_container2,  # author_info_element
        ]
        mock_article2.find_elements.return_value = []  # No PDF for second article

        # Configure mock_driver.find_elements to return our mocked articles
        # This is for the initial call to find 'div.gs_r.gs_or.gs_scl'
        mock_driver.find_elements.return_value = [mock_article1, mock_article2]

        job_id = "test-scholar-job-123"
        params = {
            "query": {
                "all_words": "test query",
                "date_range": {"start_year": 2020, "end_year": 2023}
            },
            "fetch_author_details": "all",
        }

        # Create a temporary directory for the test
        temp_download_dir = tempfile.mkdtemp()

        mock_write_result = MagicMock()

        try:
            execute(job_id, params, temp_download_dir, mock_write_result)

            # Assert that write_result_to_outbound was called once
            mock_write_result.assert_called_once()

            # Get the result passed to the mock function
            _, result = mock_write_result.call_args[0]

            assert result['job_id'] == job_id
            assert result['status'] == 'complete'
            assert 'result' in result
            assert 'articles' in result['result']
            assert len(result['result']['articles']) == 2  # Expecting 2 mocked articles

            # Assert the new structure
            article1 = result['result']['articles'][0]
            assert article1['title'] == "Test Title 1"
            assert article1['link'] == "http://example.com/article1"
            assert article1['snippet'] == "Test Snippet 1"
            assert article1['pdf_link'] == "http://example.com/pdf1.pdf"
            assert len(article1['authors']) == 1
            assert article1['authors'][0]['name'] == "Author A"
            assert article1['authors'][0]['scholar_user'] == "USER_A"
            assert article1['authors'][0]['scholar_org'] == "Org A"
            assert article1['authors'][0]['scholar_citations'] == "100"
            assert article1['publication_details'] == "Publication X, 2023"

            article2 = result['result']['articles'][1]
            assert article2['title'] == "Test Title 2"
            assert article2['link'] == "http://example.com/article2"
            assert article2['snippet'] == "Test Snippet 2"
            assert article2['pdf_link'] is None
            assert len(article2['authors']) == 1
            assert article2['authors'][0]['name'] == "Author B"
            assert article2['authors'][0]['scholar_user'] == "USER_B"
            assert article2['authors'][0]['scholar_org'] == "Org B"
            assert article2['authors'][0]['scholar_citations'] == "200"
            assert article2['publication_details'] == "Publication Y, 2022"

        finally:
            shutil.rmtree(temp_download_dir)

    @patch('src.actions.search_google_scholar._get_scholar_profile_details')
    @patch('src.actions.search_google_scholar._setup_driver')
    def test_execute_with_no_results(self, mock_setup_driver, mock_get_scholar_profile_details,
                                     mock_get_total_estimated_results):
        """
        Tests the search_google_scholar action when no results are found.
        """
        mock_driver = MagicMock()
        mock_setup_driver.return_value = mock_driver
        mock_driver.get.return_value = None
        mock_driver.find_elements.return_value = []  # No articles found

        # Mock window handles for _get_scholar_profile_details (even if not called, good practice)
        mock_driver.current_window_handle = "main_window"
        mock_driver.window_handles = ["main_window", "new_window"]
        mock_driver.execute_script.return_value = None
        mock_driver.switch_to.window.return_value = None
        mock_driver.close.return_value = None
        mock_get_scholar_profile_details.return_value = {"scholar_org": None, "scholar_citations": None}

        job_id = "test-scholar-job-no-results"
        params = {
            "query": {
                "all_words": "nonexistent query"
            },
            "fetch_author_details": "all",
        }

        temp_download_dir = tempfile.mkdtemp()
        mock_write_result = MagicMock()

        try:
            execute(job_id, params, temp_download_dir, mock_write_result)

            mock_write_result.assert_called_once()
            _, result = mock_write_result.call_args[0]

            assert result['job_id'] == job_id
            assert result['status'] == 'complete'
            assert 'articles' in result['result']
            assert len(result['result']['articles']) == 0
            assert result['result']['total_results_scraped'] == 0
        finally:
            shutil.rmtree(temp_download_dir)

    @patch('src.actions.search_google_scholar._get_scholar_profile_details')
    @patch('src.actions.search_google_scholar._setup_driver')
    def test_execute_with_pagination(self, mock_setup_driver, mock_get_scholar_profile_details,
                                     mock_get_total_estimated_results):
        """
        Tests the search_google_scholar action with pagination.
        Simulates two pages of results.
        """
        mock_driver = MagicMock()
        mock_setup_driver.return_value = mock_driver
        mock_driver.get.return_value = None

        # Mock window handles for _get_scholar_profile_details
        mock_driver.current_window_handle = "main_window"
        mock_driver.window_handles = ["main_window", "new_window"]
        mock_driver.execute_script.return_value = None
        mock_driver.switch_to.window.return_value = None
        mock_driver.close.return_value = None

        mock_get_scholar_profile_details.side_effect = [
            {"scholar_org": "Org P1A1", "scholar_citations": "10"},  # For USER_P1A1
            {"scholar_org": "Org P1A2", "scholar_citations": "20"},  # For USER_P1A2
            {"scholar_org": "Org P2A1", "scholar_citations": "30"},  # For USER_P2A1
        ]

        # --- Mock for Page 1 Articles ---
        # Article 1, Page 1
        mock_author_info_container_p1a1 = MagicMock()
        mock_author_info_container_p1a1.text = "Author P1A1 - Pub P1A1, 2023"
        mock_author_link_p1a1 = MagicMock(text="Author P1A1", get_attribute=lambda
            x: "https://scholar.google.com/citations?user=USER_P1A1&hl=en")
        mock_publication_span_p1a1 = MagicMock(text="Pub P1A1, 2023")
        mock_author_info_container_p1a1.find_elements.side_effect = [
            [mock_author_link_p1a1],
            [mock_publication_span_p1a1],
        ]

        mock_article_p1_a1 = MagicMock()
        mock_article_p1_a1.find_element.side_effect = [
            MagicMock(text="Page 1 Article 1", get_attribute=lambda x: "http://example.com/p1a1"),
            MagicMock(text="Snippet P1A1"),
            mock_author_info_container_p1a1,
        ]
        mock_article_p1_a1.find_elements.return_value = []

        # Article 2, Page 1
        mock_author_info_container_p1a2 = MagicMock()
        mock_author_info_container_p1a2.text = "Author P1A2 - Pub P1A2, 2022"
        mock_author_link_p1a2 = MagicMock(text="Author P1A2", get_attribute=lambda
            x: "https://scholar.google.com/citations?user=USER_P1A2&hl=en")
        mock_publication_span_p1a2 = MagicMock(text="Pub P1A2, 2022")
        mock_author_info_container_p1a2.find_elements.side_effect = [
            [mock_author_link_p1a2],
            [mock_publication_span_p1a2],
        ]

        mock_article_p1_a2 = MagicMock()
        mock_article_p1_a2.find_element.side_effect = [
            MagicMock(text="Page 1 Article 2", get_attribute=lambda x: "http://example.com/p1a2"),
            MagicMock(text="Snippet P1A2"),
            mock_author_info_container_p1a2,
        ]
        mock_article_p1_a2.find_elements.return_value = []

        # --- Mock for Page 2 Articles ---
        # Article 1, Page 2
        mock_author_info_container_p2a1 = MagicMock()
        mock_author_info_container_p2a1.text = "Author P2A1 - Pub P2A1, 2021"
        mock_author_link_p2a1 = MagicMock(text="Author P2A1", get_attribute=lambda
            x: "https://scholar.google.com/citations?user=USER_P2A1&hl=en")
        mock_publication_span_p2a1 = MagicMock(text="Pub P2A1, 2021")
        mock_author_info_container_p2a1.find_elements.side_effect = [
            [mock_author_link_p2a1],
            [mock_publication_span_p2a1],
        ]

        mock_article_p2_a1 = MagicMock()
        mock_article_p2_a1.find_element.side_effect = [
            MagicMock(text="Page 2 Article 1", get_attribute=lambda x: "http://example.com/p2a1"),
            MagicMock(text="Snippet P2A1"),
            mock_author_info_container_p2a1,
        ]
        mock_article_p2_a1.find_elements.return_value = []

        # Configure find_elements to return different results on subsequent calls
        # This is for `driver.find_elements(By.CSS_SELECTOR, 'div.gs_r.gs_or.gs_scl')`
        mock_driver.find_elements.side_effect = [
            [mock_article_p1_a1, mock_article_p1_a2],  # Page 1 has 2 articles
            [mock_article_p2_a1],  # Page 2 has 1 article
            [],  # Third call, no more articles
        ]

        job_id = "test-scholar-job-pagination"
        params = {
            "query": {
                "all_words": "pagination test"
            },
            "fetch_author_details": "all",
        }

        temp_download_dir = tempfile.mkdtemp()
        mock_write_result = MagicMock()

        try:
            execute(job_id, params, temp_download_dir, mock_write_result)

            mock_write_result.assert_called_once()
            _, result = mock_write_result.call_args[0]

            assert result['job_id'] == job_id
            assert result['status'] == 'complete'
            assert 'articles' in result['result']
            assert len(result['result']['articles']) == 3  # 2 from page 1 + 1 from page 2

            # Assertions for article 1 (page 1)
            article1 = result['result']['articles'][0]
            assert article1['title'] == "Page 1 Article 1"
            assert article1['link'] == "http://example.com/p1a1"
            assert article1['snippet'] == "Snippet P1A1"
            assert len(article1['authors']) == 1
            assert article1['authors'][0]['name'] == "Author P1A1"
            assert article1['authors'][0]['scholar_user'] == "USER_P1A1"
            assert article1['authors'][0]['scholar_org'] == "Org P1A1"
            assert article1['authors'][0]['scholar_citations'] == "10"
            assert article1['publication_details'] == "Pub P1A1, 2023"

            # Assertions for article 2 (page 1)
            article2 = result['result']['articles'][1]
            assert article2['title'] == "Page 1 Article 2"
            assert article2['link'] == "http://example.com/p1a2"
            assert article2['snippet'] == "Snippet P1A2"
            assert len(article2['authors']) == 1
            assert article2['authors'][0]['name'] == "Author P1A2"
            assert article2['authors'][0]['scholar_user'] == "USER_P1A2"
            assert article2['authors'][0]['scholar_org'] == "Org P1A2"
            assert article2['authors'][0]['scholar_citations'] == "20"
            assert article2['publication_details'] == "Pub P1A2, 2022"

            # Assertions for article 3 (page 2)
            article3 = result['result']['articles'][2]
            assert article3['title'] == "Page 2 Article 1"
            assert article3['link'] == "http://example.com/p2a1"
            assert article3['snippet'] == "Snippet P2A1"
            assert len(article3['authors']) == 1
            assert article3['authors'][0]['name'] == "Author P2A1"
            assert article3['authors'][0]['scholar_user'] == "USER_P2A1"
            assert article3['authors'][0]['scholar_org'] == "Org P2A1"
            assert article3['authors'][0]['scholar_citations'] == "30"
            assert article3['publication_details'] == "Pub P2A1, 2021"

        finally:
            shutil.rmtree(temp_download_dir)

    @patch('src.actions.search_google_scholar._get_scholar_profile_details')
    @patch('src.actions.search_google_scholar._setup_driver')
    def test_execute_error_handling(self, mock_setup_driver, mock_get_scholar_profile_details,
                                    mock_get_total_estimated_results):
        """
        Tests error handling during the search_google_scholar action.
        """
        mock_driver = MagicMock()
        mock_setup_driver.return_value = mock_driver
        mock_driver.get.side_effect = Exception("Simulated network error")  # Simulate a network error

        # Mock window handles for _get_scholar_profile_details (even if not called, good practice)
        mock_driver.current_window_handle = "main_window"
        mock_driver.window_handles = ["main_window", "new_window"]
        mock_driver.execute_script.return_value = None
        mock_driver.switch_to.window.return_value = None
        mock_driver.close.return_value = None
        mock_get_scholar_profile_details.return_value = {"scholar_org": None, "scholar_citations": None}

        job_id = "test-scholar-job-error"
        params = {
            "query": {
                "all_words": "error test"
            },
            "fetch_author_details": "all",
        }

        temp_download_dir = tempfile.mkdtemp()
        mock_write_result = MagicMock()

        try:
            execute(job_id, params, temp_download_dir, mock_write_result)

            mock_write_result.assert_called_once()
            _, result = mock_write_result.call_args[0]

            assert result['job_id'] == job_id
            assert result['status'] == 'failed'
            assert 'error' in result
            assert "Simulated network error" in result['error']
        finally:
            shutil.rmtree(temp_download_dir)

    def test_build_scholar_url_all_params(self, mock_get_total_estimated_results):
        """
        Tests _build_scholar_url with all possible parameters.
        """
        query_params = {
            "all_words": "machine learning",
            "exact_phrase": "reinforcement learning",
            "at_least_one": "AI OR neural networks",
            "without_words": "robotics",
            "author": "Geoffrey Hinton",
            "publication": "Nature",
            "date_range": {"start_year": 2020, "end_year": 2023},
            "full_text_only": True,  # This should be ignored
            "review_articles_only": True  # This should be ignored
        }
        url = _build_scholar_url(query_params, start_index=10)
        assert "as_q=machine+learning" in url
        assert "as_epq=reinforcement+learning" in url
        assert "as_oq=AI+OR+neural+networks" in url
        assert "as_eq=robotics" in url
        assert "as_sauthors=Geoffrey+Hinton" in url
        assert "as_publication=Nature" in url
        assert "as_ylo=2020" in url
        assert "as_yhi=2023" in url
        assert "start=10" in url
        assert "full_text_only" not in url  # Should be ignored
        assert "review_articles_only" not in url  # Should be ignored

    def test_build_scholar_url_only_exact_phrase(self, mock_get_total_estimated_results):
        """
        Tests _build_scholar_url with only exact_phrase.
        """
        query_params = {
            "exact_phrase": "large language models"
        }
        url = _build_scholar_url(query_params)
        assert "as_epq=large+language+models" in url
        assert "as_q=" in url and "as_q=large" not in url

    def test_build_scholar_url_empty_query(self, mock_get_total_estimated_results):
        """
        Tests _build_scholar_url with an empty query.
        """
        query_params = {}
        url = _build_scholar_url(query_params)
        expected_url = "https://scholar.google.com/scholar?as_q=&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=&as_publication=&as_ylo=&as_yhi=&hl=en&as_sdt=0%2C5"
        assert url == expected_url
