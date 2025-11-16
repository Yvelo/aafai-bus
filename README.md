# aafai-bus: An On-Demand Asynchronous Task Processor

## 1. Purpose

**aafai-bus** (Asynchronous Actions Framework - Bus) is a lightweight, on-demand Python server designed to handle long-running, resource-intensive tasks that are delegated from other services. Its primary use case is to act as a "boot-on-demand mini bus" for batch-processing occasional deep internet searches, such as those requiring a full browser via Selenium.

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

## 3. Features

- **Dynamic Action System:** Add new capabilities by simply dropping a Python file into the `actions/` directory.
- **File-Based Queue:** A simple, durable, and transparent queueing system using the local filesystem.
- **Asynchronous Processing:** Uses `APScheduler` with a thread pool to handle multiple tasks concurrently.
- **On-Demand & Auto-Shutdown:** Designed to be started by a client and automatically shuts down when idle, minimizing resource costs.
- **Gunicorn & Systemd:** Ready for production deployment using industry-standard tools.

## 4. Setup & Deployment

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

## 5. Configuration

Configuration is managed via environment variables, which is ideal for production deployments.

- `APP_ENV`: Set to `production` to enable production settings. Defaults to `development`.
- `QUEUE_BASE_PATH`: **(Production)** The absolute path for storing queues (e.g., `/var/www/aafai-bus/prod_queues`).
- `DOWNLOAD_DIR`: **(Production)** The absolute path for storing downloaded files.

These are typically set in the `aafai-bus.service` file.

## 6. API Endpoints

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

## 7. Google Apps Script Integration

An example of a client implementation using Google Apps Script is provided in the `examples/` directory. This script can be added to a Google Sheet to:
- Provide a custom menu to start tasks.
- Automatically start the `aafai-bus` VM on Google Cloud.
- Submit tasks and poll for results.
- Display completion/failure notifications to the user.
