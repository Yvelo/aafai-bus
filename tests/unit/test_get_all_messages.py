import sys
import os
import pytest
import json
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))

from actions import full_recursive_download, get_all_messages

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

def test_get_all_messages(tmp_path, app):
    """
    Tests that the 'get_all_messages' action correctly retrieves all messages
    from the inbound, consumed, and failed queues.
    """
    # 1. ARRANGE
    job_id = "test-get-all-messages"
    params = {}

    # Create mock queue directories
    queue_base_path = tmp_path / "queues"
    inbound_dir = queue_base_path / "inbound"
    consumed_dir = queue_base_path / "consumed"
    failed_dir = queue_base_path / "failed"
    inbound_dir.mkdir(parents=True, exist_ok=True)
    consumed_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)

    # Create dummy message files
    inbound_msg = {"action": "test_action_1"}
    consumed_msg = {"action": "test_action_2"}
    failed_msg = {"action": "test_action_3"}

    with open(inbound_dir / "msg1.json", "w") as f:
        json.dump(inbound_msg, f)
    with open(consumed_dir / "msg2.json", "w") as f:
        json.dump(consumed_msg, f)
    with open(failed_dir / "msg3.json", "w") as f:
        json.dump(failed_msg, f)

    mock_write_result = MagicMock()

    with patch.dict(os.environ, {'QUEUE_BASE_PATH': str(queue_base_path)}):
        with app.app_context():
            # 2. ACT
            get_all_messages.execute(job_id, params, None, mock_write_result)

    # 3. ASSERT
    mock_write_result.assert_called_once()
    args, _ = mock_write_result.call_args
    result_job_id, result_data = args

    assert result_job_id == job_id
    assert result_data['status'] == 'complete'
    messages = result_data['result']
    assert len(messages['inbound']) == 1
    assert messages['inbound'][0] == inbound_msg
    assert len(messages['consumed']) == 1
    assert messages['consumed'][0] == consumed_msg
    assert len(messages['failed']) == 1
    assert messages['failed'][0] == failed_msg