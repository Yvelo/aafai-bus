/**
 * @OnlyCurrentDoc
 *
 * The above comment directs Apps Script to limit the scope of authorization,
 * confining it to the current spreadsheet only.
 */

// --- Configuration ---
// const DOWNLOAD_FOLDER_ID = Must be defined in the main calling script

const SERVICE_ACCOUNT_KEY_PROPERTY = 'SERVICE_ACCOUNT_KEY';
const GCP_PROJECT_ID = 'startup-scraping';
const VM_ZONE = 'europe-west1-d';
const VM_INSTANCE_NAME = 'aafai-bus';
const SERVER_BASE_URL = 'http://34.79.110.150:8000';
const BOOT_DELAY_SECONDS = 60; // Time to wait for the server to initialize after the VM starts
const VM_RESTART_DELAY_SECONDS = 3600; // Time to wait (1 hr) before retrying if VM resources are unavailable
const BATCH_JOBS_PROPERTY = 'activeBatchJobs'; // Script property key for storing active jobs
const JOBS_HEADERS = ['Timestamp Sent', 'Action', 'Inbound Message', 'Timestamp Received', 'URL to Outbound Message', 'Job ID', 'Status', 'File link'];
const JOBS_SHEET_NAME = "Jobs";

/**
 * Adds items to the custom menu.
 * @param {GoogleAppsScript.Base.Menu} menu The menu to add items to.
 */
function addBusMenu(menu) {
  menu.addItem('Download full website', 'showWebsiteDownloadForm');
  menu.addItem('Show server queues status', 'showQueuesStatus');
  menu.addItem('Purge server queues', 'triggerServerPurge');
  menu.addItem('Restart Incomplete Jobs', 'restartIncompleteJobs');
  menu.addItem('Clear All Jobs', 'clearAllJobs');
  menu.addItem('Set Service Account Key', 'setServiceAccountKey');
}

/**
 * Displays a custom HTML form as a modal dialog.
 */
function showWebsiteDownloadForm() {
  const template = HtmlService.createTemplateFromFile('WebsiteDownload');
  template.getLogoBase64 = getLogoBase64;
  const html = template.evaluate()
    .setWidth(450)
    .setHeight(380); // Increased height for the textarea
  SpreadsheetApp.getUi().showModalDialog(html, ' ');
}

/**
 * Processes the form submission from the HTML dialog.
 * It now accepts an array of URLs to enable batch processing from the UI.
 * @param {string[]} urls The array of website URLs submitted by the user.
 * @param {string} max_depth The recursion max_depth submitted by the user.
 * @return {string} A success message to be displayed to the user.
 */
function processForm(urls, max_depth) {
  const ui = getUi();
  if (DOWNLOAD_FOLDER_ID === 'YOUR_FOLDER_ID_HERE' || DOWNLOAD_FOLDER_ID === '') {
    const errorMessage = 'Configuration Error: Please set the DOWNLOAD_FOLDER_ID constant in the script editor.';
    Logger.log(errorMessage);
    if (ui) {ui.alert(errorMessage);}
    return 'Configuration Error: Please contact the sheet owner.';
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();

  // UPDATED: Get existing sheet or create if it doesn't exist
  let sheet = ss.getSheetByName(JOBS_SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(JOBS_SHEET_NAME);
  }
  // Optional: Activate the sheet so the user sees it immediately
  sheet.activate();

  const inboundMessages = urls.map(url => ({
    action: 'full_recursive_download',
    params: {
      'url': url,
      'max_depth': parseInt(max_depth, 10)
    }
  }));

  batchScrapingRequests(sheet, inboundMessages);

  return 'Task submitted! You can close this window. Check the ' + JOBS_SHEET_NAME + ' sheet for progress.';
}


/**
 * Processes a batch of inbound scraping messages, prepares a target sheet,
 * and populates it with job tracking information.
 * UPDATED: Appends to the provided sheet.
 */
function batchScrapingRequests(sheet, inboundMessages, skipTriggerManagement = false) {
  const lastRow = sheet.getLastRow();
  let nextRowIndex = lastRow + 1;

  if (lastRow === 0) {
    // Write headers
    sheet.getRange(1, 1, 1, JOBS_HEADERS.length).setValues([JOBS_HEADERS]).setFontWeight('bold');
    SpreadsheetApp.flush();
    nextRowIndex = 2;
  }

  const scriptProperties = PropertiesService.getScriptProperties();
  let allJobsToPoll = JSON.parse(scriptProperties.getProperty(BATCH_JOBS_PROPERTY) || '[]');

  ensureVmIsRunning((isVmRunning) => {
    const newlySubmittedJobs = [];
    for (const [index, message] of inboundMessages.entries()) {
      const currentRow = nextRowIndex + index;
      const sentTimestamp = new Date();
      let jobId = null, status = 'Failed to Submit';

      if (isVmRunning) {
        const payload = { action: message.action, params: message.params };
        const options = { 'method': 'post', 'contentType': 'application/json', 'payload': JSON.stringify(payload) };

        try {
          const response = UrlFetchApp.fetch(`${SERVER_BASE_URL}/inbound`, options);
          const result = JSON.parse(response.getContentText());

          if (result.status === 'received' && result.job_id) {
            jobId = result.job_id;
            status = 'Submitted';
            Logger.log(`Task successfully submitted. Job ID: ${jobId}`);
            newlySubmittedJobs.push({
              jobId: jobId,
              row: currentRow,
              spreadsheetId: sheet.getParent().getId(),
              sheetName: sheet.getName()
            });
          } else {
            Logger.log(`Failed to submit task. Server response: ${response.getContentText()}`);
          }
        } catch (e) {
          Logger.log(`An error occurred while contacting the server: ${e.toString()}`);
          status = 'Failed to connect to server';
        }
      } else {
        // VM Failed to boot (e.g. resources unavailable)
        status = 'On Hold - VM Unavailable';
      }

      // Initialize row with empty string for 'File link' column
      const rowData = [sentTimestamp, message.action, JSON.stringify(message.params), '', '', jobId || '', status, ''];

      // Write to the specific calculated row AND APPLY FONT COLOR
      sheet.getRange(currentRow, 1, 1, rowData.length)
           .setValues([rowData])
           .setFontColor(typeof DATA_FONT_COLOR !== 'undefined' ? DATA_FONT_COLOR : '#000000');

      if (status === 'Failed to connect to server') {
        return;
      }
    };

    if (isVmRunning) {
      if (newlySubmittedJobs.length > 0) {
        allJobsToPoll.push(...newlySubmittedJobs);
        scriptProperties.setProperty(BATCH_JOBS_PROPERTY, JSON.stringify(allJobsToPoll));

        if (!skipTriggerManagement) {
          deleteTriggers('pollForBatchResults');
          ScriptApp.newTrigger('pollForBatchResults').timeBased().everyMinutes(1).create();
        }

        SpreadsheetApp.getActiveSpreadsheet().toast(`${newlySubmittedJobs.length} tasks appended to ${sheet.getName()}! Polling.`, 'Success', 5);
      } else {
        SpreadsheetApp.getActiveSpreadsheet().toast('No tasks were successfully submitted.', 'Error', 5);
      }
    } else {
      // Create a trigger to retry incomplete jobs if VM was unavailable
      scheduleRestartIncompleteJobs();
      SpreadsheetApp.getActiveSpreadsheet().toast('VM resources are currently unavailable. Jobs placed on hold and will automatically retry in 1 hour.', 'Warning', 10);
    }
  });
}

function clearAllJobs() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const jobsSheet = ss.getSheetByName(JOBS_SHEET_NAME);

  if (!jobsSheet) {
    SpreadsheetApp.getActiveSpreadsheet().toast(`Sheet "${JOBS_SHEET_NAME}" not found.`, "Error");
    return;
  }

  // Expanded to cover all explicit states
  const statusesToRemove = [
    "Submitted", "Pending", "Polling", "Complete", "Completed", "Success",
    "Failed", "Download Error", "Failed to Submit", "On Hold - VM Unavailable",
    "Imported", "Error Parsing", "Failed to connect to server",
    "Connection Error", "Server Processing / Check Error"
  ];

  clearJobs(jobsSheet, statusesToRemove);
}

/**
 * Removes lines in the ACTIVE sheet where the status matches the input array.
 * IMPORTANT: Updates ScriptProperties to keep polling in sync for remaining jobs.
 * @param {string[]} statusArray Array of status strings to remove.
 */
function clearJobs(sheet, statusArray) {
  const lastRow = sheet.getLastRow();

  // If only headers or empty, exit
  if (lastRow < 2) {
    SpreadsheetApp.getActiveSpreadsheet().toast("No jobs to clear.", "Info");
    return;
  }

  // 1. Get current Active Jobs from memory (to ensure we don't break polling for kept rows)
  const scriptProperties = PropertiesService.getScriptProperties();
  const jobsDataString = scriptProperties.getProperty(BATCH_JOBS_PROPERTY);
  let activeJobs = jobsDataString ? JSON.parse(jobsDataString) : [];
  const sheetName = sheet.getName();
  const ssId = sheet.getParent().getId();

  // 2. Get Data to analyze (Status is Column 7 / Index 6)
  // We get values from row 2 to lastRow
  const dataRange = sheet.getRange(2, 1, lastRow - 1, 8);
  const data = dataRange.getValues();

  const rowsToDelete = [];

  // 3. Identify rows to delete
  for (let i = 0; i < data.length; i++) {
    const status = (data[i][6] || "").toString().trim(); // Column 7 is index 6

    // Check against array OR dynamic error/recovery prefixes
    const isDynamicErrorState = status.startsWith("Recovered") ||
                                status.startsWith("Server Error") ||
                                status.startsWith("HTTP Error");

    if (statusArray.includes(status) || isDynamicErrorState) {
      rowsToDelete.push(i + 2);
    }
  }

  if (rowsToDelete.length === 0) {
    SpreadsheetApp.getActiveSpreadsheet().toast("No matching jobs found to clear.", "Info");
    return;
  }

  // 4. Process deletions in REVERSE order
  // We must delete from bottom up so row numbers of previous deletes don't shift
  rowsToDelete.sort((a, b) => b - a);

  rowsToDelete.forEach(rowToDelete => {
    // A. Remove the row from the sheet
    sheet.deleteRow(rowToDelete);

    // B. Update the activeJobs list
    activeJobs = activeJobs.filter(job => {
      // Filter out the job if it matches the deleted row and sheet
      if (job.spreadsheetId === ssId && job.sheetName === sheetName && job.row === rowToDelete) {
        return false;
      }
      return true;
    });

    // Shift up rows for remaining jobs in this sheet
    activeJobs.forEach(job => {
      if (job.spreadsheetId === ssId && job.sheetName === sheetName && job.row > rowToDelete) {
        job.row = job.row - 1;
      }
    });
  });

  // 5. Save the updated job list back to properties
  scriptProperties.setProperty(BATCH_JOBS_PROPERTY, JSON.stringify(activeJobs));

  SpreadsheetApp.getActiveSpreadsheet().toast(`Cleared ${rowsToDelete.length} jobs.`, "Success");
}

/**
 * Polls the outbound queue.
 * Optimized with LockService to prevent overlapping triggers
 * and a 45-second guard to hand off cleanly to the next minute's trigger.
 * Checks if VM is running first to avoid infinite polling failure if VM stops.
 */
function pollForBatchResults() {
  // 1. ADD LOCK SERVICE: Prevents two 1-minute triggers from running at the same time
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) {
    Logger.log('Another instance of polling is already running. Exiting to prevent data corruption.');
    return;
  }

  try {
    // 2. CHECK VM STATUS: Ensure the server is online before trying to poll.
    // If the VM is off, this will turn it on and sleep for BOOT_DELAY_SECONDS (60s).
    ensureVmIsRunning((isVmRunning) => {

      if (!isVmRunning) {
        Logger.log('VM is not running and failed to start. Suspending 1-minute polling and scheduling a retry in 1 hour.');
        deleteTriggers('pollForBatchResults');
        scheduleRestartIncompleteJobs();
        return;
      }

      // 3. Start the timer AFTER the VM check (which might have paused for 60s)
      const EXECUTION_START = Date.now();
      const MAX_EXECUTION_TIME_MS = 45 * 1000; // 45 seconds

      const scriptProperties = PropertiesService.getScriptProperties();
      const jobsDataString = scriptProperties.getProperty(BATCH_JOBS_PROPERTY);

      if (!jobsDataString) {
        Logger.log('No active batch jobs found. Stopping polling.');
        deleteTriggers('pollForBatchResults');
        return;
      }

      let activeJobs = JSON.parse(jobsDataString);
      if (activeJobs.length === 0) {
        scriptProperties.deleteProperty(BATCH_JOBS_PROPERTY);
        deleteTriggers('pollForBatchResults');
        return;
      }

      const downloadFolder = DriveApp.getFolderById(DOWNLOAD_FOLDER_ID);
      const jobsToSave = []; // Accumulate jobs that are STILL pending to save back to memory

      const jobsBySheet = activeJobs.reduce((acc, job) => {
        const key = `${job.spreadsheetId}::${job.sheetName}`;
        if (!acc[key]) acc[key] = { ssId: job.spreadsheetId, sheetName: job.sheetName, jobs: [] };
        acc[key].jobs.push(job);
        return acc;
      }, {});

      for (const key in jobsBySheet) {
        // 4. TIME GUARD: Cleanly exit at 45 seconds to hand off to the next trigger
        if (Date.now() - EXECUTION_START > MAX_EXECUTION_TIME_MS) {
          Logger.log("Nearing 45-second limit. Saving progress and pausing for next minute's trigger.");
          jobsToSave.push(...jobsBySheet[key].jobs);
          continue;
        }

        const { ssId, sheetName, jobs } = jobsBySheet[key];
        let sheet;
        try {
          sheet = SpreadsheetApp.openById(ssId).getSheetByName(sheetName);
          if (!sheet) throw new Error(`Sheet "${sheetName}" not found.`);
        } catch (e) {
          jobsToSave.push(...jobs);
          continue;
        }

        const BATCH_SIZE = 10;
        for (let i = 0; i < jobs.length; i += BATCH_SIZE) {
          const jobBatch = jobs.slice(i, i + BATCH_SIZE);

          const requests = jobBatch.map(job => ({
            url: `${SERVER_BASE_URL}/outbound?job_id=${encodeURIComponent(job.jobId)}`,
            method: 'get',
            muteHttpExceptions: true
          }));

          let responses;
          try {
            responses = UrlFetchApp.fetchAll(requests);
          } catch (err) {
            Logger.log(`Fetch error during polling: ${err.message}`);
            jobsToSave.push(...jobBatch);
            continue;
          }

          jobBatch.forEach((job, index) => {
            const { jobId, row } = job;
            const responseText = responses[index].getContentText();

            try {
              if (!responseText || responseText.trim() === '') {
                sheet.getRange(row, 7).setValue('Polling').setFontColor(typeof DATA_FONT_COLOR !== 'undefined' ? DATA_FONT_COLOR : '#000000');
                jobsToSave.push(job);
                return;
              }

              const result = JSON.parse(responseText);
              const status = result.status ? result.status.toLowerCase() : 'polling';

              // Catch 'completed', or 'success' to be extra safe against API changes
              if (status === 'completed' || status === 'success') {
                processCompletedJob(sheet, row, jobId, result, downloadFolder);
              } else if (status === 'failed' || status === 'error') {
                sheet.getRange(row, 4, 1, 5)
                     .setValues([[new Date(), `Error: ${result.error || 'Unknown server error'}`, jobId, 'Failed', '']])
                     .setFontColor(typeof DATA_FONT_COLOR !== 'undefined' ? DATA_FONT_COLOR : '#000000');
              } else {
                sheet.getRange(row, 7).setValue(result.status || 'Polling').setFontColor(typeof DATA_FONT_COLOR !== 'undefined' ? DATA_FONT_COLOR : '#000000');
                jobsToSave.push(job);
              }
            } catch (e) {
              // Usually means server returned an HTML error page instead of JSON
              sheet.getRange(row, 7).setValue('Server Processing / Check Error').setFontColor(typeof DATA_FONT_COLOR !== 'undefined' ? DATA_FONT_COLOR : '#000000');
              jobsToSave.push(job);
            }
          });

          scriptProperties.setProperty(BATCH_JOBS_PROPERTY, JSON.stringify(jobsToSave));
        }
      }

      if (jobsToSave.length > 0) {
        scriptProperties.setProperty(BATCH_JOBS_PROPERTY, JSON.stringify(jobsToSave));
      } else {
        scriptProperties.deleteProperty(BATCH_JOBS_PROPERTY);
        deleteTriggers('pollForBatchResults');
      }
    });
  } finally {
    // ALWAYS release the lock when done, even if the script crashes
    lock.releaseLock();
  }
}

/**
 * Ensures the VM is running before executing a callback function.
 * @param {function(boolean)} callback The function to execute after checking VM status. Receives `true` if running, `false` otherwise.
 */
function ensureVmIsRunning(callback) {
  let instance = getVmDetails();
  let status = instance ? instance.status : 'TERMINATED';

  if (status !== 'RUNNING') {
    Logger.log(`VM is not running. Starting VM: ${VM_INSTANCE_NAME}`);
    startVm();
    Logger.log(`Waiting for ${BOOT_DELAY_SECONDS} seconds for the server to boot...`);
    Utilities.sleep(BOOT_DELAY_SECONDS * 1000);

    // Check if the VM successfully started after the wait
    instance = getVmDetails();
    status = instance ? instance.status : 'TERMINATED';

    if (status !== 'RUNNING') {
      Logger.log(`VM failed to start after ${BOOT_DELAY_SECONDS} seconds (Status: ${status}). Resources may be unavailable.`);
      callback(false);
      return;
    }
  } else {
    Logger.log(`VM is already running.`);
  }

  callback(true);
}

/**
 * Starts the specified GCE VM instance using the Compute Engine API.
 */
function startVm() {
  const service = getGcpService();
  if (!service || !service.hasAccess()) {
    Logger.log('Authentication failed. Check your service account key.');
    SpreadsheetApp.getActiveSpreadsheet().toast('GCP Authentication Failed.', 'Error', 5);
    return;
  }

  const url = `https://compute.googleapis.com/compute/v1/projects/${GCP_PROJECT_ID}/zones/${VM_ZONE}/instances/${VM_INSTANCE_NAME}/start`;
  const options = {
    method: 'post',
    headers: { 'Authorization': 'Bearer ' + service.getAccessToken() },
    muteHttpExceptions: true
  };

  const response = UrlFetchApp.fetch(url, options);
  Logger.log(`VM start response: ${response.getContentText()}`);
}

/**
 * Retrieves the details of the specified GCE VM instance.
 * @return {object | null} The instance resource object or null if not found or on error.
 */
function getVmDetails() {
  const service = getGcpService();
  if (!service || !service.hasAccess()) {
    Logger.log('Authentication failed.');
    return null;
  }

  const url = `https://compute.googleapis.com/compute/v1/projects/${GCP_PROJECT_ID}/zones/${VM_ZONE}/instances/${VM_INSTANCE_NAME}`;
  const options = {
    headers: { 'Authorization': 'Bearer ' + service.getAccessToken() },
    muteHttpExceptions: true
  };

  const response = UrlFetchApp.fetch(url, options);
  if (response.getResponseCode() === 200) {
    return JSON.parse(response.getContentText());
  }
  Logger.log(`Failed to get VM details. Response code: ${response.getResponseCode()}`);
  return null;
}

/**
 * Schedules a trigger to automatically run restartIncompleteJobs.
 */
function scheduleRestartIncompleteJobs() {
  deleteTriggers('restartIncompleteJobs');
  ScriptApp.newTrigger('restartIncompleteJobs')
    .timeBased()
    .after(VM_RESTART_DELAY_SECONDS * 1000)
    .create();
  Logger.log(`Scheduled restartIncompleteJobs to run in ${VM_RESTART_DELAY_SECONDS} seconds.`);
}

/**
 * Configures and returns an OAuth2 service for GCP using a service account.
 * @return {object | null} The configured OAuth2 service or null if key is missing.
 */
function getGcpService() {
    const serviceAccountKey = getServiceAccountKey();
    if (!serviceAccountKey) {
        return null;
    }

    return OAuth2.createService('GCP')
        .setTokenUrl('https://oauth2.googleapis.com/token')
        .setPrivateKey(serviceAccountKey.private_key)
        .setIssuer(serviceAccountKey.client_email)
        .setSubject(serviceAccountKey.client_email)
        .setPropertyStore(PropertiesService.getScriptProperties())
        .setScope('https://www.googleapis.com/auth/cloud-platform https://www.googleapis.com/auth/drive');
}

/**
 * Prompts the user to set the Service Account Key.
 */
function setServiceAccountKey() {
  const ui = getUi();
  const response = ui.prompt('Set Service Account Key', 'Please paste your entire Google Cloud Service Account Key (JSON):', ui.ButtonSet.OK_CANCEL);
  if (response.getSelectedButton() == ui.Button.OK) {
    const serviceAccountKey = response.getResponseText().trim();
    if (serviceAccountKey) {
      try {
        JSON.parse(serviceAccountKey);
        PropertiesService.getUserProperties().setProperty(SERVICE_ACCOUNT_KEY_PROPERTY, serviceAccountKey);
        if (ui) {ui.alert('Success', 'Service Account Key has been set for this user.', ui.ButtonSet.OK);}
      } catch (e) {
        if (ui) {ui.alert('Error', 'Invalid JSON format.', ui.ButtonSet.OK)};
      }
    } else {
      if (ui) {ui.alert('Cancelled', 'No Service Account Key was entered.', ui.ButtonSet.OK);}
    }
  }
}

/**
 * Retrieves the Service Account Key.
 * @return {object | null} The parsed Service Account Key JSON object.
 */
function getServiceAccountKey() {
  const ui = getUi();
  const userProperties = PropertiesService.getUserProperties();
  const serviceAccountKeyJSON = userProperties.getProperty(SERVICE_ACCOUNT_KEY_PROPERTY);

  if (!serviceAccountKeyJSON) {
    if (ui) {ui.alert('Service Account Key is not set. Please use the "aafai-bus > Set Service Account Key" menu to set it.');}
    return null;
  }
  return JSON.parse(serviceAccountKeyJSON);
}

/**
 * A test function to demonstrate batchScrapingRequests with sample URLs.
 * Can be run from the custom 'aafai-bus' menu.
 */
function testBatchScraping() {
  const ui = getUi();
  if (DOWNLOAD_FOLDER_ID === 'YOUR_FOLDER_ID_HERE' || DOWNLOAD_FOLDER_ID === '') {
    if (ui) {ui.alert('Configuration Needed', 'Please set the DOWNLOAD_FOLDER_ID constant in the script editor before running.', ui.ButtonSet.OK);}
    return;
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();

  // UPDATED: Use the common sheet logic
  let sheet = ss.getSheetByName(JOBS_SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(JOBS_SHEET_NAME);
  }
  sheet.activate();

  const inboundMessages = [
   {
      action: 'get_all_messages',
      params: { }
    }
  ];

  batchScrapingRequests(sheet, inboundMessages);
}

/**
 * Calls the server to get the status of all queues and displays a summary.
 */
function showQueuesStatus() {
  const ui = getUi();
  SpreadsheetApp.getActiveSpreadsheet().toast('Contacting server to fetch queues status...', 'Status');

  // Ensure the VM is running before attempting to fetch the queue
  ensureVmIsRunning((isVmRunning) => {
    if (!isVmRunning) {
      if (ui) {ui.alert('Connection Error', 'VM resources are currently unavailable. Cannot fetch queues status at this time.', ui.ButtonSet.OK);}
      return;
    }

    try {
      const url = `${SERVER_BASE_URL}/queues`;
      const options = {
        'method': 'get',
        'muteHttpExceptions': true
      };

      const response = UrlFetchApp.fetch(url, options);

      if (response.getResponseCode() === 200) {
        const data = JSON.parse(response.getContentText());

        let summary = 'Server Queues Summary:\n\n';
        const queues = ['inbound', 'processing', 'outbound', 'failed', 'consumed'];

        queues.forEach(q => {
          const items = data[q] || [];
          // Capitalize the first letter of the queue name
          const name = q.charAt(0).toUpperCase() + q.slice(1);
          summary += `${name}: ${items.length} task(s)\n`;

          // Detail the active or failed tasks (up to 5 items to avoid huge popups)
          if (items.length > 0 && ['inbound', 'processing', 'outbound', 'failed', 'consumed'].includes(q)) {
            items.forEach((item, index) => {
              if (index < 5) {
                const action = item.action || 'Unknown Action';
                const jobId = item.job_id ? item.job_id.substring(0, 8) + '...' : 'N/A';
                summary += `    ↳ [${jobId}] ${action}\n`;
              }
              Logger.log(`${name}: [${item.job_id}] ${item.action}`);
            });
            if (items.length > 5) {
              summary += `    ↳ ... and ${items.length - 5} more.\n`;
            }
          }
        });

        if (ui) {ui.alert('Queues Status', summary, ui.ButtonSet.OK);}

      } else {
        if (ui) {ui.alert('Server Error', `Failed to fetch queues. Server responded with code: ${response.getResponseCode()}\nResponse: ${response.getContentText()}`, ui.ButtonSet.OK);}
      }
    } catch (e) {
      Logger.log(`Error fetching queues: ${e.toString()}`);
      if (ui) {ui.alert('Connection Error', `Could not reach the server. The VM might still be booting up.\n\nDetails: ${e.message}`, ui.ButtonSet.OK);}
    }
  });
}

/**
 * Calls the server to manually trigger the purge of old files.
 */
function triggerServerPurge() {
  const ui = getUi();

  // Ask for confirmation before triggering the action
  if (ui) {
    const confirm = ui.alert(
      'Confirm Purge',
      'Are you sure you want to manually trigger a purge on the server?\n\nThis will delete all files across all queues and downloads.',
      ui.ButtonSet.YES_NO
    );

    if (confirm !== ui.Button.YES) {
      return;
    }
  }

  SpreadsheetApp.getActiveSpreadsheet().toast('Contacting server to start purge...', 'Status');

  // Ensure the VM is running before sending the request
  ensureVmIsRunning((isVmRunning) => {
    if (!isVmRunning) {
      if (ui) {ui.alert('Connection Error', 'VM resources are currently unavailable. Cannot trigger purge at this time.', ui.ButtonSet.OK);}
      return;
    }

    try {
      const url = `${SERVER_BASE_URL}/purge`;
      const payload = {
        'days': 0
      };
      const options = {
        'method': 'post',
        'contentType': 'application/json',
        'payload': JSON.stringify(payload),
        'muteHttpExceptions': true
      };

      const response = UrlFetchApp.fetch(url, options);

      if (response.getResponseCode() === 200) {
        const data = JSON.parse(response.getContentText());
        showQueuesStatus();
      } else {
        if (ui) {ui.alert('Server Error', `Failed to start purge. Server responded with code: ${response.getResponseCode()}\nResponse: ${response.getContentText()}`, ui.ButtonSet.OK);}
      }
    } catch (e) {
      Logger.log(`Error triggering purge: ${e.toString()}`);
      if (ui) {ui.alert('Connection Error', `Could not reach the server. The VM might still be booting up.\n\nDetails: ${e.message}`, ui.ButtonSet.OK);}
    }
  });
}

/**
 * Stops current polling, finds all incomplete jobs in the sheet,
 * compares them against the server's current /queues status,
 * recovers existing jobs to be polled, resubmits missing ones, and restarts polling.
 * Handles both manual execution and automated triggers.
 */
function restartIncompleteJobs(e) {
  // If run via a time-based trigger, ensure we don't duplicate executions
  if (e) {
    deleteTriggers('restartIncompleteJobs');
  }

  const isAuto = e !== undefined; // Check if triggered automatically
  let ui = null;

  if (!isAuto) {
    try {
      ui = getUi();
    } catch (err) {
      try { ui = SpreadsheetApp.getUi(); } catch (error) {}
    }
  }

  if (ui && !isAuto) {
    const response = ui.alert(
      'Confirm Restart',
      'This will stop current polling, cross-reference incomplete jobs with the server queues, recover active jobs, resubmit missing ones, and restart polling. Continue?',
      ui.ButtonSet.YES_NO
    );
    if (response !== ui.Button.YES) return;
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) {
    Logger.log("Could not access active spreadsheet. Aborting restartIncompleteJobs.");
    return;
  }

  const sheet = ss.getSheetByName(JOBS_SHEET_NAME);

  if (!sheet) {
    if (ui) ui.alert('Error', `Sheet "${JOBS_SHEET_NAME}" not found.`, ui.ButtonSet.OK);
    return;
  }

  ss.toast('Stopping existing polling processes...', 'Status');

  // 1. Kill existing polling triggers and reset the active jobs memory
  deleteTriggers('pollForBatchResults');
  const scriptProperties = PropertiesService.getScriptProperties();
  scriptProperties.deleteProperty(BATCH_JOBS_PROPERTY);

  // 2. Read the sheet data
  const data = sheet.getDataRange().getValues();
  if (data.length < 2) {
     ss.toast('No jobs found in the sheet.', 'Info');
     return;
  }

  const jobsToRestart = [];

  // 3. Identify incomplete jobs (Start from i=1 to skip headers)
  for (let i = 1; i < data.length; i++) {
    const status = (data[i][6] || '').toString().trim().toLowerCase();
    const action = data[i][1];
    const paramsString = data[i][2];
    const existingJobId = data[i][5];

    // Skip ALL terminal states (Completed successfully or imported)
    const terminalStatuses = [
      'completed',
      'success',
      'imported'
    ];

    if (terminalStatuses.includes(status)) {
        continue;
    }

    // If it has action and params, it is a valid candidate for recovery/restart
    if (action && paramsString) {
        jobsToRestart.push({
            row: i + 1, // Sheet rows are 1-indexed
            action: action,
            paramsString: paramsString,
            existingJobId: existingJobId
        });
    }
  }

  if (jobsToRestart.length === 0) {
      ss.toast('No eligible incomplete jobs found. Nothing to restart.', 'Info');
      return;
  }

  ss.toast(`Found ${jobsToRestart.length} jobs to check/restart. Waking up server...`, 'Status');

  // 4. Verify on server and resubmit if missing
  ensureVmIsRunning((isVmRunning) => {
    if (!isVmRunning) {
      // If VM cannot be started, rewrite statuses and set the trigger to try again later
      jobsToRestart.forEach(job => {
        sheet.getRange(job.row, 7).setValue('On Hold - VM Unavailable')
             .setFontColor(typeof DATA_FONT_COLOR !== 'undefined' ? DATA_FONT_COLOR : '#000000');
      });
      scheduleRestartIncompleteJobs();
      ss.toast('VM resources still unavailable. Jobs kept on hold for another hour.', 'Warning', 10);
      return;
    }

    // STEP A: Fetch master list of server queues
    let serverJobsMap = {};
    try {
      const qResponse = UrlFetchApp.fetch(`${SERVER_BASE_URL}/queues`, { method: 'get', muteHttpExceptions: true });
      if (qResponse.getResponseCode() === 200) {
        const qData = JSON.parse(qResponse.getContentText());

        // We do NOT include 'consumed' here. If a job is consumed but the sheet isn't 'Completed',
        // the script crashed before saving the file. It must be resubmitted.
        const activeQueues = ['inbound', 'processing', 'outbound', 'failed'];

        activeQueues.forEach(qName => {
          if (qData[qName] && Array.isArray(qData[qName])) {
            qData[qName].forEach(serverJob => {
              if (serverJob.job_id) {
                // Map the Job ID to the name of the queue it currently resides in
                serverJobsMap[serverJob.job_id] = qName;
              }
            });
          }
        });
      } else {
        Logger.log(`Warning: Could not fetch /queues. Server returned ${qResponse.getResponseCode()}`);
      }
    } catch (err) {
      Logger.log(`Warning: Error fetching /queues -> ${err.message}`);
    }

    const jobsToPoll = [];
    let downloadFolder = null;
    let immediatelyProcessedCount = 0;

    // STEP B: Process each job
    jobsToRestart.forEach(job => {
      let needsResubmit = true;
      let currentJobId = job.existingJobId;

      // Check if the Job ID exists in our master server queues map
      if (currentJobId && serverJobsMap[currentJobId]) {
        const queueLocation = serverJobsMap[currentJobId];
        needsResubmit = false;

        // If the recovered job is already sitting in outbound, process it immediately instead of polling later
        if (queueLocation === 'outbound') {
           try {
             Logger.log(`Job [${currentJobId}] found in outbound queue. Fetching immediately...`);
             const outResponse = UrlFetchApp.fetch(`${SERVER_BASE_URL}/outbound?job_id=${encodeURIComponent(currentJobId)}`, { method: 'get', muteHttpExceptions: true });
             const outText = outResponse.getContentText();

             if (outText) {
                const result = JSON.parse(outText);
                const status = result.status ? result.status.toLowerCase() : '';

                if (status === 'completed' || status === 'success') {
                   if (!downloadFolder) {
                      downloadFolder = DriveApp.getFolderById(DOWNLOAD_FOLDER_ID);
                   }
                   processCompletedJob(sheet, job.row, currentJobId, result, downloadFolder);
                   immediatelyProcessedCount++;
                   return; // Job fully recovered and downloaded, exit loop iteration & skip adding to jobsToPoll
                } else if (status === 'failed' || status === 'error') {
                   sheet.getRange(job.row, 4, 1, 5)
                        .setValues([[new Date(), `Error: ${result.error || 'Unknown server error'}`, currentJobId, 'Failed', '']])
                        .setFontColor(typeof DATA_FONT_COLOR !== 'undefined' ? DATA_FONT_COLOR : '#000000');
                   return; // Job failed, exit loop iteration & skip adding to jobsToPoll
                }
             }
           } catch (e) {
             Logger.log(`Error immediately fetching outbound job ${currentJobId}: ${e.message}`);
             // If immediate download errors (e.g. server timeout), naturally fall back to regular polling loop below
           }
        }

        Logger.log(`Job [${currentJobId}] found in server queue: ${queueLocation}. Resuming polling.`);

        jobsToPoll.push({
          jobId: currentJobId,
          row: job.row,
          spreadsheetId: ss.getId(),
          sheetName: sheet.getName()
        });

        // Capitalize the queue name for display (e.g., 'Processing')
        const displayStatus = `Recovered (${queueLocation.charAt(0).toUpperCase() + queueLocation.slice(1)})`;
        sheet.getRange(job.row, 7).setValue(displayStatus)
             .setFontColor(typeof DATA_FONT_COLOR !== 'undefined' ? DATA_FONT_COLOR : '#000000');
      }

      // If it wasn't found in the active server queues, it must be resubmitted
      if (needsResubmit) {
        let params = {};
        try {
           params = JSON.parse(job.paramsString);
        } catch(err) {
           Logger.log(`Skipping row ${job.row}: Invalid JSON params.`);
           return;
        }

        const payload = { action: job.action, params: params };
        const options = {
          'method': 'post',
          'contentType': 'application/json',
          'payload': JSON.stringify(payload),
          'muteHttpExceptions': true
        };

        let newStatus = 'Failed to Submit';
        const sentTimestamp = new Date();
        currentJobId = null;

        try {
          const response = UrlFetchApp.fetch(`${SERVER_BASE_URL}/inbound`, options);
          if (response.getResponseCode() === 200 || response.getResponseCode() === 202) {
            const result = JSON.parse(response.getContentText());
            if ((result.status === 'received' || result.status === 'success') && result.job_id) {
              currentJobId = result.job_id;
              newStatus = 'Submitted';
              jobsToPoll.push({
                jobId: currentJobId,
                row: job.row,
                spreadsheetId: ss.getId(),
                sheetName: sheet.getName()
              });
            } else {
               newStatus = `Server Error: ${result.error || 'Unknown'}`;
            }
          } else {
             newStatus = `HTTP Error: ${response.getResponseCode()}`;
          }
        } catch (err) {
          newStatus = 'Connection Error';
          Logger.log(`Error resubmitting row ${job.row}: ${err.toString()}`);
        }

        // Update the Timestamp Sent (Col 1)
        sheet.getRange(job.row, 1).setValue(sentTimestamp).setFontColor(typeof DATA_FONT_COLOR !== 'undefined' ? DATA_FONT_COLOR : '#000000');

        // Ensure "URL to Outbound Message" (Col 5) and other legacy data is explicitly cleared out
        const updateDataRow = [
          '',                   // Column 4: Clears Timestamp Received
          '',                   // Column 5: Clears URL to Outbound Message
          currentJobId || '',   // Column 6: New Job ID
          newStatus,            // Column 7: New Status
          ''                    // Column 8: Clears File link
        ];

        sheet.getRange(job.row, 4, 1, updateDataRow.length)
             .setValues([updateDataRow])
             .setFontColor(typeof DATA_FONT_COLOR !== 'undefined' ? DATA_FONT_COLOR : '#000000');
      }
    });

    // 5. Restart polling with the verified/newly submitted jobs
    if (jobsToPoll.length > 0) {
        scriptProperties.setProperty(BATCH_JOBS_PROPERTY, JSON.stringify(jobsToPoll));
        ScriptApp.newTrigger('pollForBatchResults').timeBased().everyMinutes(1).create();
        ss.toast(`Recovered/Restarted ${jobsToPoll.length} jobs to poll. ${immediatelyProcessedCount > 0 ? immediatelyProcessedCount + ' finished immediately. ' : ''}Polling resumed!`, 'Success', 8);
    } else if (immediatelyProcessedCount > 0) {
        ss.toast(`Successfully recovered and downloaded ${immediatelyProcessedCount} jobs immediately! No more jobs require polling.`, 'Success', 8);
    } else {
        ss.toast('No jobs successfully recovered or restarted.', 'Warning', 8);
    }
  });
}

/**
 * Processes a completed job by downloading its files and updating the sheet.
 * Used by both normal polling mechanisms and the recovery system.
 */
function processCompletedJob(sheet, row, jobId, result, downloadFolder) {
  try {
    // 1. Get Action and safely parse parameters
    const action = sheet.getRange(row, 2).getValue() || '';
    const paramsString = sheet.getRange(row, 3).getValue();
    let originalMessageParams = {};

    if (paramsString) {
      try {
        originalMessageParams = JSON.parse(paramsString);
      } catch (e) {
        Logger.log(`Job ${jobId}: Invalid JSON in params column.`);
      }
    }

    // 2. Determine the Filename based on the Action
    const dateString = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyyMMdd");
    let jsonFilename = "";

    if (action === 'full_recursive_download' && originalMessageParams.url) {
      // Clean URL for filename if it's a website download
      jsonFilename = `${dateString} Data ${originalMessageParams.url.replace(/[^a-z0-9]/gi, '_')}.json`;
    } else {
      // Use fallback JobId naming for all other actions (or if URL is missing)
      jsonFilename = `${dateString} JobId-${jobId}.json`;
    }

    // 3. Safely extract the JSON payload
    // Handles scenarios where the server returns data directly in 'result' instead of 'result.result'
    const payloadToSave = result.result !== undefined ? result.result : result;

    // Ensure we always pass a string to createFile (JSON.stringify returns undefined if payload is undefined)
    let jsonContent = JSON.stringify(payloadToSave, null, 2);
    if (jsonContent === undefined) {
      jsonContent = "{}";
    }

    // 4. Create the JSON file in Drive
    const jsonFile = downloadFolder.createFile(jsonFilename, jsonContent, 'application/json');

    let fileLinks = [];

    // 5. Check for base-64 encoded downloaded files and save them
    const downloadedFiles = (payloadToSave && payloadToSave.downloaded_files) || result.downloaded_files;

    if (downloadedFiles && Array.isArray(downloadedFiles)) {
      downloadedFiles.forEach(fileObj => {
        if (fileObj.filename && fileObj.content_base64) {
          try {
            const decoded = Utilities.base64Decode(fileObj.content_base64);
            const blob = Utilities.newBlob(decoded, 'application/octet-stream', fileObj.filename);
            const savedFile = downloadFolder.createFile(blob);
            fileLinks.push(savedFile.getUrl());
          } catch (decodeErr) {
            Logger.log(`Job ${jobId}: Error decoding file ${fileObj.filename}`);
            fileLinks.push(`Error saving: ${fileObj.filename}`);
          }
        }
      });
    }

    // 6. Update the Spreadsheet with final links and 'Completed' status
    const fileLinksString = fileLinks.join('\n');
    sheet.getRange(row, 4, 1, 5)
         .setValues([[new Date(), jsonFile.getUrl(), jobId, 'Completed', fileLinksString]])
         .setFontColor(typeof DATA_FONT_COLOR !== 'undefined' ? DATA_FONT_COLOR : '#000000');

  } catch (error) {
    // Catch any unexpected file-saving errors here so the script doesn't infinite-loop in polling
    Logger.log(`processCompletedJob failed for Job ${jobId}: ${error.message}`);
    sheet.getRange(row, 4, 1, 5)
         .setValues([[new Date(), '', jobId, 'Download Error', `Error: ${error.message}`]])
         .setFontColor(typeof DATA_FONT_COLOR !== 'undefined' ? DATA_FONT_COLOR : '#000000');
  }
}

function debugSpecificJob() {
  const jobId = '967757b9-e557-4eb9-85df-5580df4b9575'; // Your stuck job ID
  const url = `http://34.79.110.150:8000/outbound?job_id=${jobId}`;

  const response = UrlFetchApp.fetch(url, {muteHttpExceptions: true});
  const text = response.getContentText();

  Logger.log("SERVER RAW RESPONSE: " + text);
}