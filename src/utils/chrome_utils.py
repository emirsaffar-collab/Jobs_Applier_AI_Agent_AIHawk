import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager  # Import webdriver_manager
import urllib
from src.logging import logger

def chrome_browser_options():
    logger.debug("Setting Chrome browser options")
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("window-size=1200x800")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-translate")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-logging")
    options.add_argument("--disable-autofill")
    options.add_argument("--disable-plugins")
    options.add_argument("--disable-animations")
    options.add_argument("--disable-cache")
    options.add_argument("--incognito")
    logger.debug("Using Chrome in incognito mode")
    
    return options

def init_browser() -> webdriver.Chrome:
    try:
        options = chrome_browser_options()
        # Use webdriver_manager to handle ChromeDriver
        driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
        logger.debug("Chrome browser initialized successfully.")
        return driver
    except Exception as e:
        logger.error(f"Failed to initialize browser: {str(e)}")
        raise RuntimeError(f"Failed to initialize browser: {str(e)}")



def HTML_to_PDF(html_content, driver):
    """Convert an HTML string to PDF and return it as a base64 string.

    :param html_content: HTML string to convert.
    :param driver: Selenium WebDriver instance.
    :return: Base64-encoded PDF string.
    :raises ValueError: If HTML input is not a valid string.
    :raises RuntimeError: If a WebDriver exception occurs.
    """
    if not isinstance(html_content, str) or not html_content.strip():
        raise ValueError("HTML content must be a non-empty string.")

    encoded_html = urllib.parse.quote(html_content)
    data_url = f"data:text/html;charset=utf-8,{encoded_html}"

    try:
        driver.get(data_url)
        time.sleep(2)

        pdf_base64 = driver.execute_cdp_cmd("Page.printToPDF", {
            "printBackground": True,
            "landscape": False,
            "paperWidth": 8.27,               # A4 width in inches
            "paperHeight": 11.69,             # A4 height in inches
            "marginTop": 0.8,
            "marginBottom": 0.8,
            "marginLeft": 0.5,
            "marginRight": 0.5,
            "displayHeaderFooter": False,
            "preferCSSPageSize": True,
            "generateDocumentOutline": False,
            "generateTaggedPDF": False,
            "transferMode": "ReturnAsBase64",
        })
        return pdf_base64['data']
    except Exception as e:
        logger.error(f"WebDriver exception: {e}")
        raise RuntimeError(f"WebDriver exception: {e}")
