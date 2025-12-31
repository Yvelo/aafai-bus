import sys
import os
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))

# Import the function to be tested
from actions.drooms_scraping import execute, _sanitize_filename

# --- Test Cases for drooms_scraping ---

def test_execute_missing_parameters():
    """
    Tests that the action calls back with an error when required parameters are missing.
    """
    # ARRANGE
    write_mock = MagicMock()
    job_id = 'test-job-1'
    download_dir = '/tmp/output'
    
    # ACT & ASSERT for missing all params
    params_none = {}
    execute(job_id, params_none, download_dir, write_mock)
    write_mock.assert_called_with(job_id, {
        "status": "error", 
        "message": "Missing required parameters: url, username, or password."
    })

    # ACT & ASSERT for one missing param
    params_missing_pw = {'url': 'some_url', 'username': 'some_user'}
    execute(job_id, params_missing_pw, download_dir, write_mock)
    write_mock.assert_called_with(job_id, {
        "status": "error", 
        "message": "Missing required parameters: url, username, or password."
    })

@patch('actions.drooms_scraping.os.makedirs')
@patch('actions.drooms_scraping.WebDriverWait')
@patch('actions.drooms_scraping._expand_all_folders')
@patch('actions.drooms_scraping._login')
@patch('actions.drooms_scraping._setup_driver')
@patch('actions.drooms_scraping._gather_all_items')
@patch('actions.drooms_scraping._process_all_items')
def test_execute_success(mock_process_all, mock_gather_all, mock_setup_driver, mock_login, mock_expand, mock_wait, mock_makedirs):
    """
    Tests the success scenario for the drooms_scraping action by mocking helper functions.
    """
    # ARRANGE
    mock_driver = MagicMock()
    mock_setup_driver.return_value = mock_driver
    write_mock = MagicMock()
    job_id = 'test-job-2'
    download_dir = '/tmp/test-job'

    params = {
        'url': 'http://test.drooms.com',
        'username': 'testuser',
        'password': 'testpassword'
    }

    # ACT
    execute(job_id, params, download_dir, write_mock)

    # ASSERT
    mock_makedirs.assert_called()
    mock_setup_driver.assert_called_once()
    mock_login.assert_called_once_with(mock_driver, params['url'], params['username'], params['password'])
    mock_wait.assert_called()
    mock_expand.assert_called_once_with(mock_driver, debug_mode=False)
    
    # The final success message uses a hardcoded path
    expected_download_root = 'C:/temp/drooms_scraping'
    write_mock.assert_called_with(job_id, {
        "status": "complete", 
        "message": f"D-Rooms scraping completed. Files saved to {expected_download_root}"
    })
    
    mock_driver.quit.assert_called_once()

@patch('actions.drooms_scraping.os.makedirs')
@patch('actions.drooms_scraping._login', side_effect=Exception("Login failed"))
@patch('actions.drooms_scraping._setup_driver')
def test_execute_login_failure(mock_setup_driver, mock_login, mock_makedirs):
    """
    Tests the failure scenario when login fails.
    """
    # ARRANGE
    mock_driver = MagicMock()
    mock_setup_driver.return_value = mock_driver
    write_mock = MagicMock()
    job_id = 'test-job-3'
    download_dir = '/tmp/test-job'
    
    params = {
        'url': 'http://test.drooms.com',
        'username': 'testuser',
        'password': 'testpassword'
    }

    # ACT
    execute(job_id, params, download_dir, write_mock)

    # ASSERT
    mock_makedirs.assert_called()
    mock_setup_driver.assert_called_once()
    mock_login.assert_called_once()
    
    write_mock.assert_called_with(job_id, {
        "status": "error", 
        "message": "Login failed"
    })
    
    mock_driver.save_screenshot.assert_called_once()
    mock_driver.quit.assert_called_once()

def test_sanitize_filename():
    """
    Tests the _sanitize_filename helper function.
    """
    assert _sanitize_filename("file/name with:invalid\\chars?") == "file_name with_invalid_chars_"
    assert _sanitize_filename("a\nb\nc") == "a b c"
    assert _sanitize_filename("  leading and trailing spaces  ") == "leading and trailing spaces"
