import os
import json
import time
from flask import current_app

def test_get_all_messages_empty(client):
    """Test that getting all messages returns an empty structure when no messages exist."""
    response = client.get('/messages')
    assert response.status_code == 200
    data = response.get_json()
    assert data == {
        'inbound': [],
        'outbound': [],
        'consumed': [],
        'failed': [],
        'processing': []
    }

def test_get_all_messages_with_data(client):
    """Test retrieving messages from all stages."""
    base_path = current_app.config['BASE_QUEUE_PATH']
    stages = ['inbound', 'outbound', 'consumed', 'failed', 'processing']
    
    # Create dummy message files in each stage
    for stage in stages:
        stage_path = os.path.join(base_path, stage)
        os.makedirs(stage_path, exist_ok=True)
        with open(os.path.join(stage_path, f'message_{stage}.json'), 'w') as f:
            json.dump({'id': f'{stage}_msg'}, f)

    response = client.get('/messages')
    assert response.status_code == 200
    data = response.get_json()

    for stage in stages:
        assert len(data[stage]) == 1
        assert data[stage][0]['id'] == f'{stage}_msg'
        assert data[stage][0]['filename'] == f'message_{stage}.json'

def test_clear_all_messages(client):
    """Test clearing all messages from all stages."""
    base_path = current_app.config['BASE_QUEUE_PATH']
    stages = ['inbound', 'outbound', 'consumed', 'failed', 'processing']
    
    # Create dummy message files in each stage
    for stage in stages:
        stage_path = os.path.join(base_path, stage)
        os.makedirs(stage_path, exist_ok=True)
        with open(os.path.join(stage_path, f'message_{stage}.json'), 'w') as f:
            json.dump({'id': f'{stage}_msg'}, f)

    # Verify files exist before clearing
    for stage in stages:
        assert len(os.listdir(os.path.join(base_path, stage))) == 1

    response = client.post('/messages/clear')
    assert response.status_code == 200
    data = response.get_json()

    assert data['status'] == 'success'
    for stage in stages:
        assert data['cleared_messages'][stage] == 1
        assert len(os.listdir(os.path.join(base_path, stage))) == 0

def test_clear_all_messages_empty(client):
    """Test that clearing messages when none exist works correctly."""
    response = client.post('/messages/clear')
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'
    assert data['cleared_messages'] == {
        'inbound': 0,
        'outbound': 0,
        'consumed': 0,
        'failed': 0,
        'processing': 0
    }
