import sys
import os
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))

from actions import clear_all_messages

def test_clear_all_messages(app):
    """
    Tests that the 'clear_all_messages' action correctly deletes all messages
    from the inbound, consumed, and failed queues and leaves a confirmation message.
    """
    # 1. ARRANGE
    job_id = "test-clear-all-messages"
    params = {}

    # Directories are created by the app fixture. Get their paths from the app config.
    queue_base_path = app.config['BASE_QUEUE_PATH']
    inbound_dir = os.path.join(queue_base_path, "inbound")
    consumed_dir = os.path.join(queue_base_path, "consumed")
    failed_dir = os.path.join(queue_base_path, "failed")

    # Create dummy message files
    (open(os.path.join(inbound_dir, "msg1.json"), "w")).close()
    (open(os.path.join(consumed_dir, "msg2.json"), "w")).close()
    (open(os.path.join(failed_dir, "msg3.json"), "w")).close()

    mock_write_result = MagicMock()

    with app.app_context():
        # 2. ACT
        clear_all_messages.execute(job_id, params, None, mock_write_result)

    # 3. ASSERT
    assert not os.listdir(inbound_dir)
    assert not os.listdir(consumed_dir)
    assert not os.listdir(failed_dir)

    mock_write_result.assert_called_once()
    args, _ = mock_write_result.call_args
    result_job_id, result_data = args

    assert result_job_id == job_id
    assert result_data['status'] == 'complete'
    assert result_data['result']['message'] == 'All queues cleared successfully.'
    assert set(result_data['result']['cleared_queues']) == {'inbound', 'consumed', 'failed'}
