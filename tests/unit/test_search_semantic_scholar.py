import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import tempfile
import shutil
from src.actions.search_semantic_scholar import execute, _build_semantic_scholar_url, _handle_security_check, _setup_driver
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

            assert result['status'] == 'Completed'
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

            assert result['status'] == 'Completed'
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

    @patch('src.actions.search_semantic_scholar.get_headless_status', return_value=False)
    @patch('src.actions.search_semantic_scholar.WebDriverWait')
    def test_security_check_propagates_verification_errors(
        self, mock_webdriver_wait, mock_get_headless_status, mock_get_total_estimated_results
    ):
        """An unexpected failure while waiting on a challenge must not be treated as success."""
        mock_driver = MagicMock()
        mock_driver.page_source = "captcha-container"
        mock_driver.find_element.side_effect = NoSuchElementException
        mock_webdriver_wait.return_value.until_not.side_effect = RuntimeError("webdriver failure")

        with pytest.raises(RuntimeError, match="Unable to check Semantic Scholar security verification"):
            _handle_security_check(mock_driver, timeout=1)

    def test_security_check_ignores_regular_search_page(self, mock_get_total_estimated_results):
        """A normal page should pass through without requiring manual verification."""
        mock_driver = MagicMock()
        mock_driver.page_source = "<html>Search results</html>"

        _handle_security_check(mock_driver)

    def test_security_check_rejects_headless_challenge(self, mock_get_total_estimated_results):
        """Headless searches should stop when a CAPTCHA needs a human response."""
        mock_driver = MagicMock()
        mock_driver.page_source = "captcha-container"
        mock_driver.find_element.side_effect = NoSuchElementException

        with patch('src.actions.search_semantic_scholar.get_headless_status', return_value=True):
            with pytest.raises(RuntimeError, match="blocked the request with AWS WAF CAPTCHA"):
                _handle_security_check(mock_driver)

    def test_security_check_waits_for_visible_manual_verification(self, mock_get_total_estimated_results):
        """Visible searches should pause for a user to resolve the challenge."""
        mock_driver = MagicMock()
        mock_driver.page_source = "captcha-container"
        mock_driver.find_element.side_effect = NoSuchElementException

        with patch('src.actions.search_semantic_scholar.get_headless_status', return_value=False):
            with patch('src.actions.search_semantic_scholar.WebDriverWait') as mock_webdriver_wait:
                with patch('src.actions.search_semantic_scholar.time.sleep'):
                    _handle_security_check(mock_driver, timeout=7)

        mock_webdriver_wait.assert_called_once_with(mock_driver, 7, poll_frequency=2)
        mock_webdriver_wait.return_value.until_not.assert_called_once()

    @patch('src.actions.search_semantic_scholar.solve_captcha')
    def test_security_check_calls_solve_captcha(self, mock_solve_captcha, mock_get_total_estimated_results):
        """Verifies that solve_captcha is invoked when a CAPTCHA is detected."""
        mock_driver = MagicMock()
        mock_driver.page_source = "captcha-container"
        mock_driver.find_element.side_effect = NoSuchElementException
        mock_solve_captcha.return_value = {"rows": 3, "cols": 3, "matrix": [[True, False], [False, True]]}

        with patch('src.actions.search_semantic_scholar.get_headless_status', return_value=False):
            with patch('src.actions.search_semantic_scholar.WebDriverWait'):
                with patch('src.actions.search_semantic_scholar.time.sleep'):
                    _handle_security_check(mock_driver)

        assert mock_solve_captcha.call_count >= 1
        called_arg = mock_solve_captcha.call_args[0][0]
        assert isinstance(called_arg, str)
        assert called_arg.endswith('.png')

    @patch('src.actions.search_semantic_scholar.solve_captcha')
    def test_security_check_retries_when_a_new_captcha_is_shown(self, mock_solve_captcha, mock_get_total_estimated_results):
        """A failed answer that leaves a new puzzle should call solve_captcha again."""
        mock_driver = MagicMock()
        mock_driver.find_element.side_effect = NoSuchElementException
        mock_solve_captcha.return_value = {"rows": 1, "cols": 1, "matrix": [[False]]}
        page_sources = [
            "captcha-container",
            "captcha-container",
            "<html>Success</html>",
        ]
        type(mock_driver).page_source = PropertyMock(side_effect=page_sources)

        with patch('src.actions.search_semantic_scholar.get_headless_status', return_value=False):
            with patch('src.actions.search_semantic_scholar.time.sleep'):
                _handle_security_check(mock_driver)

        assert mock_solve_captcha.call_count == 2

    @patch('src.actions.search_semantic_scholar.solve_captcha')
    def test_security_check_applies_captcha_solution(self, mock_solve_captcha, mock_get_total_estimated_results):
        """Verifies that CAPTCHA tiles and verification buttons are clicked when solve_captcha returns a solution."""
        mock_driver = MagicMock()
        mock_captcha_container = MagicMock()
        mock_verify_btn = MagicMock()
        mock_verify_btn.is_displayed.return_value = True

        def find_element_side_effect(by, value):
            if value == "captcha-container":
                return mock_captcha_container
            if value == "amzn-captcha-verify-button":
                return mock_verify_btn
            raise NoSuchElementException(f"Element not found: {value}")

        mock_driver.find_element.side_effect = find_element_side_effect
        mock_driver.page_source = "captcha-container confirm you are human"
        mock_solve_captcha.return_value = {
            "rows": 2,
            "cols": 2,
            "matrix": [[True, False], [False, True]]
        }

        # First call has captcha-container, second call after solution has no captcha
        page_sources = ["captcha-container confirm you are human", "<html>Success</html>"]
        type(mock_driver).page_source = PropertyMock(side_effect=page_sources)

        with patch('src.actions.search_semantic_scholar.get_headless_status', return_value=False):
            with patch('src.actions.search_semantic_scholar.time.sleep'):
                _handle_security_check(mock_driver)

        # Verify solve_captcha was called
        mock_solve_captcha.assert_called_once()
        # Verify execute_script was called for clicking tiles
        assert mock_driver.execute_script.call_count >= 2

    @patch('src.actions.search_semantic_scholar.solve_captcha')
    def test_security_check_starts_amazon_captcha_iframe(self, mock_solve_captcha, mock_get_total_estimated_results):
        """Starts the AWS CAPTCHA with a trusted click and solves the rendered iframe puzzle."""
        mock_driver = MagicMock()
        begin_button = MagicMock()
        begin_button.text = "Begin"
        iframe = MagicMock()
        iframe.is_displayed.return_value = True
        captcha_container = MagicMock()
        submit_button = MagicMock()
        submit_button.text = "Verify"
        submit_button.is_displayed.return_value = True
        puzzle_ready = False
        in_captcha_frame = False

        def click_begin():
            nonlocal puzzle_ready
            puzzle_ready = True

        def switch_to_frame(_frame):
            nonlocal in_captcha_frame
            in_captcha_frame = True

        def switch_to_default_content():
            nonlocal in_captcha_frame
            in_captcha_frame = False

        mock_driver.switch_to.frame.side_effect = switch_to_frame
        mock_driver.switch_to.default_content.side_effect = switch_to_default_content

        def find_element_side_effect(by, value):
            if value == "amzn-captcha-verify-button":
                return begin_button
            if in_captcha_frame and value == "captcha-container":
                return captcha_container
            if in_captcha_frame and value == "amzn-captcha-submit-button":
                return submit_button
            raise NoSuchElementException(f"Element not found: {value}")

        mock_driver.find_element.side_effect = find_element_side_effect

        def find_elements_side_effect(by, value):
            if not in_captcha_frame and "iframe" in value and puzzle_ready:
                return [iframe]
            return []

        mock_driver.find_elements.side_effect = find_elements_side_effect
        page_source_property = PropertyMock(
            side_effect=["captcha-container confirm you are human", "<html>Success</html>"]
        )
        type(mock_driver).page_source = page_source_property
        mock_solve_captcha.return_value = {"rows": 1, "cols": 1, "matrix": [[True]]}

        def execute_script_side_effect(script, *args):
            if "var clickX =" in script:
                return {"x": 10.0, "y": 20.0, "target": captcha_container}
            if "getBoundingClientRect" in script:
                if args and args[0] is iframe:
                    return {"x": 50.0, "y": 60.0, "w": 320, "h": 400}
                if args and args[0] is submit_button:
                    return {"x": 160.0, "y": 220.0, "w": 90, "h": 32}
                return {"x": 160.0, "y": 220.0, "w": 90, "h": 32}
            return None

        def execute_cdp_side_effect(_command, params):
            if params.get("type") == "mousePressed":
                click_begin()

        mock_driver.execute_script.side_effect = execute_script_side_effect
        mock_driver.execute_cdp_cmd.side_effect = execute_cdp_side_effect

        with patch('src.actions.search_semantic_scholar.get_headless_status', return_value=False):
            with patch('src.actions.search_semantic_scholar.time.sleep'):
                _handle_security_check(mock_driver)

        pressed = [
            call for call in mock_driver.execute_cdp_cmd.call_args_list
            if call.args[1].get("type") == "mousePressed"
        ]
        assert len(pressed) >= 3
        assert pressed[0].args[1]["x"] == 160.0
        assert pressed[0].args[1]["y"] == 220.0
        assert any(call.args[1]["x"] == 60.0 and call.args[1]["y"] == 80.0 for call in pressed)
        assert any(call.args[1]["x"] == 210.0 and call.args[1]["y"] == 280.0 for call in pressed)
        mock_driver.switch_to.frame.assert_called_once_with(iframe)
        mock_solve_captcha.assert_called_once()
        assert not submit_button.click.called
        assert not begin_button.click.called
        mock_driver.switch_to.default_content.assert_called_once()
        assert page_source_property.call_count == 2


def test_setup_driver_retries_with_a_fresh_chrome_options():
    """A version-mismatch retry must not reuse the ChromeOptions consumed by the first launch."""
    first_options = MagicMock(name="first_options")
    second_options = MagicMock(name="second_options")
    driver = MagicMock()

    fake_uc = MagicMock()
    fake_uc.ChromeOptions.side_effect = [first_options, second_options]
    fake_uc.Chrome.side_effect = [
        Exception("session not created: Current browser version is 131"),
        driver,
    ]

    with patch.dict('sys.modules', {'undetected_chromedriver': fake_uc}):
        with patch('src.actions.search_semantic_scholar.tempfile.mkdtemp', return_value='C:\\temp\\uc'):
            with patch('src.actions.search_semantic_scholar.get_headless_status', return_value=True):
                with patch('src.actions.search_semantic_scholar.stealth'):
                    result = _setup_driver('job-dir', 'download-dir')

    assert result is driver
    assert fake_uc.Chrome.call_args_list[0].kwargs['options'] is first_options
    assert fake_uc.Chrome.call_args_list[1].kwargs['options'] is second_options
    assert fake_uc.Chrome.call_args_list[1].kwargs['version_main'] == 131
