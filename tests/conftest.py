# tests/conftest.py
import pytest
import os
import shutil
from server import create_app

@pytest.fixture
def app():
    """Create and configure a new app instance for each test using the app factory."""

    # Create the app with testing configuration
    app = create_app(testing=True)

    # The base path is now set within create_app, but we still need to clean it up
    base_path = app.config['BASE_QUEUE_PATH']

    # --- Setup: Ensure a clean state before each test ---
    # Clean up directories from previous runs if they exist
    if os.path.exists(base_path):
        shutil.rmtree(base_path)

    # Re-create directories for the test
    os.makedirs(os.path.join(base_path, 'inbound'), exist_ok=True)
    os.makedirs(os.path.join(base_path, 'outbound'), exist_ok=True)
    os.makedirs(os.path.join(base_path, 'consumed'), exist_ok=True)

    yield app

    # --- Teardown: Clean up after each test ---
    shutil.rmtree(base_path)

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()
