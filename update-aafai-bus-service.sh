#!/bin/bash

echo "--- Starting deployment for aafai-bus ---"

# 1. Go to the application directory
echo "Changing directory to /var/www/aafai-bus"
cd /var/www/aafai-bus

# 2. Pull the latest code as the 'www-data' user
# This assumes you have set up deploy keys for www-data (Solution 2 from our chat)
echo "Pulling latest code from repository..."
sudo -u www-data git pull

echo "Code successfully updated."

# 3. Restart the systemd service
# This command requires the script to be run with sudo
echo "Restarting aafai-bus service..."
systemctl restart aafai-bus.service

echo "--- Deployment finished successfully. ---"