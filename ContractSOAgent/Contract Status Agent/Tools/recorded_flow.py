import re
from playwright.sync_api import Playwright, sync_playwright, expect
from dotenv import load_dotenv
import os


def run(playwright: Playwright) -> None:
    load_dotenv()
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://jswsteel.my.site.com/jswone/s/login/")
    page.get_by_role("textbox", name="Username").click()
    page.get_by_role("textbox", name="Username").fill(os.getenv("SF_USERNAME", ""))
    page.get_by_role("textbox", name="Password").click()
    page.get_by_role("textbox", name="Password").click()
    page.get_by_role("textbox", name="Password").fill(os.getenv("SF_PASSWORD", ""))
    page.get_by_role("button", name="Log in").click()
    page.get_by_role("menuitem", name="Contract").click()
    page.get_by_role("button", name="Select a List View: Contracts").click()
    page.locator("span").filter(has_text="JSW One All Contracts").first.click()
    page.get_by_role("button", name="Sort Created Date").click()
    page.close()

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
