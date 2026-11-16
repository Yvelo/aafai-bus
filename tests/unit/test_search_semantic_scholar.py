import os
import threading
import time
import pytest
from unittest.mock import MagicMock, patch, PropertyMock, call
import tempfile
import shutil
from src.actions.search_semantic_scholar import execute, _build_semantic_scholar_url, _handle_security_check, _setup_driver
from selenium.common.exceptions import NoSuchElementException, TimeoutException


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


def test_setup_driver_retries_driver_discovery_with_detected_chrome_version():
    first_options = MagicMock(name="first_options")
    second_options = MagicMock(name="second_options")
    driver = MagicMock()
    fake_uc = MagicMock()
    fake_uc.ChromeOptions.side_effect = [first_options, second_options]
    fake_uc.find_chrome_executable.return_value = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    fake_uc.Chrome.side_effect = [Exception("Unable to obtain driver for chrome"), driver]

    with patch.dict('sys.modules', {'undetected_chromedriver': fake_uc}):
        with patch('src.actions.search_semantic_scholar.tempfile.mkdtemp', side_effect=[r'C:\temp\uc1', r'C:\temp\uc2']):
            with patch('src.actions.search_semantic_scholar.subprocess.run', return_value=MagicMock(stdout="Google Chrome 132.0.6834.83", stderr="")):
                with patch('src.actions.search_semantic_scholar.get_headless_status', return_value=True):
                    with patch('src.actions.search_semantic_scholar.stealth'):
                        with patch('src.actions.search_semantic_scholar.shutil.rmtree'):
                            result = _setup_driver('job-dir', 'download-dir')

    assert result is driver
    assert fake_uc.Chrome.call_count == 2
    assert fake_uc.Chrome.call_args_list[0].kwargs['version_main'] == 132
    assert fake_uc.Chrome.call_args_list[0].kwargs['use_subprocess'] is True
    assert fake_uc.Chrome.call_args_list[0].kwargs['browser_executable_path'] == fake_uc.find_chrome_executable.return_value
    assert fake_uc.Chrome.call_args_list[1].kwargs['version_main'] == 132
    assert fake_uc.Chrome.call_args_list[1].kwargs['use_subprocess'] is True
    assert call('--user-data-dir=C:\\temp\\uc1') in first_options.add_argument.call_args_list
    assert call('--user-data-dir=C:\\temp\\uc2') in second_options.add_argument.call_args_list


def test_setup_driver_preserves_original_error_after_all_launch_retries():
    original_error = Exception("Unable to obtain driver for chrome")
    fake_uc = MagicMock()
    fake_uc.find_chrome_executable.return_value = None
    fake_uc.Chrome.side_effect = [original_error, Exception("retry failed"), Exception("final failure")]

    with patch.dict('sys.modules', {'undetected_chromedriver': fake_uc}):
        with patch('src.actions.search_semantic_scholar.tempfile.mkdtemp', side_effect=[r'C:\temp\uc1', r'C:\temp\uc2', r'C:\temp\uc3']):
            with patch('src.actions.search_semantic_scholar.get_headless_status', return_value=True):
                with patch('src.actions.search_semantic_scholar.shutil.rmtree'):
                    with pytest.raises(Exception) as error:
                        _setup_driver('job-dir', 'download-dir')

    assert error.value is original_error
    assert fake_uc.Chrome.call_count == 3


def test_setup_driver_keeps_chromedriver_cache_out_of_home_local():
    driver = MagicMock()
    fake_uc = MagicMock()
    home = r"C:\var\www"
    seen = {}

    def launch(**kwargs):
        seen["home"] = os.environ.get("HOME")
        seen["data_path"] = fake_uc.Patcher.data_path
        return driver

    fake_uc.Chrome.side_effect = launch

    with patch.dict('sys.modules', {'undetected_chromedriver': fake_uc}):
        with patch.dict(os.environ, {"HOME": home}, clear=False):
            with patch('src.actions.search_semantic_scholar.tempfile.mkdtemp', return_value=r'C:\temp\uc1'):
                with patch('src.actions.search_semantic_scholar.tempfile.gettempdir', return_value=r'C:\temp'):
                    with patch('src.actions.search_semantic_scholar.get_headless_status', return_value=True):
                        with patch('src.actions.search_semantic_scholar.stealth'):
                            with patch('src.actions.search_semantic_scholar.os.makedirs'):
                                result = _setup_driver('job-dir', 'download-dir')
            assert os.environ["HOME"] == home

    assert result is driver
    assert seen["home"] == r'C:\temp\uc1'
    assert seen["data_path"] == os.path.join(r'C:\temp', 'undetected_chromedriver')
    assert '.local' not in seen["data_path"]


def test_quit_driver_ignores_connection_error():
    from src.actions.search_semantic_scholar import _quit_driver

    driver = MagicMock()
    driver.quit.side_effect = ConnectionError("Connection refused")

    _quit_driver(driver)

    driver.quit.assert_called_once_with()


def test_run_search_reraises_dead_driver_while_dismissing_cookie_banner():
    from src.actions.search_semantic_scholar import _run_search

    driver = MagicMock()
    driver.find_element.side_effect = ConnectionError(
        "HTTPConnectionPool(host='localhost', port=41895): Max retries exceeded "
        "(Caused by NewConnectionError: Failed to establish a new connection: [Errno 111] Connection refused)"
    )

    with patch('src.actions.search_semantic_scholar._handle_security_check'):
        with patch('src.actions.search_semantic_scholar.WebDriverWait') as wait:
            wait.return_value.until.side_effect = driver.find_element.side_effect
            with pytest.raises(ConnectionError, match='Connection refused'):
                _run_search(driver, 'job', {'all_words': 'test'}, 'none', 1, None, [], {})


def test_get_author_details_propagates_driver_connection_errors():
    from src.actions.search_semantic_scholar import _get_author_details

    driver = MagicMock()
    driver.current_window_handle = 'main-window'
    driver.window_handles = ['main-window', 'author-window']
    driver.get.side_effect = ConnectionError('Connection refused')

    with pytest.raises(ConnectionError, match='Connection refused'):
        _get_author_details(driver, 'https://example.com/author')

    driver.close.assert_called_once_with()
    driver.switch_to.window.assert_has_calls([call('author-window'), call('main-window')])


@patch('src.actions.search_semantic_scholar._run_search')
@patch('src.actions.search_semantic_scholar._setup_driver')
def test_execute_restarts_driver_connection_failure_before_first_article(mock_setup_driver, mock_run_search, tmp_path):
    from src.actions.search_semantic_scholar import execute

    first_driver = MagicMock()
    second_driver = MagicMock()
    mock_setup_driver.side_effect = [first_driver, second_driver]
    completed_result = {
        'job_id': 'restart-test',
        'status': 'Completed',
        'result': {'articles': []},
    }
    mock_run_search.side_effect = [
        ConnectionError("HTTPConnectionPool(host='localhost'): Connection refused"),
        completed_result,
    ]
    write_result = MagicMock()

    execute(
        'restart-test',
        {'query': {'all_words': 'test'}},
        str(tmp_path),
        write_result,
    )

    assert mock_setup_driver.call_count == 2
    assert mock_run_search.call_count == 2
    first_driver.quit.assert_called_once_with()
    write_result.assert_called_once_with('restart-test', completed_result)


@patch('src.actions.search_semantic_scholar._run_search')
@patch('src.actions.search_semantic_scholar._setup_driver')
def test_execute_retries_connection_failure_after_preserving_scraped_articles(mock_setup_driver, mock_run_search, tmp_path):
    first_driver = MagicMock()
    second_driver = MagicMock()
    mock_setup_driver.side_effect = [first_driver, second_driver]
    article = {'title': 'Already scraped', 'link': 'https://example.com/paper'}
    completed_result = {'job_id': 'partial-retry-test', 'status': 'Completed', 'result': {'articles': [article]}}

    attempts = 0

    def run_search(*args):
        nonlocal attempts
        attempts += 1
        results = args[6]
        if attempts == 1:
            results.append(article)
            raise ConnectionError("HTTPConnectionPool(host='localhost'): Connection refused")
        assert results == [article]
        return completed_result

    mock_run_search.side_effect = run_search
    write_result = MagicMock()

    with patch('src.actions.search_semantic_scholar._cleanup_driver'):
        execute('partial-retry-test', {'query': {'all_words': 'test'}}, str(tmp_path), write_result)

    assert mock_setup_driver.call_count == 2
    assert mock_run_search.call_count == 2
    write_result.assert_called_once_with('partial-retry-test', completed_result)


@patch('src.actions.search_semantic_scholar._run_search')
@patch('src.actions.search_semantic_scholar._setup_driver')
def test_execute_returns_partial_results_after_repeated_driver_failures(mock_setup_driver, mock_run_search, tmp_path):
    drivers = [MagicMock() for _ in range(3)]
    mock_setup_driver.side_effect = drivers
    article = {'title': 'Partial result', 'link': 'https://example.com/partial'}

    def fail_with_partial_results(*args):
        results = args[6]
        if not results:
            results.append(article)
        raise ConnectionError("HTTPConnectionPool(host='localhost'): Connection refused")

    mock_run_search.side_effect = fail_with_partial_results
    write_result = MagicMock()

    with patch('src.actions.search_semantic_scholar._cleanup_driver'):
        execute('partial-result-test', {'query': {'all_words': 'test'}}, str(tmp_path), write_result)

    write_result.assert_called_once()
    _, result = write_result.call_args[0]
    assert mock_setup_driver.call_count == 3
    assert mock_run_search.call_count == 3
    assert result['status'] == 'Completed'
    assert 'warning' in result
    assert result['result']['articles'] == [article]
    assert result['result']['total_results_scraped'] == 1


def test_run_search_skips_articles_already_collected_on_retry():
    from src.actions.search_semantic_scholar import _run_search

    duplicate_article_element = MagicMock()
    new_article_element = MagicMock()
    driver = MagicMock()
    driver.find_elements.return_value = [duplicate_article_element, new_article_element]
    driver.find_element.side_effect = NoSuchElementException
    scraped_article = {'title': 'A paper title', 'link': 'https://example.com/first'}
    articles = [scraped_article]
    duplicate_article = {'title': ' A PAPER   TITLE ', 'link': 'https://example.com/duplicate'}
    new_article = {'title': 'A different paper', 'link': 'https://example.com/new'}

    class ImmediateTimeoutWait:
        def __init__(self, *args, **kwargs):
            pass

        def until(self, *args, **kwargs):
            raise TimeoutException()

    with patch('src.actions.search_semantic_scholar.WebDriverWait', ImmediateTimeoutWait):
        with patch('src.actions.search_semantic_scholar._handle_security_check'):
            with patch('src.actions.search_semantic_scholar._get_total_estimated_results', return_value=2):
                with patch('src.actions.search_semantic_scholar._parse_single_article', side_effect=[duplicate_article, new_article]):
                    result = _run_search(
                        driver,
                        'dedupe-test',
                        {'all_words': 'test'},
                        'none',
                        10,
                        None,
                        articles,
                        {},
                    )

    assert result['result']['articles'] == [scraped_article, new_article]


def test_execute_runs_only_one_semantic_scholar_search_at_a_time(tmp_path):
    active = {'count': 0, 'max': 0}
    state_lock = threading.Lock()

    def slow_search(*args, **kwargs):
        with state_lock:
            active['count'] += 1
            active['max'] = max(active['max'], active['count'])
        time.sleep(0.05)
        with state_lock:
            active['count'] -= 1

    errors = []

    def run_job(job_id):
        try:
            execute(job_id, {'query': {'all_words': 'test'}}, str(tmp_path), MagicMock())
        except Exception as exc:
            errors.append(exc)

    with patch('src.actions.search_semantic_scholar._execute_search', side_effect=slow_search):
        threads = [threading.Thread(target=run_job, args=(f'job-{index}',)) for index in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

    assert not errors
    assert active['max'] == 1
    assert not any(thread.is_alive() for thread in threads)
