import sys
import os
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))

# Import the function to be tested
from actions.drooms_scraping import run, _sanitize_filename

# --- Test Cases for drooms_scraping ---

def test_run_missing_parameters():
    """
    Tests that the action returns an error when required parameters are missing.
    """
    # ARRANGE
    job_context = {'job_output_dir': '/tmp/output'}
    
    # ACT & ASSERT for missing all params
    params_none = {}
    result_none = run(params_none, job_context)
    assert result_none['status'] == 'error'
    assert "Missing required parameters" in result_none['message']

    # ACT & ASSERT for one missing param
    params_missing_pw = {'url': 'some_url', 'username': 'some_user'}
    result_missing_pw = run(params_missing_pw, job_context)
    assert result_missing_pw['status'] == 'error'
    assert "Missing required parameters" in result_missing_pw['message']

@patch('actions.drooms_scraping.os.makedirs')
@patch('actions.drooms_scraping.WebDriverWait')
@patch('actions.drooms_scraping._expand_all_folders')
@patch('actions.drooms_scraping._login')
@patch('actions.drooms_scraping._setup_driver')
def test_run_success(mock_setup_driver, mock_login, mock_expand, mock_wait, mock_makedirs):
    """
    Tests the success scenario for the drooms_scraping action by mocking helper functions.
    """
    # ARRANGE
    mock_driver = MagicMock()
    mock_setup_driver.return_value = mock_driver

    params = {
        'url': 'http://test.drooms.com',
        'username': 'testuser',
        'password': 'testpassword'
    }
    job_context = {'job_output_dir': '/tmp/test-job'}

    # ACT
    result = run(params, job_context)

    # ASSERT
    mock_makedirs.assert_called()
    mock_setup_driver.assert_called_once()
    mock_login.assert_called_once_with(mock_driver, params['url'], params['username'], params['password'])
    mock_wait.assert_called()
    mock_expand.assert_called_once_with(mock_driver)
    
    assert result['status'] == 'complete'
    assert 'D-Rooms scraping completed' in result['message']
    
    mock_driver.quit.assert_called_once()

@patch('actions.drooms_scraping.os.makedirs')
@patch('actions.drooms_scraping._login', side_effect=Exception("Login failed"))
@patch('actions.drooms_scraping._setup_driver')
def test_run_login_failure(mock_setup_driver, mock_login, mock_makedirs):
    """
    Tests the failure scenario when login fails.
    """
    # ARRANGE
    mock_driver = MagicMock()
    mock_setup_driver.return_value = mock_driver
    
    params = {
        'url': 'http://test.drooms.com',
        'username': 'testuser',
        'password': 'testpassword'
    }
    job_context = {'job_output_dir': '/tmp/test-job'}

    # ACT
    result = run(params, job_context)

    # ASSERT
    mock_makedirs.assert_called()
    mock_setup_driver.assert_called_once()
    mock_login.assert_called_once()
    
    assert result['status'] == 'error'
    assert "Login failed" in result['message']
    
    mock_driver.save_screenshot.assert_called_once()
    mock_driver.quit.assert_called_once()

def test_sanitize_filename():
    """
    Tests the _sanitize_filename helper function.
    """
    assert _sanitize_filename("file/name with:invalid\\chars?") == "file_name with_invalid_chars_"
    assert _sanitize_filename("a\nb\nc") == "a b c"
    assert _sanitize_filename("  leading and trailing spaces  ") == "leading and trailing spaces"
