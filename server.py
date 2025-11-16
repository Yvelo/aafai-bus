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
QUEUE_PEREMPTION_DAYS = 7

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
        scheduler.add_job(func=purge_old_files, args=[app], trigger='cron', hour=3, id='purge_old_files')
        atexit.register(lambda: scheduler.shutdown())
        scheduler.start()
        logging.info("Scheduler started with idle check and daily purge enabled.")

    # --- Register Routes ---
    @app.route('/inbound', methods=['POST'])
    def inbound_route():
        # Update activity timestamp only on inbound requests
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
            shutil.move(result_filepath, os.path.join(consumed_dir, f"result_{job_id}.json"))
            return jsonify(task_result)
        except (IOError, json.JSONDecodeError) as e:
            logging.error(f"Error reading or moving result file: {e}")
            return jsonify({'status': 'error', 'message': 'Could not retrieve result'}), 500
    else:
        return jsonify({'status': 'pending', 'message': 'Job not yet complete.'})

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
    """Scheduler job to process tasks within a created app context."""
    with app.app_context():
        base_path = current_app.config['BASE_QUEUE_PATH']
        inbound_queue_dir = os.path.join(base_path, 'inbound')
        if not os.path.exists(inbound_queue_dir) or not os.listdir(inbound_queue_dir):
            return

        logging.info("Scheduler worker checking for tasks...")
        consumed_dir = os.path.join(base_path, 'consumed')
        failed_dir = os.path.join(base_path, 'failed')
        download_dir = current_app.config['DOWNLOAD_DIR']
        actions_dir = current_app.config['ACTIONS_DIR']

        task_filename = sorted(os.listdir(inbound_queue_dir))[0]
        task_filepath = os.path.join(inbound_queue_dir, task_filename)
        consumed_filepath = os.path.join(consumed_dir, task_filename)

        try:
            shutil.move(task_filepath, consumed_filepath)
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
            with open(consumed_filepath, 'r') as f:
                task_to_process = json.load(f)

            job_id = task_to_process.get('job_id', 'unknown')
            action_name = task_to_process.get('action')
            params = task_to_process.get('params')
            logging.info(f"Processing job {job_id} for action '{action_name}'")

            try:
                action_module = importlib.import_module(f"{actions_dir}.{action_name}")
            except ModuleNotFoundError:
                raise ValueError(f"Action '{action_name}' not found or is not a valid module.")

            action_module.execute(job_id, params, download_dir, write_result_to_outbound)

        except (json.JSONDecodeError, ValueError) as e:
            error_message = f"Failed to process task {task_filename} due to bad input: {e}"
            logging.warning(error_message)
            if task_to_process and task_to_process.get('job_id'):
                job_id = task_to_process.get('job_id')
            
            result = {'job_id': job_id, 'status': 'failed', 'error': str(e)}
            write_result_to_outbound(job_id, result)
            os.makedirs(failed_dir, exist_ok=True)
            shutil.move(consumed_filepath, os.path.join(failed_dir, task_filename))

        except Exception as e:
            error_message = f"An unexpected error occurred while processing task {task_filename}: {e}"
            logging.error(error_message, exc_info=True)
            if task_to_process and task_to_process.get('job_id'):
                job_id = task_to_process.get('job_id')
            
            result = {'job_id': job_id, 'status': 'failed', 'error': str(e)}
            write_result_to_outbound(job_id, result)
            os.makedirs(failed_dir, exist_ok=True)
            shutil.move(consumed_filepath, os.path.join(failed_dir, task_filename))

def check_idle_shutdown(app):
    """
    Checks if the server has been idle AND the inbound queue is empty.
    If both conditions are met, it initiates a graceful shutdown.
    """
    with app.app_context():
        base_path = current_app.config['BASE_QUEUE_PATH']
        inbound_queue_dir = os.path.join(base_path, 'inbound')
        timestamp_file = os.path.join(base_path, 'last_api_call.timestamp')

        if os.path.exists(inbound_queue_dir) and os.listdir(inbound_queue_dir):
            logging.info("Idle check: Inbound queue is not empty. Deferring shutdown.")
            return

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

def purge_old_files(app):
    """
    Scheduled job to delete files and directories older than QUEUE_PEREMPTION_DAYS.
    """
    with app.app_context():
        logging.info("Daily purge job started.")
        base_path = current_app.config['BASE_QUEUE_PATH']
        download_dir = current_app.config['DOWNLOAD_DIR']
        
        cutoff = time.time() - (QUEUE_PEREMPTION_DAYS * 24 * 60 * 60)
        
        dirs_to_purge = [
            os.path.join(base_path, 'inbound'),
            os.path.join(base_path, 'outbound'),
            os.path.join(base_path, 'consumed'),
            os.path.join(base_path, 'failed'),
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
                            logging.info(f"Removed old directory: {item_path}")
                        else:
                            os.remove(item_path)
                            logging.info(f"Removed old file: {item_path}")
                except FileNotFoundError:
                    logging.warning(f"Could not find {item_path} during purge; it may have been deleted already.")
                except Exception as e:
                    logging.error(f"Error purging {item_path}: {e}", exc_info=True)
        
        logging.info("Daily purge job finished.")

# This block is now only used for local development.
if __name__ == '__main__':
    app = create_app()
    logging.info("Starting Flask development server.")
    app.run(host='0.0.0.0', port=5000, debug=(os.environ.get('APP_ENV') == 'development'))