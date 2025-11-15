# tests/conftest.py
import pytest
import os
import shutil
from server import app as flask_app

@pytest.fixture
def app():
    """Create and configure a new app instance for each test."""

    # --- Configuration for Testing ---
    # Use a temporary folder for the queues, isolated for each test run
    base_path = "test_queues"
    flask_app.config['TESTING'] = True
    flask_app.config['BASE_QUEUE_PATH'] = base_path

    # --- Setup: Ensure a clean state before each test ---
    # Clean up directories from previous runs if they exist
    if os.path.exists(base_path):
        shutil.rmtree(base_path)

    # Create the necessary directories for the test
    os.makedirs(os.path.join(base_path, 'inbound'), exist_ok=True)
    os.makedirs(os.path.join(base_path, 'outbound'), exist_ok=True)
    os.makedirs(os.path.join(base_path, 'consumed'), exist_ok=True)

    yield flask_app

    # --- Teardown: Clean up after each test ---
    shutil.rmtree(base_path)