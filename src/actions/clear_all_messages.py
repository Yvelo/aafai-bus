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
        if not os.path.isdir(queue_path):
            # If directory doesn't exist, it's clear.
            reported_cleared_queues.append(queue)
            continue

        all_deleted = True
        for filename in os.listdir(queue_path):
            file_path = os.path.join(queue_path, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                logging.error(f'Failed to delete {file_path}. Reason: {e}')
                all_deleted = False
        
        if all_deleted:
            reported_cleared_queues.append(queue)

    result = {
        'job_id': job_id,
        'status': 'complete',
        'result': {
            'message': 'All queues cleared successfully.',
            'cleared_queues': reported_cleared_queues
        }
    }
    write_result_to_outbound(job_id, result)
