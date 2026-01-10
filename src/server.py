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
# This ensures the app can be run from anywhere and still find its modules.
SRC_ROOT = os.path.abspath(os.path.dirname(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SRC_ROOT, '..'))
sys.path.insert(0, PROJECT_ROOT)

# --- Constants ---
MAX_IDLE_TIME_IN_SECONDS = 1800
QUEUE_PEREMPTION_DAYS = 7

def create_app(testing=False):
    """Application factory for the Flask app."""
    # Note: static/template folders are now relative to the PROJECT_ROOT, not the app's root.
    app = Flask(__name__, 
                static_folder=os.path.join(PROJECT_ROOT, 'static'),
                template_folder=os.path.join(PROJECT_ROOT, 'templates'))

    # --- Logging Configuration ---
    log_level = logging.ERROR if testing else logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s', force=True)

    # --- App Configuration ---
    APP_ENV = os.environ.get('APP_ENV', 'development')
    if testing:
        # Test data lives in the project root
        base_path = os.path.join(PROJECT_ROOT, 'test_queues')
    elif APP_ENV == 'production':
        # Production data lives in a dedicated 'data' directory in the project root
        base_path = os.environ.get('QUEUE_BASE_PATH', os.path.join(PROJECT_ROOT, 'data'))
    else:
        # Development data lives in the project root
        base_path = os.path.join(PROJECT_ROOT, 'dev_queues')

    app.config['BASE_QUEUE_PATH'] = base_path
    # All data directories are now correctly placed in the project root, outside 'src'
    app.config['DOWNLOAD_DIR'] = os.path.join(PROJECT_ROOT, 'downloads')
    app.config['ACTIONS_DIR'] = 'actions'
    app.config['TESTING'] = testing

    # --- Initialization ---
    with app.app_context():
        logging.info(f"Application starting in '{'testing' if testing else APP_ENV}' mode.")
        logging.info(f"Using queue base path: '{current_app.config['BASE_QUEUE_PATH']}'")
        
        # Create data directories
        os.makedirs(current_app.config['BASE_QUEUE_PATH'], exist_ok=True)
        os.makedirs(current_app.config['DOWNLOAD_DIR'], exist_ok=True)
        for dir_name in ['inbound', 'outbound', 'consumed', 'failed', 'processing']:
            os.makedirs(os.path.join(current_app.config['BASE_QUEUE_PATH'], dir_name), exist_ok=True)
        
        # Create code directories (if they don't exist)
        os.makedirs(os.path.join(PROJECT_ROOT, app.config['ACTIONS_DIR']), exist_ok=True)
        
        timestamp_file = os.path.join(current_app.config['BASE_QUEUE_PATH'], 'last_api_call.timestamp')
        # Always write the current timestamp on startup to prevent immediate shutdown
        with open(timestamp_file, 'w') as f:
            f.write(str(time.time()))

    # --- Scheduler & Startup Jobs ---
    if not testing:
        # Run purge job immediately on startup
        logging.info("Running purge job on startup...")
        purge_old_files(app)

        # Configure and start the scheduler for recurring jobs
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
        # Update activity timestamp only on inbound requests
        timestamp_file = os.path.join(current_app.config['BASE_QUEUE_PATH'], 'last_api_call.timestamp')
        with open(timestamp_file, 'w') as f:
            f.write(str(time.time()))
        return receive_task()

    @app.route('/outbound', methods=['GET'])
    def outbound_route():
        return check_task_status()

    @app.route('/messages', methods=['GET'])
    def get_all_messages():
        """Gets a list of all messages in each stage of processing."""
        base_path = current_app.config['BASE_QUEUE_PATH']
        stages = ['inbound', 'outbound', 'consumed', 'failed', 'processing']
        all_messages = {}

        for stage in stages:
            stage_path = os.path.join(base_path, stage)
            messages = []
            if os.path.exists(stage_path):
                for filename in sorted(os.listdir(stage_path)):
                    filepath = os.path.join(stage_path, filename)
                    message_content = {'filename': filename}
                    try:
                        with open(filepath, 'r') as f:
                            message_content.update(json.load(f))
                        messages.append(message_content)
                    except (IOError, json.JSONDecodeError) as e:
                        logging.warning(f"Could not read or parse message {filepath}: {e}")
                        message_content['error'] = 'Could not read or parse file'
                        messages.append(message_content)
            all_messages[stage] = messages
        
        return jsonify(all_messages)

    @app.route('/messages/clear', methods=['POST'])
    def clear_all_messages():
        """Clears all messages in every processing stage."""
        base_path = current_app.config['BASE_QUEUE_PATH']
        stages = ['inbound', 'outbound', 'consumed', 'failed', 'processing']
        cleared_count = {}

        for stage in stages:
            stage_path = os.path.join(base_path, stage)
            count = 0
            if os.path.exists(stage_path):
                for item_name in os.listdir(stage_path):
                    item_path = os.path.join(stage_path, item_name)
                    try:
                        if os.path.isfile(item_path) or os.path.islink(item_path):
                            os.unlink(item_path)
                            count += 1
                        elif os.path.isdir(item_path):
                            shutil.rmtree(item_path)
                            count += 1
                    except Exception as e:
                        logging.error(f'Failed to delete {item_path}. Reason: {e}')
            cleared_count[stage] = count

        return jsonify({'status': 'success', 'cleared_messages': cleared_count})

    @app.errorhandler(404)
    def not_found_error(e):
        return page_not_found(e)

    return app

# --- API and Logic (defined outside the factory) ---
# ... (The rest of the functions remain unchanged)
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
            shutil.move(result_filepath, os.path.join(consumed_dir, f"result_{job_id}.json"))
            return jsonify(task_result)
        except (IOError, json.JSONDecodeError) as e:
            logging.error(f"Error reading or moving result file: {e}")
            return jsonify({'status': 'error', 'message': 'Could not retrieve result'}), 500
    else:
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
    """Scheduler job to process tasks within a created app context."""
    with app.app_context():
        base_path = current_app.config['BASE_QUEUE_PATH']
        inbound_queue_dir = os.path.join(base_path, 'inbound')
        if not os.path.exists(inbound_queue_dir) or not os.listdir(inbound_queue_dir):
            return

        logging.info("Scheduler worker checking for tasks...")
        processing_dir = os.path.join(base_path, 'processing')
        consumed_dir = os.path.join(base_path, 'consumed')
        failed_dir = os.path.join(base_path, 'failed')
        download_dir = current_app.config['DOWNLOAD_DIR']
        actions_dir = current_app.config['ACTIONS_DIR']

        task_filename = sorted(os.listdir(inbound_queue_dir))[0]
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
            params = task_to_process.get('params')
            logging.info(f"Processing job {job_id} for action '{action_name}'")

            # --- Debug Logging ---
            actions_path = os.path.join(PROJECT_ROOT, actions_dir)
            if os.path.exists(actions_path):
                available_actions = [f.replace('.py', '') for f in os.listdir(actions_path) if f.endswith('.py') and not f.startswith('__')]
                logging.info(f"Available actions: {available_actions}")
            else:
                logging.warning(f"Actions directory not found at: {actions_path}")
            # --- End Debug Logging ---

            try:
                action_module = importlib.import_module(f"{actions_dir}.{action_name}")
            except ModuleNotFoundError:
                raise ValueError(f"Action '{action_name}' not found or is not a valid module.")

            action_module.execute(job_id, params, download_dir, write_result_to_outbound)

            # On success, move to consumed
            consumed_filepath = os.path.join(consumed_dir, task_filename)
            shutil.move(processing_filepath, consumed_filepath)

        except (json.JSONDecodeError, ValueError) as e:
            error_message = f"Failed to process task {task_filename} due to bad input: {e}"
            logging.warning(error_message)
            if task_to_process and task_to_process.get('job_id'):
                job_id = task_to_process.get('job_id')
            
            result = {'job_id': job_id, 'status': 'failed', 'error': str(e)}
            write_result_to_outbound(job_id, result)
            os.makedirs(failed_dir, exist_ok=True)
            if os.path.exists(processing_filepath):
                shutil.move(processing_filepath, os.path.join(failed_dir, task_filename))

        except Exception as e:
            error_message = f"An unexpected error occurred while processing task {task_filename}: {e}"
            logging.error(error_message, exc_info=True)
            if task_to_process and task_to_process.get('job_id'):
                job_id = task_to_process.get('job_id')
            
            result = {'job_id': job_id, 'status': 'failed', 'error': str(e)}
            write_result_to_outbound(job_id, result)
            os.makedirs(failed_dir, exist_ok=True)
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
            if not inbound_is_empty:
                logging.info("Idle check: Inbound queue is not empty. Deferring shutdown.")
            if not processing_is_empty:
                logging.info("Idle check: Processing queue is not empty. Deferring shutdown.")
            return

        try:
            with open(timestamp_file, 'r') as f:
                last_api_call_time = float(f.read().strip())
            
            idle_time = time.time() - last_api_call_time
            logging.info(f"Idle check: Queues are empty. Last inbound call was {idle_time:.2f} seconds ago.")

            if idle_time > MAX_IDLE_TIME_IN_SECONDS:
                logging.warning(
                    f"Server has been idle for more than {MAX_IDLE_TIME_IN_SECONDS} seconds and queues are empty. "
                    "Initiating VM power off."
                )
                os.system('sudo /sbin/shutdown --poweroff now')

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
                            logging.info(f"Removed old directory: {item_path}")
                        else:
                            os.remove(item_path)
                            logging.info(f"Removed old file: {item_path}")
                except FileNotFoundError:
                    logging.warning(f"Could not find {item_path} during purge; it may have been deleted already.")
                except Exception as e:
                    logging.error(f"Error purging {item_path}: {e}", exc_info=True)
        
        logging.info("Purge job finished.")

# This block is now only used for local development.
if __name__ == '__main__':
    app = create_app()
    logging.info("Starting Flask development server.")
    app.run(host='0.0.0.0', port=5000, debug=(os.environ.get('APP_ENV') == 'development'))
