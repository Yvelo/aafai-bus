import os
from unittest.mock import patch, MagicMock
import requests
from bs4 import BeautifulSoup

# Import the function to be tested from its new location
from actions.full_recursive_download import execute


def test_execute_download_success(app):
    """
    Tests the success scenario for the 'full_recursive_download' action.
    - Mocks network requests and other external dependencies.
    - Directly calls the action's execute function.
    - Verifies the final result is passed to the callback correctly.
    """
    # 1. ARRANGE
    job_id = "test-job-success"
    url = "http://mit.edu"
    download_dir = app.config['DOWNLOAD_DIR']
    download_path = os.path.join(download_dir, job_id)
    mock_html = "<html><body><h1>Test Page</h1></body></html>"
    expected_content = BeautifulSoup(mock_html, 'html.parser').prettify()
    mock_write_result = MagicMock()
    params = {'url': url}

    # 2. ACT & MOCK
    # Patch the dependencies of the function we are testing.
    with patch('actions.full_recursive_download.requests.get') as mock_get, \
         patch('actions.full_recursive_download.time.sleep', return_value=None) as mock_sleep:

        # Configure the mock for a successful download
        mock_response = MagicMock()
        mock_response.text = mock_html
        mock_get.return_value = mock_response

        # Manually execute the action function
        execute(job_id, params, download_dir, mock_write_result)

    # 3. ASSERT
    # Assert that the network call was made correctly
    mock_get.assert_called_once_with(url, timeout=10)

    # Assert that the file was created and contains the correct content
    expected_file = os.path.join(download_path, 'index.html')
    assert os.path.exists(expected_file)
    with open(expected_file, 'r', encoding='utf-8') as f:
        assert f.read() == expected_content

    # Assert that the long-running process was simulated
    mock_sleep.assert_called_once_with(5)

    # Assert that the final result was written with a 'complete' status
    expected_result_data = {
        'job_id': job_id,
        'status': 'complete',
        'result': f'Successfully downloaded content from {url} to {download_path}'
    }
    mock_write_result.assert_called_once_with(job_id, expected_result_data)


def test_execute_download_network_failure(app):
    """
    Tests the failure scenario for the 'full_recursive_download' action.
    - Mocks the network request to raise an exception.
    - Directly calls the action's execute function.
    - Verifies that the 'failed' status is passed to the callback correctly.
    """
    # 1. ARRANGE
    job_id = "test-job-failure"
    url = "http://example-fails.com"
    download_dir = app.config['DOWNLOAD_DIR']
    download_path = os.path.join(download_dir, job_id)
    error_message = "Network Error"
    mock_write_result = MagicMock()
    params = {'url': url}

    # 2. ACT & MOCK
    with patch('actions.full_recursive_download.requests.get') as mock_get:
        # Configure the mock to raise a RequestException
        mock_get.side_effect = requests.exceptions.RequestException(error_message)

        # Manually execute the action function
        execute(job_id, params, download_dir, mock_write_result)

    # 3. ASSERT
    # Assert that a network call was attempted
    mock_get.assert_called_once_with(url, timeout=10)

    # Assert that no file was created due to the failure
    expected_file = os.path.join(download_path, 'index.html')
    assert not os.path.exists(expected_file)

    # Assert that the final result was written with a 'failed' status and the error
    expected_result_data = {
        'job_id': job_id,
        'status': 'failed',
        'error': error_message
    }
    mock_write_result.assert_called_once_with(job_id, expected_result_data)
