import os
import json
import uuid
import time
import shutil
from flask import Flask, request, jsonify, render_template
from apscheduler.schedulers.background import BackgroundScheduler
import requests
from bs4 import BeautifulSoup

# --- Basic Configuration ---
app = Flask(__name__)

# --- Environment-based Configuration ---
# Get the environment context. Default to 'development' if not set.
APP_ENV = os.environ.get('APP_ENV', 'development')

if APP_ENV == 'production':
    # In production, you might use a more robust path like /var/queues/
    # These are read from environment variables for flexibility.
    BASE_QUEUE_PATH = os.environ.get('QUEUE_BASE_PATH', 'prod_queues')
else:
    # In development, just use local folders.
    BASE_QUEUE_PATH = 'dev_queues'

# Define queue directories based on the environment context
INBOUND_QUEUE_DIR = os.path.join(BASE_QUEUE_PATH, 'inbound')
OUTBOUND_QUEUE_DIR = os.path.join(BASE_QUEUE_PATH, 'outbound')
CONSUMED_DIR = os.path.join(BASE_QUEUE_PATH, 'consumed')  # For processed inbound messages
DOWNLOAD_DIR = 'downloads'


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

    filename = f"{int(time.time() * 1000)}_{job_id}.json"
    filepath = os.path.join(INBOUND_QUEUE_DIR, filename)

    try:
        with open(filepath, 'w') as f:
            json.dump(task, f, indent=4)
        return jsonify({'status': 'received', 'job_id': job_id})
    except IOError as e:
        print(f"Error writing to inbound queue: {e}")
        return jsonify({'status': 'error', 'message': 'Could not save task to queue'}), 500


@app.route('/outbound', methods=['GET'])
def check_task_status():
    """Endpoint for the client to poll for task results."""
    job_id = request.args.get('job_id')
    if not job_id:
        return jsonify({'status': 'error', 'message': 'Job ID is required'}), 400

    result_filepath = os.path.join(OUTBOUND_QUEUE_DIR, f"{job_id}.json")

    if os.path.exists(result_filepath):
        try:
            with open(result_filepath, 'r') as f:
                task_result = json.load(f)

            # Instead of deleting, move the result file to the consumed folder for auditing
            consumed_path = os.path.join(CONSUMED_DIR, f"result_{job_id}.json")
            shutil.move(result_filepath, consumed_path)

            return jsonify(task_result)
        except (IOError, json.JSONDecodeError) as e:
            print(f"Error reading or moving result file: {e}")
            return jsonify({'status': 'error', 'message': 'Could not retrieve result'}), 500
    else:
        return jsonify({'status': 'pending', 'message': 'Job not yet complete.'})


# --- NEW: 404 Error Handler using Templates ---
@app.errorhandler(404)
def page_not_found(e):
    """
    Renders the custom 404 HTML page from the templates folder.
    """
    return render_template('404.html'), 404


# --- Job Processing Logic ---

def write_result_to_outbound(job_id, result_data):
    """Saves a task's result to a JSON file in the outbound directory."""
    filepath = os.path.join(OUTBOUND_QUEUE_DIR, f"{job_id}.json")
    try:
        with open(filepath, 'w') as f:
            json.dump(result_data, f, indent=4)
    except IOError as e:
        print(f"Error writing result for job {job_id}: {e}")


def download_website_recursively(job_id, url, base_path):
    """A sample long-running task: recursively download a website."""
    try:
        os.makedirs(base_path, exist_ok=True)
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        file_path = os.path.join(base_path, 'index.html')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(soup.prettify())
        time.sleep(15)
        result = {
            'job_id': job_id,
            'status': 'complete',
            'result': f'Successfully downloaded content from {url} to {base_path}'
        }
        write_result_to_outbound(job_id, result)
    except Exception as e:
        result = {'job_id': job_id, 'status': 'failed', 'error': str(e)}
        write_result_to_outbound(job_id, result)


def process_inbound_queue():
    """Scheduler job to check the inbound queue and start processing."""
    print("Scheduler waking up to check for tasks...")
    try:
        tasks = sorted(os.listdir(INBOUND_QUEUE_DIR))
        if not tasks:
            return

        task_filename = tasks[0]
        task_filepath = os.path.join(INBOUND_QUEUE_DIR, task_filename)

        task_to_process = None
        try:
            with open(task_filepath, 'r') as f:
                task_to_process = json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            print(f"Could not read or parse task file {task_filename}. Error: {e}")
            shutil.move(task_filepath, os.path.join(CONSUMED_DIR, f"bad_{task_filename}"))
            return

        # Move the file to the consumed directory BEFORE processing
        # This prevents a crash during processing from causing the task to run again
        shutil.move(task_filepath, os.path.join(CONSUMED_DIR, task_filename))

        print(f"Processing task: {task_to_process.get('job_id')}")
        action = task_to_process.get('action')
        job_id = task_to_process.get('job_id')
        params = task_to_process.get('params')

        if action == 'full_recursive_download':
            url = params.get('url')
            if url:
                download_path = os.path.join(DOWNLOAD_DIR, job_id)
                download_website_recursively(job_id, url, download_path)
        else:
            print(f"Unknown action: {action}")
            result = {'job_id': job_id, 'status': 'failed', 'error': 'Unknown action'}
            write_result_to_outbound(job_id, result)

    except Exception as e:
        print(f"An unexpected error occurred in the scheduler: {e}")


# --- Initialize and Run Server ---
if __name__ == '__main__':
    # Ensure all necessary directories exist
    print(f"Application running in '{APP_ENV}' mode.")
    print(f"Using queue base path: '{BASE_QUEUE_PATH}'")
    for dir_path in [INBOUND_QUEUE_DIR, OUTBOUND_QUEUE_DIR, CONSUMED_DIR, DOWNLOAD_DIR, 'static', 'templates']:
        os.makedirs(dir_path, exist_ok=True)

    scheduler = BackgroundScheduler()
    scheduler.add_job(process_inbound_queue, 'interval', seconds=10)
    scheduler.start()
    print("Scheduler started. Server is running.")

    app.run(host='0.0.0.0', port=5000, debug=(APP_ENV == 'development'))