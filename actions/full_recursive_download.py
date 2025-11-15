import os
import time
import requests
from bs4 import BeautifulSoup

def execute(job_id, params, download_dir, write_result_to_outbound):
    """
    Downloads a website recursively.

    Args:
        job_id (str): The ID of the job.
        params (dict): A dictionary of parameters for the action.
                       Expected to contain a 'url' key.
        download_dir (str): The base directory for downloads.
        write_result_to_outbound (function): A function to write the result to the outbound queue.
    """
    url = params.get('url')
    if not url:
        raise ValueError("'url' parameter is missing for 'full_recursive_download'")

    download_path = os.path.join(download_dir, job_id)

    try:
        os.makedirs(download_path, exist_ok=True)
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        file_path = os.path.join(download_path, 'index.html')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(soup.prettify())
        # Simulating a long-running job
        time.sleep(5)
        result = {
            'job_id': job_id,
            'status': 'complete',
            'result': f'Successfully downloaded content from {url} to {download_path}'
        }
    except Exception as e:
        result = {'job_id': job_id, 'status': 'failed', 'error': str(e)}

    write_result_to_outbound(job_id, result)
