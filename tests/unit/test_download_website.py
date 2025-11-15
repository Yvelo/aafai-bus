import os
import json
from unittest.mock import patch, MagicMock
import requests
from bs4 import BeautifulSoup

from server import download_website_recursively


def test_download_website_recursively_success(client, app):
    """
    Tests the success scenario for downloading a website.
    - Mocks network requests and other external dependencies.
    - Simulates receiving a task via an API call to get a job_id.
    - Directly calls the worker function to simulate its execution.
    - Verifies the final result is written correctly.
    """
    # 1. ARRANGE
    job_id = "test-job-success"
    url = "http://mit.edu"
    download_path = os.path.join(app.config['DOWNLOAD_DIR'], job_id)
    mock_html = "<html><body><h1>Test Page</h1></body></html>"
    expected_content = BeautifulSoup(mock_html, 'html.parser').prettify()

    # 2. ACT & MOCK
    # We patch the dependencies of the function we are about to manually execute.
    with patch('server.requests.get') as mock_get, \
            patch('server.time.sleep', return_value=None) as mock_sleep, \
            patch('server.write_result_to_outbound') as mock_write_result, \
            patch('uuid.uuid4', return_value=job_id):  # Mock job_id for predictability

        # First, call the API to simulate the job being created.
        response = client.post('/inbound', data=json.dumps({
            'action': 'download_website',
            'params': {'url': url}
        }), content_type='application/json')

        # API should confirm receipt of the job
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'received'
        assert data['job_id'] == job_id

        # Configure the mock for a successful download
        mock_response = MagicMock()
        mock_response.text = mock_html
        mock_get.return_value = mock_response

        # Now, manually execute the function to simulate a background worker picking up the task.
        download_website_recursively(job_id, url, download_path)

    # 3. ASSERT
    # Assert that the network call was made correctly by the function
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


def test_download_website_recursively_network_failure(client, app):
    """
    Tests the failure scenario for downloading a website.
    - Mocks the network request to raise an exception.
    - Simulates receiving a task via an API call.
    - Directly calls the worker function to simulate its execution.
    - Verifies that the 'failed' status is written correctly.
    """
    # 1. ARRANGE
    job_id = "test-job-failure"
    url = "http://example-fails.com"
    download_path = os.path.join(app.config['DOWNLOAD_DIR'], job_id)
    error_message = "Network Error"

    # 2. ACT & MOCK
    with patch('server.requests.get') as mock_get, \
            patch('server.write_result_to_outbound') as mock_write_result, \
            patch('uuid.uuid4', return_value=job_id):  # Mock job_id for predictability

        # First, call the API to simulate the job being created.
        response = client.post('/inbound', data=json.dumps({
            'action': 'download_website',
            'params': {'url': url}
        }), content_type='application/json')

        # API should confirm receipt of the job
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'received'
        assert data['job_id'] == job_id

        # Configure the mock to raise a RequestException
        mock_get.side_effect = requests.exceptions.RequestException(error_message)

        # Manually execute the function to simulate the worker
        download_website_recursively(job_id, url, download_path)

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