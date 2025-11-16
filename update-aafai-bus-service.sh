#!/bin/bash

echo "--- Starting deployment for aafai-bus ---"

# 1. Go to the application directory
echo "Changing directory to /var/www/aafai-bus"
cd /var/www/aafai-bus || exit

# 2. Pull the latest code as the 'www-data' user
echo "Pulling latest code from repository..."
sudo -u www-data git stash
sudo -u www-data git pull
sudo chmod +x /var/www/aafai-bus/update-aafai-bus-service.sh

echo "Code successfully updated."

# 3. Install System-level dependencies for Headless Chrome
# These are needed for the chromedriver to run in a headless environment.
echo "Installing system dependencies for headless Chrome..."
apt-get update
apt-get install -y libglib2.0-0 libnss3 libgconf-2-4 libfontconfig1

# 4. Install/update Python dependencies
echo "Installing Python dependencies..."
# Assuming you have a virtual environment in /var/www/aafai-bus/venv
# and your requirements.txt is up to date.
/var/www/aafai-bus/venv/bin/pip install -r requirements.txt

# 5. Restart the systemd service
# This command requires the script to be run with sudo
echo "Restarting aafai-bus service..."
systemctl restart aafai-bus.service

echo "--- Deployment finished successfully. ---"
