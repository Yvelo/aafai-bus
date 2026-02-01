import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.actions.search_espacenet import execute
from unittest.mock import MagicMock
import tempfile
import shutil
import json

# Create temp dir
temp_dir = tempfile.mkdtemp()

try:
    job_id = "diagnostic-test"
    params = {
        "queries": [
            ["neoantigen", "tumor", "irradiated", "CAR-T", "5FU"]
        ],
        "max_number_of_patents": 100
    }
    
    mock_write_result = MagicMock()
    
    driver = execute(job_id, params, temp_dir, mock_write_result, quit_driver=False)
    
    # Print the result
    if mock_write_result.called:
        _, result = mock_write_result.call_args[0]
        print("="*80)
        print("RESULT:")
        print(json.dumps(result, indent=2))
        print("="*80)
    else:
        print("mock_write_result was not called!")
    
    if driver:
        driver.quit()
finally:
    shutil.rmtree(temp_dir, ignore_errors=True)
