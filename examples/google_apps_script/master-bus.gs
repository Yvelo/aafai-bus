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
const BOOT_DELAY_SECONDS = 3; // Time to wait for the server to initialize after the VM starts

/**
 * Adds a custom menu to the spreadsheet when it's opened.
 */
function onOpen() {
  SpreadsheetApp.getUi()
      .createMenu('AAF-Bus')
      .addItem('Run Full Recursive Download', 'startAsyncTask')
      .addSeparator()
      .addItem('Set Service Account Key', 'setServiceAccountKey')
      .addToUi();
}

/**
 * Ensures the VM is running before executing a callback function.
 * This function acts as a gatekeeper for any action that requires the server.
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
    headers: {
      'Authorization': 'Bearer ' + service.getAccessToken()
    },
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
    headers: {
      'Authorization': 'Bearer ' + service.getAccessToken()
    },
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
}

/**
 * Configures and returns an OAuth2 service for GCP using a service account.
 * This uses the OAuth2 for Apps Script library.
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
        .setScope('https://www.googleapis.com/auth/cloud-platform');
}

/**
 * Starts a long-running task by sending it to the Python server.
 * It ensures the server is running and then initiates a polling mechanism.
 */
function startAsyncTask() {
  ensureVmIsRunning(() => {
    const action = 'full_recursive_download';
    const params = {
      'url': 'http://info.cern.ch' // Example website to download
    };
    const payload = {
      action: action,
      params: params
    };
    const options = {
      'method': 'post',
      'contentType': 'application/json',
      'payload': JSON.stringify(payload)
    };

    try {
      const response = UrlFetchApp.fetch(`${SERVER_BASE_URL}/inbound`, options);
      const result = JSON.parse(response.getContentText());

      if (result.status === 'received' && result.job_id) {
        const jobId = result.job_id;
        Logger.log(`Task successfully submitted. Job ID: ${jobId}`);
        SpreadsheetApp.getActiveSpreadsheet().toast(`Task submitted! Job ID: ${jobId}`, 'Success', 5);

        // Store the job ID and set up a polling trigger
        PropertiesService.getScriptProperties().setProperty('currentJobId', jobId);
        deleteTriggers('pollForResult');
        ScriptApp.newTrigger('pollForResult')
          .timeBased()
          .everyMinutes(1)
          .create();
        Logger.log('Polling trigger created. Waiting for the server to process the task...');
      } else {
        Logger.log(`Failed to submit task. Server response: ${response.getContentText()}`);
        SpreadsheetApp.getActiveSpreadsheet().toast('Failed to submit task.', 'Error', 5);
      }
    } catch (e) {
      Logger.log(`An error occurred while contacting the server: ${e.toString()}`);
      SpreadsheetApp.getActiveSpreadsheet().toast('Server is unreachable.', 'Error', 5);
    }
  });
}

/**
 * Polls the outbound queue for the result of a submitted job.
 * This function is intended to be run by a time-based trigger.
 */
function pollForResult() {
  const jobId = PropertiesService.getScriptProperties().getProperty('currentJobId');
  if (!jobId) {
    Logger.log('No active job ID found. Stopping polling.');
    deleteTriggers('pollForResult');
    return;
  }

  Logger.log(`Polling for result of Job ID: ${jobId}`);
  const url = `${SERVER_BASE_URL}/outbound?job_id=${encodeURIComponent(jobId)}`;
  const options = {
    'method': 'get',
    'muteHttpExceptions': true
  };

  try {
    const response = UrlFetchApp.fetch(url, options);
    const result = JSON.parse(response.getContentText());

    if (result.status === 'complete') {
      Logger.log('--- JOB COMPLETE ---');
      // The result from the Selenium action is an object
      const taskResult = result.result; 
      Logger.log(`Text Size: ${taskResult.size_bytes} bytes`);
      if(taskResult.warning) {
        Logger.log(`Warning: ${taskResult.warning}`);
      }
      // For demonstration, we'll just log the first 500 chars of the text
      Logger.log(`Extracted Text (first 500 chars): ${taskResult.text.substring(0, 500)}`);
      
      SpreadsheetApp.getActiveSpreadsheet().toast('Task completed successfully!', 'Status', 5);
      PropertiesService.getScriptProperties().deleteProperty('currentJobId');
      deleteTriggers('pollForResult');

    } else if (result.status === 'failed') {
      Logger.log('--- JOB FAILED ---');
      Logger.log(`Error message: ${result.error}`);
      SpreadsheetApp.getActiveSpreadsheet().toast(`Task failed: ${result.error}`, 'Status', 5);
      PropertiesService.getScriptProperties().deleteProperty('currentJobId');
      deleteTriggers('pollForResult');
    } else {
      Logger.log('Job is still pending. Will check again later.');
    }
  } catch (e) {
    Logger.log(`An error occurred during polling: ${e.toString()}`);
  }
}

/**
 * Prompts the user to set the Service Account Key via a dialog box.
 * The key is stored in UserProperties, specific to the user and the script.
 */
function setServiceAccountKey() {
  const ui = SpreadsheetApp.getUi();
  const response = ui.prompt('Set Service Account Key', 'Please paste your entire Google Cloud Service Account Key (JSON):', ui.ButtonSet.OK_CANCEL);
  if (response.getSelectedButton() == ui.Button.OK) {
    const serviceAccountKey = response.getResponseText().trim();
    if (serviceAccountKey) {
      try {
        JSON.parse(serviceAccountKey); // Validate that the input is valid JSON
        PropertiesService.getUserProperties().setProperty(SERVICE_ACCOUNT_KEY_PROPERTY, serviceAccountKey);
        ui.alert('Success', 'Service Account Key has been set for this user.', ui.ButtonSet.OK);
      } catch (e) {
        ui.alert('Error', 'Invalid JSON format. Please enter a valid Service Account Key.', ui.ButtonSet.OK);
      }
    } else {
      ui.alert('Cancelled', 'No Service Account Key was entered.', ui.ButtonSet.OK);
    }
  }
}

/**
 * Retrieves the Service Account Key from UserProperties.
 * @return {object | null} The parsed Service Account Key JSON object or null if not set.
 */
function getServiceAccountKey() {
  const userProperties = PropertiesService.getUserProperties();
  const serviceAccountKeyJSON = userProperties.getProperty(SERVICE_ACCOUNT_KEY_PROPERTY);

  if (!serviceAccountKeyJSON) {
    SpreadsheetApp.getUi().alert('Service Account Key is not set. Please use the "AAF-Bus > Set Service Account Key" menu to set it.');
    return null;
  }
  return JSON.parse(serviceAccountKeyJSON);
}
