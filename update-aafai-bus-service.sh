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

# 3. Install/update Python dependencies
echo "Installing Python dependencies..."
# Assuming you have a virtual environment in /var/www/aafai-bus/venv
# and your requirements.txt is up to date.
/var/www/aafai-bus/venv/bin/pip install -r requirements.txt

# 4. Restart the systemd service
# This command requires the script to be run with sudo
echo "Restarting aafai-bus service..."
systemctl restart aafai-bus.service

echo "--- Deployment finished successfully. ---"
