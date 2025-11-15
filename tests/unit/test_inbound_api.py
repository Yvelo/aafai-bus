# tests/unit/test_inbound_api.py
import json

def test_receive_task_success(client):
    """Test the /inbound endpoint with valid data."""
    response = client.post('/inbound', data=json.dumps({
        'action': 'test_action',
        'params': {'key': 'value'}
    }), content_type='application/json')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'received'
    assert 'job_id' in data

def test_receive_task_invalid_request(client):
    """Test the /inbound endpoint with invalid data."""
    response = client.post('/inbound', data=json.dumps({}), content_type='application/json')
    assert response.status_code == 400
    data = json.loads(response.data)
    assert data['status'] == 'error'

def test_check_task_status_pending(client):
    """Test the /outbound endpoint for a pending job."""
    response = client.get('/outbound?job_id=non_existent_id')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'pending'