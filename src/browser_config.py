import os
from selenium.webdriver.chrome.options import Options

def get_chrome_options():
    """
    Configures and returns Chrome Options for Selenium.
    
    Respects the 'HEADLESS_BROWSER' environment variable.
    Defaults to headless='true'.
    Set HEADLESS_BROWSER='false' to see the browser UI.
    """
    options = Options()
    
    # Check environment variable, default to 'true' (headless)
    is_headless = os.environ.get('HEADLESS_BROWSER', 'true').lower() == 'true'
    
    if is_headless:
        options.add_argument("--headless=new")
    
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    
    return options

def get_headless_status():
    """Returns True if the browser should be headless, False otherwise."""
    return os.environ.get('HEADLESS_BROWSER', 'true').lower() == 'true'
