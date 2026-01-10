import os
import json
import logging
from flask import current_app

def execute(job_id, params, download_dir, write_result_to_outbound):
    """
    Reads all messages from inbound, consumed, and failed queues.
    """
    base_path = current_app.config['BASE_QUEUE_PATH']
    
    queues = ['inbound', 'consumed', 'failed']
    all_messages = {queue: [] for queue in queues}

    for queue in queues:
        queue_path = os.path.join(base_path, queue)
        if os.path.exists(queue_path):
            # Sort to ensure consistent order for testing
            for filename in sorted(os.listdir(queue_path)):
                # Skip the file if it's the one currently being processed
                if queue == 'inbound' and job_id in filename:
                    logging.info(f"Skipping current job's own message file: {filename}")
                    continue

                filepath = os.path.join(queue_path, filename)
                try:
                    with open(filepath, 'r') as f:
                        all_messages[queue].append(json.load(f))
                except (IOError, json.JSONDecodeError) as e:
                    logging.warning(f"Could not read or parse message {filename} in {queue}: {e}")

    result = {
        'job_id': job_id,
        'status': 'complete',
        'result': all_messages
    }
    write_result_to_outbound(job_id, result)
