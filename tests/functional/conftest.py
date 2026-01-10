# tests/conftest.py
import pytest
import os
import shutil
import http.server
import socketserver
import threading
from src.server import create_app

@pytest.fixture
def app():
    """Create and configure a new app instance for each test using the app factory."""

    # Create the app with testing configuration. This also creates the queue directories.
    app = create_app(testing=True)
    base_path = app.config['BASE_QUEUE_PATH']

    # The actions run in a separate process and don't have access to the app config,
    # so we pass the test queue path via an environment variable.
    os.environ['QUEUE_BASE_PATH'] = base_path

    # --- Setup: Ensure a clean state before each test ---
    # The create_app function already creates the directories. Here, we just ensure
    # they are empty before the test runs.
    if os.path.exists(base_path):
        shutil.rmtree(base_path)
    
    # Re-create all necessary directories for the test environment.
    os.makedirs(os.path.join(base_path, 'inbound'), exist_ok=True)
    os.makedirs(os.path.join(base_path, 'outbound'), exist_ok=True)
    os.makedirs(os.path.join(base_path, 'consumed'), exist_ok=True)
    os.makedirs(os.path.join(base_path, 'failed'), exist_ok=True)
    os.makedirs(os.path.join(base_path, 'processing'), exist_ok=True)

    yield app

    # --- Teardown: Clean up after each test ---
    shutil.rmtree(base_path)
    del os.environ['QUEUE_BASE_PATH']

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

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
