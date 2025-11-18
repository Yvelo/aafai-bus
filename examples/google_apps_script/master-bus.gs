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
const SERVER_BASE_URL = 'http://34.79.110.150:8000';
const BOOT_DELAY_SECONDS = 10; // Time to wait for the server to initialize after the VM starts
const DOWNLOAD_FOLDER_ID = '1CR4ziiHQezeM19MK8p1Irb3S_xXsIw9Z';
const BATCH_JOBS_PROPERTY = 'activeBatchJobs'; // Script property key for storing active jobs

/**
 * Adds items to the custom menu.
 * @param {GoogleAppsScript.Base.Menu} menu The menu to add items to.
 */
function addBusMenu(menu) {
  menu.addItem('Run Full Recursive Download', 'showWebsiteDownloadForm');
  menu.addSeparator();
  menu.addItem('Set Service Account Key', 'setServiceAccountKey');
}

/**
 * Displays a custom HTML form as a modal dialog.
 */
function showWebsiteDownloadForm() {
  const template = HtmlService.createTemplateFromFile('WebsiteDownload');
  // This function assumes you have a function to get your logo's base64 string.
  // If not, you can remove this line and the corresponding logic in the HTML.
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
  // Create a new sheet for each batch job with a timestamp to avoid conflicts.
  const sheetName = "Scraping_Job_" + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd HH:mm:ss");
  const sheet = ss.insertSheet(sheetName);

  const inboundMessages = urls.map(url => ({
    action: 'full_recursive_download',
    params: {
      'url': url,
      'max_depth': parseInt(max_depth, 10)
    }
  }));

  batchScrapingRequests(sheet, inboundMessages);

  return 'Task submitted! You can close this window. Check the new sheet for progress.';
}

/**
 * Processes a batch of inbound scraping messages, prepares a target sheet,
 * and populates it with job tracking information.
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet The sheet object where results will be tracked.
 * @param {Array<Object>} inboundMessages An array of message objects to be processed.
 */
function batchScrapingRequests(sheet, inboundMessages) {
  sheet.clear();
  const headers = [
    'Timestamp Sent', 'Action', 'Inbound Message', 'Timestamp Received',
    'URL to Outbound Message', 'Job ID', 'Status'
  ];
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold');
  SpreadsheetApp.flush();

  const scriptProperties = PropertiesService.getScriptProperties();
  // Get existing jobs to append the new ones
  let allJobsToPoll = JSON.parse(scriptProperties.getProperty(BATCH_JOBS_PROPERTY) || '[]');

  ensureVmIsRunning(() => {
    const newlySubmittedJobs = [];
    inboundMessages.forEach((message, index) => {
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
            row: index + 2, // +2 because of 1-based index and header row
            spreadsheetId: sheet.getParent().getId(), // Store spreadsheet context
            sheetName: sheet.getName() // Store sheet context
          });
        } else {
          Logger.log(`Failed to submit task. Server response: ${response.getContentText()}`);
        }
      } catch (e) {
        Logger.log(`An error occurred while contacting the server: ${e.toString()}`);
      }

      const rowData = [sentTimestamp, message.action, JSON.stringify(message.params), '', '', jobId, status];
      sheet.getRange(index + 2, 1, 1, rowData.length).setValues([rowData]);
    });

    if (newlySubmittedJobs.length > 0) {
      allJobsToPoll.push(...newlySubmittedJobs);
      scriptProperties.setProperty(BATCH_JOBS_PROPERTY, JSON.stringify(allJobsToPoll));

      deleteTriggers('pollForBatchResults');
      ScriptApp.newTrigger('pollForBatchResults').timeBased().everyMinutes(1).create();

      Logger.log('Polling trigger created/re-established for batch jobs.');
      SpreadsheetApp.getActiveSpreadsheet().toast(`${newlySubmittedJobs.length} tasks submitted! Polling for results.`, 'Success', 5);
    } else {
      SpreadsheetApp.getActiveSpreadsheet().toast('No tasks were successfully submitted.', 'Error', 5);
    }
  });
}


/**
 * Polls the outbound queue for multiple job results from potentially multiple spreadsheets,
 * saves them to Google Drive, and updates the corresponding rows in the source sheets.
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

  // Group jobs by spreadsheet and sheet to process them efficiently
  const jobsBySheet = activeJobs.reduce((acc, job) => {
    const key = `${job.spreadsheetId}::${job.sheetName}`;
    if (!acc[key]) {
      acc[key] = { ssId: job.spreadsheetId, sheetName: job.sheetName, jobs: [] };
    }
    acc[key].jobs.push(job);
    return acc;
  }, {});

  for (const key in jobsBySheet) {
    const { ssId, sheetName, jobs } = jobsBySheet[key];
    let sheet;
    try {
      const ss = SpreadsheetApp.openById(ssId);
      sheet = ss.getSheetByName(sheetName);
      if (!sheet) {
        throw new Error(`Sheet "${sheetName}" not found.`);
      }
    } catch (e) {
      Logger.log(`Cannot access spreadsheet/sheet: ${ssId}/${sheetName}. Error: ${e.message}. Skipping jobs for this sheet.`);
      // These jobs are now orphaned, decide if they should be kept or discarded. Keeping them for now.
      remainingJobs.push(...jobs);
      continue;
    }

    jobs.forEach(job => {
      const { jobId, row } = job;
      Logger.log(`Polling for Job ID: ${jobId} in Sheet: ${sheetName}`);
      const url = `${SERVER_BASE_URL}/outbound?job_id=${encodeURIComponent(jobId)}`;
      const options = { 'method': 'get', 'muteHttpExceptions': true };

      try {
        const response = UrlFetchApp.fetch(url, options);
        const responseText = response.getContentText();

        if (!responseText || responseText.trim() === '') {
          sheet.getRange(row, 7).setValue('Polling');
          remainingJobs.push(job);
          return;
        }

        const result = JSON.parse(responseText);

        if (result.status === 'complete') {
          const originalMessageParams = JSON.parse(sheet.getRange(row, 3).getValue());
          const originalUrl = originalMessageParams.url || 'unknown_url';
          const dateString = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyyMMdd");
          const filename = `${dateString} Download ${originalUrl.replace(/[^a-z0-9]/gi, '_')}.json`;
          const fileContent = JSON.stringify(result.result, null, 2);
          const downloadFolder = DriveApp.getFolderById(DOWNLOAD_FOLDER_ID);
          const file = downloadFolder.createFile(filename, fileContent, 'application/json');

          sheet.getRange(row, 4, 1, 4).setValues([[new Date(), file.getUrl(), jobId, 'Complete']]);
        } else if (result.status === 'failed') {
          sheet.getRange(row, 4, 1, 4).setValues([[new Date(), `Error: ${result.error}`, jobId, 'Failed']]);
        } else {
          sheet.getRange(row, 7).setValue(result.status || 'Polling');
          remainingJobs.push(job);
        }
      } catch (e) {
        Logger.log(`An error occurred polling for job ${jobId}: ${e.toString()}`);
        sheet.getRange(row, 4, 1, 4).setValues([[new Date(), e.toString(), jobId, 'Download Error']]);
      }
    });
  }

  if (remainingJobs.length > 0) {
    scriptProperties.setProperty(BATCH_JOBS_PROPERTY, JSON.stringify(remainingJobs));
    Logger.log(`${remainingJobs.length} jobs remaining.`);
  } else {
    Logger.log('All batch jobs complete. Deleting trigger.');
    scriptProperties.deleteProperty(BATCH_JOBS_PROPERTY);
    deleteTriggers('pollForBatchResults');
    // Note: Cannot use Toast messages in a trigger-run function.
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
  const ui =getUi();
  const userProperties = PropertiesService.getUserProperties();
  const serviceAccountKeyJSON = userProperties.getProperty(SERVICE_ACCOUNT_KEY_PROPERTY);

  if (!serviceAccountKeyJSON) {
    if (ui) {ui.alert('Service Account Key is not set. Please use the "aafai-bus > Set Service Account Key" menu to set it.');}
    return null;
  }
  return JSON.parse(serviceAccountKeyJSON);
}

/**
 * NEW FUNCTION
 * A test function to demonstrate batchScrapingRequests with sample URLs.
 * Can be run from the custom 'aafai-bus' menu.
 */
function testBatchScraping() {
  const ui =getUi();
  if (DOWNLOAD_FOLDER_ID === 'YOUR_FOLDER_ID_HERE' || DOWNLOAD_FOLDER_ID === '') {
    if (ui) {SpreadsheetApp.getUi().alert('Configuration Needed', 'Please set the DOWNLOAD_FOLDER_ID constant in the script editor before running.', SpreadsheetApp.getUi().ButtonSet.OK);}
    return;
  }

  const sheetName = "Scraping_Job_" + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd HH:mm:ss");
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.insertSheet(sheetName);
  const inboundMessages = [{
      action: 'full_recursive_download',
      params: { 'url': 'https://mit.edu/', 'max_depth': 0 }
    },
    {
      action: 'full_recursive_download',
      params: { 'url': 'https://www.airbooster.fr/en/', 'max_depth': 0 }
    }
  ];

  batchScrapingRequests(sheet, inboundMessages);
}