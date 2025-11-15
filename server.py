import os
import json
import uuid
import time
import shutil
import atexit
import importlib
import logging
from flask import Flask, request, jsonify, render_template
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor

# --- Logging Configuration ---
# Configure logging immediately. This ensures it's active when Gunicorn imports the file.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Basic Configuration ---
app = Flask(__name__)

# --- Centralized Application Configuration ---
APP_ENV = os.environ.get('APP_ENV', 'development')
if APP_ENV == 'production':
    base_path = os.environ.get('QUEUE_BASE_PATH', 'prod_queues')
else:
    base_path = 'dev_queues'

app.config['BASE_QUEUE_PATH'] = base_path
app.config['DOWNLOAD_DIR'] = 'downloads'
app.config['ACTIONS_DIR'] = 'actions'

# --- Application Initialization (Moved from __main__) ---
# This code will now run when the file is imported by Gunicorn or run directly.
logging.info(f"Application starting in '{APP_ENV}' mode.")
base_queue_path = app.config['BASE_QUEUE_PATH']
logging.info(f"Using queue base path: '{base_queue_path}'")

# Create necessary directories on startup
for dir_name in ['inbound', 'outbound', 'consumed', 'failed']:
    os.makedirs(os.path.join(base_queue_path, dir_name), exist_ok=True)
for dir_path in [app.config['DOWNLOAD_DIR'], 'static', 'templates', app.config['ACTIONS_DIR']]:
    os.makedirs(dir_path, exist_ok=True)

# --- Scheduler Configuration ---
executors = {'default': ThreadPoolExecutor(5)}
job_defaults = {'coalesce': False, 'max_instances': 5}
scheduler = BackgroundScheduler(executors=executors, job_defaults=job_defaults)
scheduler.add_job(func=lambda: process_inbound_queue(), trigger='interval', seconds=5)

# Register a graceful shutdown for the scheduler
atexit.register(lambda: scheduler.shutdown())

scheduler.start()
logging.info("Scheduler started with concurrent processing enabled.")


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

    inbound_queue_dir = os.path.join(app.config['BASE_QUEUE_PATH'], 'inbound')
    filename = f"{int(time.time() * 1000)}_{job_id}.json"
    filepath = os.path.join(inbound_queue_dir, filename)

    try:
        os.makedirs(inbound_queue_dir, exist_ok=True)
        with open(filepath, 'w') as f:
            json.dump(task, f, indent=4)
        return jsonify({'status': 'received', 'job_id': job_id})
    except IOError as e:
        logging.error(f"Error writing to inbound queue: {e}")
        return jsonify({'status': 'error', 'message': 'Could not save task to queue'}), 500


@app.route('/outbound', methods=['GET'])
def check_task_status():
    """Endpoint for the client to poll for task results."""
    job_id = request.args.get('job_id')
    if not job_id:
        return jsonify({'status': 'error', 'message': 'Job ID is required'}), 400

    base_path = app.config['BASE_QUEUE_PATH']
    outbound_queue_dir = os.path.join(base_path, 'outbound')
    consumed_dir = os.path.join(base_path, 'consumed')
    result_filepath = os.path.join(outbound_queue_dir, f"{job_id}.json")

    if os.path.exists(result_filepath):
        try:
            with open(result_filepath, 'r') as f:
                task_result = json.load(f)

            os.makedirs(consumed_dir, exist_ok=True)
            consumed_path = os.path.join(consumed_dir, f"result_{job_id}.json")
            shutil.move(result_filepath, consumed_path)

            return jsonify(task_result)
        except (IOError, json.JSONDecodeError) as e:
            logging.error(f"Error reading or moving result file: {e}")
            return jsonify({'status': 'error', 'message': 'Could not retrieve result'}), 500
    else:
        return jsonify({'status': 'pending', 'message': 'Job not yet complete.'})


# --- 404 Error Handler ---
@app.errorhandler(404)
def page_not_found(e):
    """Renders the custom 404 HTML page from the templates folder."""
    return render_template('404.html'), 404


# --- Job Processing Logic ---

def write_result_to_outbound(job_id, result_data):
    """Saves a task's result to a JSON file in the outbound directory."""
    outbound_queue_dir = os.path.join(app.config['BASE_QUEUE_PATH'], 'outbound')
    filepath = os.path.join(outbound_queue_dir, f"{job_id}.json")
    try:
        os.makedirs(outbound_queue_dir, exist_ok=True)
        with open(filepath, 'w') as f:
            json.dump(result_data, f, indent=4)
    except IOError as e:
        logging.error(f"Error writing result for job {job_id}: {e}")


def process_inbound_queue():
    """Scheduler job to check for and process a single task from the inbound queue."""
    # Use app_context to ensure Flask configurations are available in the thread
    with app.app_context():
        base_path = app.config['BASE_QUEUE_PATH']
        inbound_queue_dir = os.path.join(base_path, 'inbound')
        consumed_dir = os.path.join(base_path, 'consumed')
        failed_dir = os.path.join(base_path, 'failed')
        download_dir = app.config['DOWNLOAD_DIR']
        actions_dir = app.config['ACTIONS_DIR']

        if not os.path.exists(inbound_queue_dir):
            return

        logging.info("Scheduler worker checking for tasks...")
        tasks = sorted(os.listdir(inbound_queue_dir))
        if not tasks:
            return

        task_filename = tasks[0]
        task_filepath = os.path.join(inbound_queue_dir, task_filename)
        consumed_filepath = os.path.join(consumed_dir, task_filename)

        try:
            os.makedirs(consumed_dir, exist_ok=True)
            shutil.move(task_filepath, consumed_filepath)
        except FileNotFoundError:
            logging.info(f"Task {task_filename} already claimed. Skipping.")
            return
        except Exception as e:
            logging.error(f"Error claiming task {task_filename}: {e}")
            return

        logging.info(f"Worker claimed task: {task_filename}")
        task_to_process = None
        try:
            with open(consumed_filepath, 'r') as f:
                task_to_process = json.load(f)

            job_id = task_to_process.get('job_id')
            action_name = task_to_process.get('action')
            params = task_to_process.get('params')

            logging.info(f"Processing job {job_id} for action '{action_name}'")

            action_module_path = f"{actions_dir}.{action_name}"
            action_module = importlib.import_module(action_module_path)
            action_module.execute(job_id, params, download_dir, write_result_to_outbound)

        except (ModuleNotFoundError, AttributeError):
            error_message = f"Action '{action_name}' not found or invalid."
            logging.error(error_message)
            result = {'job_id': job_id, 'status': 'failed', 'error': error_message}
            write_result_to_outbound(job_id, result)
            os.makedirs(failed_dir, exist_ok=True)
            shutil.move(consumed_filepath, os.path.join(failed_dir, task_filename))
        except Exception as e:
            logging.error(f"Failed to process task {task_filename}: {e}", exc_info=True)
            job_id = task_to_process.get('job_id') if task_to_process else "unknown"
            result = {'job_id': job_id, 'status': 'failed', 'error': str(e)}
            write_result_to_outbound(job_id, result)
            os.makedirs(failed_dir, exist_ok=True)
            shutil.move(consumed_filepath, os.path.join(failed_dir, task_filename))


# --- Development Server ---
if __name__ == '__main__':
    # This block is now only used for local development.
    # Gunicorn does not run this.
    logging.info("Starting Flask development server.")
    app.run(host='0.0.0.0', port=5000, debug=(APP_ENV == 'development'))
