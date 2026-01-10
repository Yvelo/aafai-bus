import os
import json
import time
import logging
from flask import current_app
from src.server import process_inbound_queue

def poll_for_result(client, job_id, timeout=30):
    """Polls the outbound endpoint until the job is complete or times out."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        response = client.get(f'/outbound?job_id={job_id}')
        if response.status_code == 200:
            data = response.get_json()
            logging.info(f"Polling for job {job_id}, status: {data.get('status')}")
            if data.get('status') == 'complete':
                return data
        time.sleep(0.5)
    return None

def test_get_all_messages_action_empty(client, app):
    """Test that the get_all_messages action returns an empty structure when no messages exist."""
    # 1. ACT
    response = client.post('/inbound', json={'action': 'get_all_messages'})
    assert response.status_code == 200
    job_id = response.get_json()['job_id']
    time.sleep(0.1) # Give the filesystem time to create the file

    process_inbound_queue(app)  # Manually trigger processing

    data = poll_for_result(client, job_id)

    # 3. ASSERT
    assert data is not None, "Polling for result timed out."
    assert data['status'] == 'complete'
    messages = data['result']
    assert messages['inbound'] == []
    assert messages['consumed'] == []
    assert messages['failed'] == []

def test_get_all_messages_action_with_data(client, app):
    """Test the get_all_messages action with messages in various queues."""
    # 1. ARRANGE
    base_path = current_app.config['BASE_QUEUE_PATH']
    inbound_dir = os.path.join(base_path, 'inbound')
    consumed_dir = os.path.join(base_path, 'consumed')
    failed_dir = os.path.join(base_path, 'failed')

    inbound_msg = {"test": "inbound_data"}
    consumed_msg = {"test": "consumed_data"}
    failed_msg = {"test": "failed_data"}

    with open(os.path.join(inbound_dir, 'inbound.json'), 'w') as f:
        json.dump(inbound_msg, f)
    with open(os.path.join(consumed_dir, 'consumed.json'), 'w') as f:
        json.dump(consumed_msg, f)
    with open(os.path.join(failed_dir, 'failed.json'), 'w') as f:
        json.dump(failed_msg, f)

    # 2. ACT
    response = client.post('/inbound', json={'action': 'get_all_messages'})
    assert response.status_code == 200
    job_id = response.get_json()['job_id']
    time.sleep(0.1) # Give the filesystem time to create the file

    process_inbound_queue(app)

    data = poll_for_result(client, job_id)

    # 3. ASSERT
    assert data is not None, "Polling for result timed out."
    assert data['status'] == 'complete'
    messages = data['result']
    
    # The inbound message created for the test should be present.
    # The message for the get_all_messages action itself is skipped.
    assert len(messages['inbound']) == 1
    assert messages['inbound'][0]['test'] == 'inbound_data'
    
    assert len(messages['consumed']) == 1
    assert messages['consumed'][0]['test'] == 'consumed_data'
    
    assert len(messages['failed']) == 1
    assert messages['failed'][0]['test'] == 'failed_data'

def test_clear_all_messages_action(client, app):
    """Test the clear_all_messages action."""
    # 1. ARRANGE
    base_path = current_app.config['BASE_QUEUE_PATH']
    inbound_dir = os.path.join(base_path, 'inbound')
    consumed_dir = os.path.join(base_path, 'consumed')
    failed_dir = os.path.join(base_path, 'failed')

    # Create dummy files in each directory to ensure they are cleared.
    with open(os.path.join(inbound_dir, 'dummy_inbound.json'), 'w') as f:
        json.dump({'action': 'dummy_action'}, f)
    with open(os.path.join(consumed_dir, 'dummy_consumed.json'), 'w') as f:
        json.dump({'test': 'dummy'}, f)
    with open(os.path.join(failed_dir, 'dummy_failed.json'), 'w') as f:
        json.dump({'test': 'dummy'}, f)

    # 2. ACT
    response = client.post('/inbound', json={'action': 'clear_all_messages'})
    assert response.status_code == 200
    job_id = response.get_json()['job_id']
    time.sleep(0.1)  # Give the filesystem time to create the file

    process_inbound_queue(app)

    data = poll_for_result(client, job_id)

    # 3. ASSERT
    assert data is not None, "Polling for result timed out."
    assert data['status'] == 'complete'
    assert data['result']['message'] == 'All queues cleared successfully.'
    assert set(data['result']['cleared_queues']) == {'inbound', 'consumed', 'failed'}

    # inbound and failed queues should be empty.
    assert not os.listdir(inbound_dir)
    assert not os.listdir(failed_dir)

    # The consumed queue should only contain the message and result for the
    # 'clear_all_messages' action itself.
    consumed_files = os.listdir(consumed_dir)
    assert len(consumed_files) == 2
    assert any(f.endswith(f'_{job_id}.json') for f in consumed_files)
    assert f'result_{job_id}.json' in consumed_files

def test_clear_all_messages_action_when_empty(client, app):
    """Test that the clear_all_messages action works correctly when queues are already empty."""
    # 1. ARRANGE
    base_path = current_app.config['BASE_QUEUE_PATH']
    inbound_dir = os.path.join(base_path, 'inbound')
    consumed_dir = os.path.join(base_path, 'consumed')
    failed_dir = os.path.join(base_path, 'failed')

    # 2. ACT
    response = client.post('/inbound', json={'action': 'clear_all_messages'})
    assert response.status_code == 200
    job_id = response.get_json()['job_id']
    time.sleep(0.1) # Give the filesystem time to create the file

    process_inbound_queue(app)

    data = poll_for_result(client, job_id)

    # 3. ASSERT
    assert data is not None, "Polling for result timed out."
    assert data['status'] == 'complete'
    assert data['result']['message'] == 'All queues cleared successfully.'
    # Even if empty, the action reports it "cleared" them.
    assert set(data['result']['cleared_queues']) == {'inbound', 'consumed', 'failed'}

    # inbound and failed queues should be empty.
    assert not os.listdir(inbound_dir)
    assert not os.listdir(failed_dir)

    # The consumed queue should only contain the message and result for the
    # 'clear_all_messages' action itself.
    consumed_files = os.listdir(consumed_dir)
    assert len(consumed_files) == 2
    assert any(f.endswith(f'_{job_id}.json') for f in consumed_files)
    assert f'result_{job_id}.json' in consumed_files
