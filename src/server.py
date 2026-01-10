import os
import sys
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

# --- Path Setup ---
SRC_ROOT = os.path.abspath(os.path.dirname(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SRC_ROOT, '..'))
sys.path.insert(0, PROJECT_ROOT)

# --- Constants ---
MAX_IDLE_TIME_IN_SECONDS = 1800
QUEUE_PEREMPTION_DAYS = 7

def create_app(testing=False):
    """Application factory for the Flask app."""
    app = Flask(__name__,
                static_folder=os.path.join(PROJECT_ROOT, 'static'),
                template_folder=os.path.join(PROJECT_ROOT, 'templates'))

    # --- Logging Configuration ---
    log_level = logging.ERROR if testing else logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s', force=True)

    # --- App Configuration ---
    APP_ENV = os.environ.get('APP_ENV', 'development')
    if testing:
        base_path = os.environ.get('QUEUE_BASE_PATH', os.path.join(PROJECT_ROOT, 'test_queues'))
    elif APP_ENV == 'production':
        base_path = os.environ.get('QUEUE_BASE_PATH', os.path.join(PROJECT_ROOT, 'data'))
    else:
        base_path = os.path.join(PROJECT_ROOT, 'dev_queues')

    app.config['BASE_QUEUE_PATH'] = base_path
    app.config['DOWNLOAD_DIR'] = os.path.join(PROJECT_ROOT, 'downloads')
    app.config['ACTIONS_DIR'] = os.path.join(SRC_ROOT, 'actions') # Correctly point to src/actions
    app.config['TESTING'] = testing

    # --- Initialization ---
    with app.app_context():
        logging.info(f"Application starting in '{'testing' if testing else APP_ENV}' mode.")
        logging.info(f"Using queue base path: '{current_app.config['BASE_QUEUE_PATH']}'")
        
        os.makedirs(current_app.config['BASE_QUEUE_PATH'], exist_ok=True)
        os.makedirs(current_app.config['DOWNLOAD_DIR'], exist_ok=True)
        for dir_name in ['inbound', 'outbound', 'consumed', 'failed', 'processing']:
            os.makedirs(os.path.join(current_app.config['BASE_QUEUE_PATH'], dir_name), exist_ok=True)
        
        os.makedirs(app.config['ACTIONS_DIR'], exist_ok=True)
        
        timestamp_file = os.path.join(current_app.config['BASE_QUEUE_PATH'], 'last_api_call.timestamp')
        with open(timestamp_file, 'w') as f:
            f.write(str(time.time()))

    # --- Scheduler & Startup Jobs ---
    if not testing:
        logging.info("Running purge job on startup...")
        purge_old_files(app)

        executors = {'default': ThreadPoolExecutor(5)}
        job_defaults = {'coalesce': False, 'max_instances': 5}
        scheduler = BackgroundScheduler(executors=executors, job_defaults=job_defaults)
        scheduler.add_job(func=process_inbound_queue, args=[app], trigger='interval', seconds=5, id='process_queue')
        scheduler.add_job(func=check_idle_shutdown, args=[app], trigger='interval', seconds=30, id='idle_check')
        scheduler.add_job(func=purge_old_files, args=[app], trigger='cron', hour=3, id='purge_old_files_daily')
        atexit.register(lambda: scheduler.shutdown())
        scheduler.start()
        logging.info("Scheduler started with recurring jobs enabled.")

    # --- Register Routes ---
    @app.route('/inbound', methods=['POST'])
    def inbound_route():
        timestamp_file = os.path.join(current_app.config['BASE_QUEUE_PATH'], 'last_api_call.timestamp')
        with open(timestamp_file, 'w') as f:
            f.write(str(time.time()))
        return receive_task()

    @app.route('/outbound', methods=['GET'])
    def outbound_route():
        timestamp_file = os.path.join(current_app.config['BASE_QUEUE_PATH'], 'last_api_call.timestamp')
        with open(timestamp_file, 'w') as f:
            f.write(str(time.time()))
        return check_task_status()

    @app.errorhandler(404)
    def not_found_error(e):
        return page_not_found(e)

    return app

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
        'status': 'Pending',
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
    job_id = request.args.get('job_id')
    if not job_id:
        return jsonify({'status': 'error', 'message': 'Job ID is required'}), 400

    base_path = current_app.config['BASE_QUEUE_PATH']
    outbound_queue_dir = os.path.join(base_path, 'outbound')
    consumed_dir = os.path.join(base_path, 'consumed')
    result_filepath = os.path.join(outbound_queue_dir, f"{job_id}.json")

    if os.path.exists(result_filepath):
        try:
            with open(result_filepath, 'r') as f:
                task_result = json.load(f)
            os.makedirs(consumed_dir, exist_ok=True)
            # Use the original task filename for consistency in consumed folder
            consumed_filename = f"result_{job_id}.json"
            shutil.move(result_filepath, os.path.join(consumed_dir, consumed_filename))
            return jsonify(task_result)
        except (IOError, json.JSONDecodeError) as e:
            logging.error(f"Error reading or moving result file: {e}")
            return jsonify({'status': 'error', 'message': 'Could not retrieve result'}), 500
    else:
        # Check if the job failed and is in the failed queue
        failed_dir = os.path.join(base_path, 'failed')
        for f in os.listdir(failed_dir):
            if job_id in f:
                return jsonify({'status': 'failed', 'message': 'Job failed during processing.'})
        return jsonify({'status': 'Pending', 'message': 'Job not yet complete.'})


def page_not_found(e):
    """Renders the custom 404 HTML page."""
    return render_template('404.html'), 404

def write_result_to_outbound(job_id, result_data):
    """Saves a task's result to a JSON file within an app context."""
    outbound_queue_dir = os.path.join(current_app.config['BASE_QUEUE_PATH'], 'outbound')
    filepath = os.path.join(outbound_queue_dir, f"{job_id}.json")
    try:
        os.makedirs(outbound_queue_dir, exist_ok=True)
        with open(filepath, 'w') as f:
            json.dump(result_data, f, indent=4)
    except IOError as e:
        logging.error(f"Error writing result for job {job_id}: {e}")

def process_inbound_queue(app):
    """Scheduler job to process all tasks in the inbound queue."""
    with app.app_context():
        base_path = current_app.config['BASE_QUEUE_PATH']
        inbound_queue_dir = os.path.join(base_path, 'inbound')
        
        if not os.path.exists(inbound_queue_dir) or not os.listdir(inbound_queue_dir):
            return

        logging.info("Scheduler worker checking for tasks...")
        
        # Process all files in the directory, not just the first one
        for task_filename in sorted(os.listdir(inbound_queue_dir)):
            process_single_task(task_filename, app.app_context)

def process_single_task(task_filename, app_context):
    """Processes a single task file from the inbound queue."""
    with app_context():
        base_path = current_app.config['BASE_QUEUE_PATH']
        inbound_queue_dir = os.path.join(base_path, 'inbound')
        processing_dir = os.path.join(base_path, 'processing')
        consumed_dir = os.path.join(base_path, 'consumed')
        failed_dir = os.path.join(base_path, 'failed')
        download_dir = current_app.config['DOWNLOAD_DIR']
        actions_dir_path = current_app.config['ACTIONS_DIR']
        
        task_filepath = os.path.join(inbound_queue_dir, task_filename)
        processing_filepath = os.path.join(processing_dir, task_filename)

        try:
            shutil.move(task_filepath, processing_filepath)
        except FileNotFoundError:
            logging.info(f"Task {task_filename} already claimed. Skipping.")
            return
        except Exception as e:
            logging.error(f"Error claiming task {task_filename}: {e}")
            return

        logging.info(f"Worker claimed task: {task_filename}")
        task_to_process = None
        job_id = "unknown"
        try:
            with open(processing_filepath, 'r') as f:
                task_to_process = json.load(f)

            job_id = task_to_process.get('job_id', 'unknown')
            action_name = task_to_process.get('action')
            params = task_to_process.get('params', {})
            
            if not action_name:
                raise ValueError("Task file does not contain an 'action'.")

            # Add base_path to params for actions
            params['base_path'] = base_path

            logging.info(f"Processing job {job_id} for action '{action_name}'")

            # Dynamically import from 'src.actions'
            try:
                action_module = importlib.import_module(f"src.actions.{action_name}")
            except ModuleNotFoundError:
                raise ValueError(f"Action '{action_name}' not found in 'src/actions'.")

            # Pass the app context to the action
            action_module.execute(job_id, params, download_dir, write_result_to_outbound)

            consumed_filepath = os.path.join(consumed_dir, task_filename)
            shutil.move(processing_filepath, consumed_filepath)

        except Exception as e:
            error_message = f"An unexpected error occurred while processing task {task_filename}: {e}"
            logging.error(error_message, exc_info=True)
            if task_to_process and task_to_process.get('job_id'):
                job_id = task_to_process.get('job_id')
            
            result = {'job_id': job_id, 'status': 'failed', 'error': str(e)}
            write_result_to_outbound(job_id, result)
            
            if os.path.exists(processing_filepath):
                shutil.move(processing_filepath, os.path.join(failed_dir, task_filename))

def check_idle_shutdown(app):
    """
    Checks if the server has been idle AND the inbound and processing queues are empty.
    If both conditions are met, it initiates a graceful VM shutdown.
    """
    with app.app_context():
        base_path = current_app.config['BASE_QUEUE_PATH']
        inbound_queue_dir = os.path.join(base_path, 'inbound')
        processing_dir = os.path.join(base_path, 'processing')
        timestamp_file = os.path.join(base_path, 'last_api_call.timestamp')

        inbound_is_empty = not (os.path.exists(inbound_queue_dir) and os.listdir(inbound_queue_dir))
        processing_is_empty = not (os.path.exists(processing_dir) and os.listdir(processing_dir))

        if not inbound_is_empty or not processing_is_empty:
            return

        try:
            with open(timestamp_file, 'r') as f:
                last_api_call_time = float(f.read().strip())
            
            idle_time = time.time() - last_api_call_time
            if idle_time > MAX_IDLE_TIME_IN_SECONDS:
                logging.warning(
                    f"Server has been idle for more than {MAX_IDLE_TIME_IN_SECONDS} seconds and queues are empty. "
                    "Initiating VM power off."
                )
                # In a real scenario, you'd use a more robust method.
                # For this example, we'll just log it.
                # os.system('sudo /sbin/shutdown --poweroff now')

        except (FileNotFoundError, ValueError, IOError) as e:
            logging.warning(f"Could not check idle time: {e}")

def purge_old_files(app):
    """
    Deletes files and directories older than QUEUE_PEREMPTION_DAYS.
    """
    with app.app_context():
        logging.info("Purge job started.")
        base_path = current_app.config['BASE_QUEUE_PATH']
        download_dir = current_app.config['DOWNLOAD_DIR']
        
        cutoff = time.time() - (QUEUE_PEREMPTION_DAYS * 24 * 60 * 60)
        
        dirs_to_purge = [
            os.path.join(base_path, 'inbound'),
            os.path.join(base_path, 'outbound'),
            os.path.join(base_path, 'consumed'),
            os.path.join(base_path, 'failed'),
            os.path.join(base_path, 'processing'),
            download_dir
        ]

        for directory in dirs_to_purge:
            if not os.path.exists(directory):
                continue
            
            logging.info(f"Purging old files from: {directory}")
            for item_name in os.listdir(directory):
                item_path = os.path.join(directory, item_name)
                try:
                    item_mod_time = os.path.getmtime(item_path)
                    if item_mod_time < cutoff:
                        if os.path.isdir(item_path):
                            shutil.rmtree(item_path)
                        else:
                            os.remove(item_path)
                except Exception as e:
                    logging.error(f"Error purging {item_path}: {e}", exc_info=True)
        
        logging.info("Purge job finished.")

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=(os.environ.get('APP_ENV') == 'development'))
