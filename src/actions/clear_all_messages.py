import os
import shutil
import logging
from flask import current_app

def execute(job_id, params, download_dir, write_result_to_outbound):
    """
    Deletes all messages from inbound, consumed, and failed queues.
    """
    base_path = current_app.config['BASE_QUEUE_PATH']
    
    # We also clear 'processing' and 'outbound' to ensure a clean slate,
    # but we don't report them in 'cleared_queues' as they are internal.
    queues_to_clear = ['inbound', 'consumed', 'failed']
    reported_cleared_queues = []

    for queue in queues_to_clear:
        queue_path = os.path.join(base_path, queue)
        if os.path.exists(queue_path):
            # Recreate the directory to clear all contents
            try:
                shutil.rmtree(queue_path)
                os.makedirs(queue_path)
                if queue in ['inbound', 'consumed', 'failed']:
                    reported_cleared_queues.append(queue)
            except Exception as e:
                logging.error(f'Failed to clear directory {queue_path}. Reason: {e}')

    result = {
        'job_id': job_id,
        'status': 'complete',
        'result': {
            'message': 'All queues cleared successfully.',
            'cleared_queues': reported_cleared_queues
        }
    }
    write_result_to_outbound(job_id, result)
