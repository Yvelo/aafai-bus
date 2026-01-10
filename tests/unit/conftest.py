# tests/conftest.py
import pytest
import os
import shutil
import http.server
import socketserver
import threading
from src.server import create_app

@pytest.fixture
def app(request, tmp_path):
    """
    Create and configure a new app instance for each test.
    This fixture sets the QUEUE_BASE_PATH environment variable before app creation,
    ensuring the app and tests operate on the same directory.
    """
    # Default path for tests that don't specify one.
    queue_base_path = tmp_path / "queues"

    # Allow tests to override the path.
    if hasattr(request, "param") and callable(request.param):
        queue_base_path = request.param(tmp_path)

    os.environ['QUEUE_BASE_PATH'] = str(queue_base_path)

    # Create the app with testing configuration
    app = create_app(testing=True)

    # The base path is now set within create_app, but we still need to clean it up
    base_path = app.config['BASE_QUEUE_PATH']

    # --- Setup: Ensure a clean state before each test ---
    if os.path.exists(base_path):
        shutil.rmtree(base_path)

    # Re-create directories for the test
    for dir_name in ['inbound', 'outbound', 'consumed', 'failed', 'processing']:
        os.makedirs(os.path.join(base_path, dir_name), exist_ok=True)

    yield app

    # --- Teardown: Clean up after each test ---
    shutil.rmtree(base_path)
    del os.environ['QUEUE_BASE_PATH']

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

@pytest.fixture(scope="module")
def static_file_server():
    """
    Starts a simple HTTP server in a background thread to serve static files
    from the 'tests/fixtures' directory.
    """
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

    httpd.shutdown()
    httpd.server_close()
    server_thread.join()
