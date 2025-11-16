# startup_purge.py
import os
import sys
import logging

# Add the project root to the Python path to ensure 'server' can be imported
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from server import create_app, purge_old_files

# Configure logging to see output in systemd logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if __name__ == "__main__":
    logging.info("Executing pre-start task: Purging old files...")
    
    # We need to create a temporary app instance to have the application context
    # and access to the configuration.
    app = create_app()
    
    # Call the purge function directly
    purge_old_files(app)
    
    logging.info("Pre-start purge task finished.")
