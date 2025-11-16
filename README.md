<div align="center">
  <img src="static/Logo AAF.png" alt="AAF Logo" width="150"/>
</div>

# aafai-bus: An On-Demand Asynchronous Task Processor

## 1. Purpose

**aafai-bus** is a lightweight, on-demand Python server designed to handle long-running, resource-intensive tasks that are delegated from other services. Its primary use case is to act as a "boot-on-demand mini bus" for batch-processing occasional deep internet searches, such as those requiring a full browser via Selenium.

The core goal is to **minimize cloud costs** by keeping the server turned off by default. It is started on-demand by a client, processes a queue of tasks, and then automatically shuts itself down after a period of inactivity.

## 2. Architecture

The system is designed around a client-server model where the client is expected to have the ability to start the server's Virtual Machine (e.g., via a cloud provider's API).

**Typical Flow:**

1.  **Client (e.g., Google Apps Script in a GSheet):** A user triggers an action in a Google Sheet.
2.  **Start VM:** The Apps Script calls the Google Cloud API to start the `aafai-bus` VM instance.
3.  **Submit Task:** Once the VM is running, the script sends a task (e.g., download a website) to the server's `/inbound` endpoint. The server writes the task to a file-based queue and immediately returns a `job_id`.
4.  **Process Task:** The server's background scheduler picks up the task from the queue, executes the requested action (e.g., runs a Selenium job), and writes the result to an outbound file.
5.  **Poll for Result:** The Apps Script sets up a time-based trigger to periodically call the server's `/outbound` endpoint with the `job_id`.
6.  **Retrieve Result:** Once the task is complete, the `/outbound` endpoint returns the final JSON result. The Apps Script processes the result and deletes its polling trigger.
7.  **Auto-Shutdown:** After a configurable period of inactivity (i.e., no new inbound requests), the server initiates a graceful shutdown to save costs.

## 3. Security Architecture

To ensure that the `aafai-bus` server only accepts requests from trusted sources, it is critical to configure a firewall rule at the VPC (Virtual Private Cloud) level. This is the most secure and efficient way to protect the server, as it blocks unauthorized traffic before it even reaches the application.

When the client is a Google Apps Script, we can restrict access to the specific IP ranges that Google uses to send `UrlFetchApp` requests.

### Google Cloud Platform (GCP) Firewall Setup

1.  **Find Google's IP Ranges:** Google publishes the IP ranges it uses for its services. You can get the list of ranges for Apps Script by running the following command in your local terminal:
    ```sh
    nslookup -q=TXT _appsscript.google.com
    ```
    This will return one or more `TXT` records containing IP address blocks (e.g., `v=spf1 ip4:64.18.0.0/20 ...`).

2.  **Create a Firewall Rule:** In your GCP project, navigate to **VPC network > Firewall** and create a new **ingress** rule with the following settings:
    - **Name:** `allow-google-apps-script`
    - **Network:** The VPC network your VM is in.
    - **Priority:** `1000` (a standard priority).
    - **Direction of traffic:** `Ingress`
    - **Action on match:** `Allow`
    - **Targets:** Apply the rule to your VM instance using a specific **target tag** (e.g., `aafai-bus-server`).
    - **Source filter:** `IPv4 ranges`.
    - **Source IPv4 ranges:** Enter the IP blocks you found in step 1.
    - **Protocols and ports:** Select `Specified protocols and ports`, then `tcp`, and enter `8000` (or the port your Gunicorn service is running on).

3.  **Tag Your VM:** Navigate to your VM instance details in **Compute Engine** and add the network tag you specified (e.g., `aafai-bus-server`).

With this firewall rule in place, only Google Apps Script will be able to make HTTP requests to your `aafai-bus` server, effectively securing it from public access.

## 4. Features

- **Dynamic Action System:** Add new capabilities by simply dropping a Python file into the `actions/` directory.
- **File-Based Queue:** A simple, durable, and transparent queueing system using the local filesystem.
- **Asynchronous Processing:** Uses `APScheduler` with a thread pool to handle multiple tasks concurrently.
- **On-Demand & Auto-Shutdown:** Designed to be started by a client and automatically shuts down when idle, minimizing resource costs.
- **Gunicorn & Systemd:** Ready for production deployment using industry-standard tools.

## 5. Setup & Deployment

### Python Environment
1.  Clone the repository.
2.  Create a virtual environment: `python -m venv .venv`
3.  Activate it: `source .venv/bin/activate` (Linux) or `.\.venv\Scripts\activate` (Windows).
4.  Install dependencies: `pip install -r requirements.txt`.
5.  Install a Selenium WebDriver (e.g., `chromedriver`) and ensure it is in your system's PATH.

### Production Deployment (Linux)
The application is designed to be run with Gunicorn and managed by a `systemd` service.

1.  Copy the `aafai-bus.service` file to `/etc/systemd/system/`.
2.  Update the paths in the service file to match your deployment directory.
3.  Reload the systemd daemon: `sudo systemctl daemon-reload`.
4.  Enable and start the service: `sudo systemctl enable --now aafai-bus.service`.

## 6. Configuration

Configuration is managed via environment variables, which is ideal for production deployments.

- `APP_ENV`: Set to `production` to enable production settings. Defaults to `development`.
- `QUEUE_BASE_PATH`: **(Production)** The absolute path for storing queues (e.g., `/var/www/aafai-bus/prod_queues`).
- `DOWNLOAD_DIR`: **(Production)** The absolute path for storing downloaded files.

These are typically set in the `aafai-bus.service` file.

## 7. API Endpoints

### `POST /inbound`
Submits a new task to the queue.

**Request Body:**
```json
{
  "action": "name_of_action_file",
  "params": {
    "key": "value"
  }
}
```

**Success Response:**
```json
{
  "status": "received",
  "job_id": "some-unique-job-id"
}
```

### `GET /outbound`
Polls for the result of a previously submitted task.

**Request URL:** `/outbound?job_id=some-unique-job-id`

**Pending Response:**
```json
{
  "status": "pending",
  "message": "Job not yet complete."
}
```

**Complete Response (Example):**
```json
{
    "job_id": "some-unique-job-id",
    "status": "complete",
    "result": {
        "text": "The extracted text from the website...",
        "size_bytes": 12345,
        "warning": "Text content exceeded 10485760 bytes and was truncated."
    }
}
```

## 8. Google Apps Script Integration

An example of a client implementation using Google Apps Script is provided in the `examples/` directory. This script can be added to a Google Sheet to:
- Provide a custom menu to start tasks.
- Automatically start the `aafai-bus` VM on Google Cloud.
- Submit tasks and poll for results.
- Display completion/failure notifications to the user.
