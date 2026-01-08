/**
 * @OnlyCurrentDoc
 *
 * The above comment directs Apps Script to limit the scope of authorization,
 * confining it to the current spreadsheet only.
 */

// --- Configuration ---
const SERVICE_ACCOUNT_KEY_PROPERTY = 'SERVICE_ACCOUNT_KEY';
const GCP_PROJECT_ID = 'startup-scraping';
const VM_ZONE = 'europe-west1-d';
const VM_INSTANCE_NAME = 'aafai-bus';
const SERVER_BASE_URL = 'http://X.Y.Z.T:8000';
const BOOT_DELAY_SECONDS = 60; // Time to wait for the server to initialize after the VM starts
const DOWNLOAD_FOLDER_ID = '---Folder Id---';
const BATCH_JOBS_PROPERTY = 'activeBatchJobs'; // Script property key for storing active jobs
const JOBS_HEADERS = ['Timestamp Sent', 'Action', 'Inbound Message', 'Timestamp Received', 'URL to Outbound Message', 'Job ID', 'Status', 'File link'];
const JOBS_SHEET_NAME = "Jobs";

/**
 * Adds items to the custom menu.
 * @param {GoogleAppsScript.Base.Menu} menu The menu to add items to.
 */
function addBusMenu(menu) {
  menu.addItem('Run Full Recursive Download', 'showWebsiteDownloadForm');
  menu.addSeparator();
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
  if (DOWNLOAD_FOLDER_ID === 'YOUR_FOLDER_ID_HERE' || DOWNLOAD_FOLDER_ID === '') {
    const errorMessage = 'Configuration Error: Please set the DOWNLOAD_FOLDER_ID constant in the script editor.';
    Logger.log(errorMessage);
    SpreadsheetApp.getUi().alert(errorMessage);
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
function batchScrapingRequests(sheet, inboundMessages) {
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

  ensureVmIsRunning(() => {
    const newlySubmittedJobs = [];
    inboundMessages.forEach((message, index) => {
      // Calculate the specific row for this job based on the append position
      const currentRow = nextRowIndex + index;

      const payload = { action: message.action, params: message.params };
      const options = { 'method': 'post', 'contentType': 'application/json', 'payload': JSON.stringify(payload) };
      const sentTimestamp = new Date();
      let jobId = null, status = 'Failed to Submit';

      try {
        const response = UrlFetchApp.fetch(`${SERVER_BASE_URL}/inbound`, options);
        const result = JSON.parse(response.getContentText());

        if (result.status === 'received' && result.job_id) {
          jobId = result.job_id;
          status = 'Submitted';
          Logger.log(`Task successfully submitted. Job ID: ${jobId}`);
          newlySubmittedJobs.push({
            jobId: jobId,
            row: currentRow, // Save the calculated row
            spreadsheetId: sheet.getParent().getId(),
            sheetName: sheet.getName()
          });
        } else {
          Logger.log(`Failed to submit task. Server response: ${response.getContentText()}`);
        }
      } catch (e) {
        Logger.log(`An error occurred while contacting the server: ${e.toString()}`);
      }

      // Initialize row with empty string for 'File link' column
      const rowData = [sentTimestamp, message.action, JSON.stringify(message.params), '', '', jobId, status, ''];

      // Write to the specific calculated row AND APPLY FONT COLOR
      sheet.getRange(currentRow, 1, 1, rowData.length)
           .setValues([rowData])
           .setFontColor(DATA_FONT_COLOR);
    });

    if (newlySubmittedJobs.length > 0) {
      allJobsToPoll.push(...newlySubmittedJobs);
      scriptProperties.setProperty(BATCH_JOBS_PROPERTY, JSON.stringify(allJobsToPoll));
      deleteTriggers('pollForBatchResults');
      ScriptApp.newTrigger('pollForBatchResults').timeBased().everyMinutes(1).create();
      SpreadsheetApp.getActiveSpreadsheet().toast(`${newlySubmittedJobs.length} tasks appended to ${sheet.getName()}! Polling.`, 'Success', 5);
    } else {
      SpreadsheetApp.getActiveSpreadsheet().toast('No tasks were successfully submitted.', 'Error', 5);
    }
  });
}

/**
 * Menu function to clear jobs based on specific statuses.
 * Covers user request and actual script status strings.
 */
function clearAllJobs() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  // UPDATED: Use the global constant
  const jobsSheet = ss.getSheetByName(JOBS_SHEET_NAME);

  if (!jobsSheet) {
    SpreadsheetApp.getActiveSpreadsheet().toast(`Sheet "${JOBS_SHEET_NAME}" not found.`, "Error");
    return;
  }

  const statusesToRemove = ["Submitted", "Pending", "Polling", "Complete", "Failed", "Download Error", "Failed to Submit"];

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
  // Loop through data. i corresponds to (Row Number - 2)
  for (let i = 0; i < data.length; i++) {
    const status = data[i][6]; // Column 7 is index 6
    if (statusArray.includes(status)) {
      // Store actual sheet row number (i + 2)
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
    // 1. Remove the job that was on this row (if it existed in active jobs)
    // 2. Decrement the 'row' property for any job in THIS sheet that was BELOW the deleted row
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
 * Polls the outbound queue for multiple job results, saves decoded files to Drive,
 * and updates the sheet with links.
 */
function pollForBatchResults() {
  const scriptProperties = PropertiesService.getScriptProperties();
  const jobsDataString = scriptProperties.getProperty(BATCH_JOBS_PROPERTY);

  if (!jobsDataString) {
    Logger.log('No active batch jobs found. Stopping polling.');
    deleteTriggers('pollForBatchResults');
    return;
  }

  const activeJobs = JSON.parse(jobsDataString);
  const remainingJobs = [];

  const jobsBySheet = activeJobs.reduce((acc, job) => {
    const key = `${job.spreadsheetId}::${job.sheetName}`;
    if (!acc[key]) acc[key] = { ssId: job.spreadsheetId, sheetName: job.sheetName, jobs: [] };
    acc[key].jobs.push(job);
    return acc;
  }, {});

  for (const key in jobsBySheet) {
    const { ssId, sheetName, jobs } = jobsBySheet[key];
    let sheet;
    try {
      const ss = SpreadsheetApp.openById(ssId);
      sheet = ss.getSheetByName(sheetName);
      if (!sheet) throw new Error(`Sheet "${sheetName}" not found.`);
    } catch (e) {
      Logger.log(`Skipping jobs for sheet ${sheetName}: ${e.message}`);
      remainingJobs.push(...jobs);
      continue;
    }

    const downloadFolder = DriveApp.getFolderById(DOWNLOAD_FOLDER_ID);

    jobs.forEach(job => {
      const { jobId, row } = job;
      const url = `${SERVER_BASE_URL}/outbound?job_id=${encodeURIComponent(jobId)}`;
      const options = { 'method': 'get', 'muteHttpExceptions': true };

      try {
        const response = UrlFetchApp.fetch(url, options);
        const responseText = response.getContentText();

        if (!responseText || responseText.trim() === '') {
          // UPDATE: Apply font color
          sheet.getRange(row, 7).setValue('Polling').setFontColor(DATA_FONT_COLOR);
          remainingJobs.push(job);
          return;
        }

        const result = JSON.parse(responseText);

        if (result.status === 'complete') {
          // 1. Save the Metadata JSON (Standard Output)
          const originalMessageParams = JSON.parse(sheet.getRange(row, 3).getValue());
          const originalUrl = originalMessageParams.url || 'unknown_url';
          const dateString = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyyMMdd");
          const jsonFilename = `${dateString} Data ${originalUrl.replace(/[^a-z0-9]/gi, '_')}.json`;

          const jsonFile = downloadFolder.createFile(jsonFilename, JSON.stringify(result.result, null, 2), 'application/json');

          // 2. Process 'downloaded_files' Array
          let fileLinks = [];
          const data = result.result;

          if (data && data.downloaded_files && Array.isArray(data.downloaded_files)) {
            data.downloaded_files.forEach(fileObj => {
              if (fileObj.filename && fileObj.content_base64) {
                try {
                  const decoded = Utilities.base64Decode(fileObj.content_base64);
                  // Create blob. 'application/octet-stream' allows Drive to auto-detect type via extension (e.g. .pdf)
                  const blob = Utilities.newBlob(decoded, 'application/octet-stream', fileObj.filename);
                  const savedFile = downloadFolder.createFile(blob);
                  fileLinks.push(savedFile.getUrl());
                } catch (decodeErr) {
                  Logger.log(`Error decoding file ${fileObj.filename}: ${decodeErr}`);
                  fileLinks.push(`Error: ${fileObj.filename}`);
                }
              }
            });
          }

          // Join multiple links with a newline if multiple files exist
          const fileLinksString = fileLinks.join('\n');

          // Update Columns 4 to 8: [Date, JSON Link, JobID, Status, File Link]
          // UPDATE: Apply font color
          sheet.getRange(row, 4, 1, 5)
               .setValues([[new Date(), jsonFile.getUrl(), jobId, 'Complete', fileLinksString]])
               .setFontColor(DATA_FONT_COLOR);

        } else if (result.status === 'failed') {
          // UPDATE: Apply font color
          sheet.getRange(row, 4, 1, 5)
               .setValues([[new Date(), `Error: ${result.error}`, jobId, 'Failed', '']])
               .setFontColor(DATA_FONT_COLOR);
        } else {
          // UPDATE: Apply font color
          sheet.getRange(row, 7).setValue(result.status || 'Polling').setFontColor(DATA_FONT_COLOR);
          remainingJobs.push(job);
        }
      } catch (e) {
        Logger.log(`Error polling job ${jobId}: ${e.toString()}`);
        // UPDATE: Apply font color
        sheet.getRange(row, 4, 1, 5)
             .setValues([[new Date(), e.toString(), jobId, 'Download Error', '']])
             .setFontColor(DATA_FONT_COLOR);
      }
    });
  }

  if (remainingJobs.length > 0) {
    scriptProperties.setProperty(BATCH_JOBS_PROPERTY, JSON.stringify(remainingJobs));
  } else {
    scriptProperties.deleteProperty(BATCH_JOBS_PROPERTY);
    deleteTriggers('pollForBatchResults');
  }
}


/**
 * Ensures the VM is running before executing a callback function.
 * @param {function} callback The function to execute after ensuring the VM is running.
 */
function ensureVmIsRunning(callback) {
  const instance = getVmDetails();
  const status = instance ? instance.status : 'TERMINATED';

  if (status !== 'RUNNING') {
    Logger.log(`VM is not running. Starting VM: ${VM_INSTANCE_NAME}`);
    startVm();
    Logger.log(`Waiting for ${BOOT_DELAY_SECONDS} seconds for the server to boot...`);
    Utilities.sleep(BOOT_DELAY_SECONDS * 1000);
  } else {
    Logger.log(`VM is already running.`);
  }

  callback();
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
 * Deletes all triggers for a given function name to prevent duplicates.
 * @param {string} functionName The name of the function whose triggers should be deleted.
 */
function deleteTriggers(functionName) {
  const triggers = ScriptApp.getProjectTriggers();
  for (const trigger of triggers) {
    if (trigger.getHandlerFunction() === functionName) {
      ScriptApp.deleteTrigger(trigger);
    }
  }
  Logger.log(`Deleted triggers for function: ${functionName}`);
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
  const ui = SpreadsheetApp.getUi();
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
      action: 'full_recursive_download',
      params: { 'url': 'https://mit.edu/', 'max_depth': 0 }
    },
    {
      action: 'full_recursive_download',
      params: { 'url': 'https://eurofins.com', 'max_depth': 0 }
    }
  ];

  batchScrapingRequests(sheet, inboundMessages);
}

function getUi() {
  try {
    return SpreadsheetApp.getUi();
  } catch(e) {
    return null;
  }
}