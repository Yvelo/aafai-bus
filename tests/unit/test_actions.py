import sys
import os
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))

from actions import full_recursive_download

def test_full_recursive_download_missing_url(app):
    """
    Tests that the 'full_recursive_download' action raises a ValueError
    when the 'url' parameter is missing. The scheduler is responsible for catching this.
    """
    # 1. ARRANGE
    job_id = "test-job-no-url"
    params = {'other_param': 'value'}
    download_dir = app.config['DOWNLOAD_DIR']
    mock_write_result = MagicMock()

    # 2. ACT & ASSERT
    # Verify that executing the action with invalid parameters raises an exception
    # that the scheduler is expected to catch.
    with pytest.raises(ValueError, match="'url' parameter is missing"):
        full_recursive_download.execute(job_id, params, download_dir, mock_write_result)

    # Ensure no result was written by the action itself
    mock_write_result.assert_not_called()
