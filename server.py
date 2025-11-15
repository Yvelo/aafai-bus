import os
import json
import uuid
import time
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

# --- Basic Configuration ---
app = Flask(__name__)
# Use a simple file-based system for our queues
INBOUND_QUEUE_FILE = 'inbound_queue.json'
OUTBOUND_QUEUE_FILE = 'outbound_queue.json'
DOWNLOAD_DIR = 'downloads'


# --- Queue Management Functions ---

def get_queue(file_path):
    """Reads a queue file, ensuring it's not corrupt."""
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def save_queue(file_path, data):
    """Saves data to a queue file."""
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=4)


# --- API Endpoints ---

@app.route('/inbound', methods=['POST'])
def receive_task():
    """Endpoint to receive a new task and add it to the inbound queue."""
    data = request.get_json()
    if not data or 'action' not in data:
        return jsonify({'status': 'error', 'message': 'Invalid request'}), 400

    job_id = str(uuid.uuid4())
    task = {
        'job_id': job_id,
        'action': data['action'],
        'params': data.get('params', {}),
        'status': 'pending',
        'received_at': time.time()
    }

    inbound_queue = get_queue(INBOUND_QUEUE_FILE)
    inbound_queue.append(task)
    save_queue(INBOUND_QUEUE_FILE, inbound_queue)

    return jsonify({'status': 'received', 'job_id': job_id})


@app.route('/outbound', methods=['GET'])
def check_task_status():
    """Endpoint for the client to poll for task results."""
    job_id = request.args.get('job_id')
    if not job_id:
        return jsonify({'status': 'error', 'message': 'Job ID is required'}), 400

    outbound_queue = get_queue(OUTBOUND_QUEUE_FILE)

    # Find the result and remove it from the queue upon retrieval
    task_result = None
    remaining_tasks = []
    for task in outbound_queue:
        if task.get('job_id') == job_id:
            task_result = task
        else:
            remaining_tasks.append(task)

    if task_result:
        save_queue(OUTBOUND_QUEUE_FILE, remaining_tasks)  # Update queue
        return jsonify(task_result)
    else:
        return jsonify({'status': 'pending', 'message': 'Job not yet complete.'})


# --- Job Processing Logic ---

def download_website_recursively(job_id, url, base_path):
    """A sample long-running task: recursively download a website."""
    try:
        if not os.path.exists(base_path):
            os.makedirs(base_path)

        # Basic recursive download logic (for demonstration)
        # In a real-world scenario, this would be far more robust.
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')

        file_path = os.path.join(base_path, 'index.html')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(soup.prettify())

        # This is a highly simplified example. A full recursive download is complex.
        # It would need to handle CSS, JS, images, and avoid re-downloading.

        # Simulate a long process
        time.sleep(15)  # Simulate work

        # Add result to the outbound queue
        outbound_queue = get_queue(OUTBOUND_QUEUE_FILE)
        outbound_queue.append({
            'job_id': job_id,
            'status': 'complete',
            'result': f'Successfully downloaded content from {url} to {base_path}'
        })
        save_queue(OUTBOUND_QUEUE_FILE, outbound_queue)

    except Exception as e:
        # Log failures to the outbound queue as well
        outbound_queue = get_queue(OUTBOUND_QUEUE_FILE)
        outbound_queue.append({
            'job_id': job_id,
            'status': 'failed',
            'error': str(e)
        })
        save_queue(OUTBOUND_QUEUE_FILE, outbound_queue)


def process_inbound_queue():
    """Scheduler job to check the inbound queue and start processing."""
    print("Scheduler waking up to check for tasks...")
    inbound_queue = get_queue(INBOUND_QUEUE_FILE)
    if not inbound_queue:
        return

    # Process one task at a time (FIFO)
    task_to_process = inbound_queue.pop(0)
    save_queue(INBOUND_QUEUE_FILE, inbound_queue)  # Update queue immediately

    print(f"Processing task: {task_to_process['job_id']}")

    action = task_to_process.get('action')
    job_id = task_to_process.get('job_id')
    params = task_to_process.get('params')

    if action == 'full_recursive_download':
        url = params.get('url')
        if url:
            download_path = os.path.join(DOWNLOAD_DIR, job_id)
            download_website_recursively(job_id, url, download_path)
    else:
        # Handle other actions or unknown actions
        print(f"Unknown action: {action}")
        # Optionally, put a failure message in the outbound queue
        outbound_queue = get_queue(OUTBOUND_QUEUE_FILE)
        outbound_queue.append({'job_id': job_id, 'status': 'failed', 'error': 'Unknown action'})
        save_queue(OUTBOUND_QUEUE_FILE, outbound_queue)


# --- Initialize and Run Server ---
if __name__ == '__main__':
    # Ensure queue files exist
    if not os.path.exists(INBOUND_QUEUE_FILE): save_queue(INBOUND_QUEUE_FILE, [])
    if not os.path.exists(OUTBOUND_QUEUE_FILE): save_queue(OUTBOUND_QUEUE_FILE, [])
    if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)

    # Setup and start the background scheduler
    scheduler = BackgroundScheduler()
    # Check the queue every 10 seconds
    scheduler.add_job(process_inbound_queue, 'interval', seconds=10)
    scheduler.start()
    print("Scheduler started. Server is running.")

    # Start the Flask web server
    # For production, use a proper WSGI server like Gunicorn or Waitress.
    # Use 0.0.0.0 to make it accessible on your network.
    app.run(host='0.0.0.0', port=5000, debug=False)