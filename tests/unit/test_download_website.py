import os
import pytest
from unittest.mock import MagicMock, patch
import http.server
import socketserver
import threading

# Import the function to be tested
from actions.full_recursive_download import execute

# --- Fixture for a simple, live HTTP server ---
@pytest.fixture(scope="module")
def static_file_server():  # Renamed from 'live_server' to avoid conflict with pytest-flask
    """
    Starts a simple HTTP server in a background thread to serve static files
    from the 'tests/fixtures' directory.
    """
    # Find an available port
    with socketserver.TCPServer(("127.0.0.1", 0), None) as s:
        port = s.server_address[1]

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory='tests/fixtures', **kwargs)

    httpd = socketserver.TCPServer(("127.0.0.1", port), Handler)
    
    server_thread = threading.Thread(target=httpd.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    yield f"http://127.0.0.1:{port}"

    # Teardown: Stop the server
    httpd.shutdown()
    httpd.server_close()
    server_thread.join()

# --- Updated Test Cases ---

def test_execute_download_success_with_static_server(static_file_server, app):
    """
    Tests the success scenario by using a real headless browser against a live, local test server.
    """
    # 1. ARRANGE
    job_id = "test-job-live-server"
    # The URL now points to our local test page served by our custom fixture
    url = f"{static_file_server}/test_page.html"
    download_dir = app.config['DOWNLOAD_DIR']
    mock_write_result = MagicMock()
    params = {'url': url}

    expected_text = "Hello, World!\nThis is a stable test page for Selenium."

    # 2. ACT
    execute(job_id, params, download_dir, mock_write_result)

    # 3. ASSERT
    mock_write_result.assert_called_once()
    result_data = mock_write_result.call_args[0][1]
    
    assert result_data['status'] == 'complete'
    assert result_data['job_id'] == job_id
    
    result = result_data['result']
    assert result['text'] == expected_text
    assert result['warning'] is None
    assert result['size_bytes'] == len(expected_text.encode('utf-8'))


def test_execute_download_selenium_failure(app):
    """
    Tests the failure scenario for the 'full_recursive_download' action
    by mocking a Selenium error.
    """
    # 1. ARRANGE
    job_id = "test-job-selenium-failure"
    url = "http://example-fails.com"
    download_dir = app.config['DOWNLOAD_DIR']
    error_message = "Selenium WebDriver not found"
    mock_write_result = MagicMock()
    params = {'url': url}

    # 2. ACT & MOCK
    with patch('actions.full_recursive_download.webdriver.Chrome', side_effect=Exception(error_message)):
        execute(job_id, params, download_dir, mock_write_result)

    # 3. ASSERT
    mock_write_result.assert_called_once()
    result_data = mock_write_result.call_args[0][1]

    assert result_data['status'] == 'failed'
    assert result_data['job_id'] == job_id
    assert error_message in result_data['error']
