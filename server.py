import os
import json
import uuid
import time
import shutil
import atexit
import importlib
import logging
import signal
from flask import Flask, request, jsonify, render_template, current_app
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor

# --- Constants ---
MAX_IDLE_TIME_IN_SECONDS = 300

def create_app(testing=False):
    """Application factory for the Flask app."""
    app = Flask(__name__)

    # --- Logging Configuration ---
    log_level = logging.ERROR if testing else logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s', force=True)

    # --- App Configuration ---
    APP_ENV = os.environ.get('APP_ENV', 'development')
    if testing:
        base_path = 'test_queues'
    elif APP_ENV == 'production':
        base_path = os.environ.get('QUEUE_BASE_PATH', 'prod_queues')
    else:
        base_path = 'dev_queues'

    app.config['BASE_QUEUE_PATH'] = base_path
    app.config['DOWNLOAD_DIR'] = 'downloads'
    app.config['ACTIONS_DIR'] = 'actions'
    app.config['TESTING'] = testing

    # --- Initialization ---
    with app.app_context():
        logging.info(f"Application starting in '{'testing' if testing else APP_ENV}' mode.")
        logging.info(f"Using queue base path: '{current_app.config['BASE_QUEUE_PATH']}'")
        for dir_name in ['inbound', 'outbound', 'consumed', 'failed']:
            os.makedirs(os.path.join(current_app.config['BASE_QUEUE_PATH'], dir_name), exist_ok=True)
        for dir_path in [current_app.config['DOWNLOAD_DIR'], 'static', 'templates', current_app.config['ACTIONS_DIR']]:
            os.makedirs(dir_path, exist_ok=True)
        
        # Initialize timestamp only if it doesn't exist
        timestamp_file = os.path.join(current_app.config['BASE_QUEUE_PATH'], 'last_api_call.timestamp')
        if not os.path.exists(timestamp_file):
            with open(timestamp_file, 'w') as f:
                f.write(str(time.time()))

    # --- Scheduler ---
    if not testing:
        executors = {'default': ThreadPoolExecutor(5)}
        job_defaults = {'coalesce': False, 'max_instances': 5}
        scheduler = BackgroundScheduler(executors=executors, job_defaults=job_defaults)
        scheduler.add_job(func=process_inbound_queue, args=[app], trigger='interval', seconds=5, id='process_queue')
        scheduler.add_job(func=check_idle_shutdown, args=[app], trigger='interval', seconds=30, id='idle_check')
        atexit.register(lambda: scheduler.shutdown())
        scheduler.start()
        logging.info("Scheduler started with idle check enabled.")

    # --- Register Routes ---
    @app.route('/inbound', methods=['POST'])
    def inbound_route():
        # This is the only place we should update the activity timestamp
        timestamp_file = os.path.join(current_app.config['BASE_QUEUE_PATH'], 'last_api_call.timestamp')
        with open(timestamp_file, 'w') as f:
            f.write(str(time.time()))
        return receive_task()

    @app.route('/outbound', methods=['GET'])
    def outbound_route():
        return check_task_status()

    @app.errorhandler(404)
    def not_found_error(e):
        return page_not_found(e)

    return app

# --- API and Logic (defined outside the factory) ---

def receive_task():
    """Handles creating a new task from an inbound request."""
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

    inbound_queue_dir = os.path.join(current_app.config['BASE_QUEUE_PATH'], 'inbound')
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

def check_task_status():
    """Handles checking the status of a task."""
    # ... (implementation remains the same)
    pass

def page_not_found(e):
    """Renders the custom 404 HTML page."""
    return render_template('404.html'), 404

def write_result_to_outbound(job_id, result_data):
    """Saves a task's result to a JSON file."""
    # ... (implementation remains the same)
    pass

def process_inbound_queue(app):
    """Scheduler job to process tasks."""
    # ... (implementation remains the same)
    pass

def check_idle_shutdown(app):
    """
    Checks if the server has been idle AND the inbound queue is empty.
    If both conditions are met, it initiates a graceful shutdown.
    """
    with app.app_context():
        base_path = current_app.config['BASE_QUEUE_PATH']
        inbound_queue_dir = os.path.join(base_path, 'inbound')
        timestamp_file = os.path.join(base_path, 'last_api_call.timestamp')

        # 1. Check if the inbound queue is empty
        if os.path.exists(inbound_queue_dir) and os.listdir(inbound_queue_dir):
            logging.info("Idle check: Inbound queue is not empty. Deferring shutdown.")
            return

        # 2. If the queue is empty, check for idleness
        try:
            with open(timestamp_file, 'r') as f:
                last_api_call_time = float(f.read().strip())
            
            idle_time = time.time() - last_api_call_time
            logging.info(f"Idle check: Queue is empty. Last inbound call was {idle_time:.2f} seconds ago.")

            if idle_time > MAX_IDLE_TIME_IN_SECONDS:
                logging.warning(
                    f"Server has been idle for more than {MAX_IDLE_TIME_IN_SECONDS} seconds and queue is empty. "
                    "Initiating graceful shutdown."
                )
                master_pid = os.getppid()
                logging.info(f"Sending SIGTERM to Gunicorn master process (PID: {master_pid}).")
                os.kill(master_pid, signal.SIGTERM)

        except (FileNotFoundError, ValueError, IOError) as e:
            logging.warning(f"Could not check idle time: {e}")

# This block is now only used for local development.
if __name__ == '__main__':
    app = create_app()
    logging.info("Starting Flask development server.")
    app.run(host='0.0.0.0', port=5000, debug=(os.environ.get('APP_ENV') == 'development'))
