"""
Tool: navigate_contract_page.py
Purpose: Log into JSW Steel portal and stop on the Contract list page.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright


load_dotenv(Path(__file__).with_name(".env"))

CONTRACTS_URL = os.getenv(
    "JSW_CONTRACTS_URL",
    "https://jswsteel.my.site.com/jswone/s/recordlist/Contract/Default",
)


def navigate_to_contract_page(headless: bool | None = None) -> dict:
    login_url = first_env("SALESFORCE_URL", "SF_PORTAL_URL", "JSW_PORTAL_URL")
    username = first_env("SALESFORCE_USERNAME", "SF_USERNAME", "JSW_PORTAL_USERNAME")
    password = first_env("SALESFORCE_PASSWORD", "SF_PASSWORD", "JSW_PORTAL_PASSWORD")

    if not login_url or not username or not password:
        raise RuntimeError(
            "Missing portal config. Set SALESFORCE_URL, SALESFORCE_USERNAME, "
            "and SALESFORCE_PASSWORD, or the supported SF_/JSW_ aliases."
        )

    if headless is None:
        headless = os.getenv("PLAYWRIGHT_HEADLESS", "False").strip().lower() == "true"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            login(page, login_url, username, password)
            page.goto(CONTRACTS_URL, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_selector("text=Contracts", timeout=30_000)
            page.wait_for_timeout(1_500)
            return {"success": True, "url": page.url}
        except PlaywrightTimeout as exc:
            raise RuntimeError(f"Timed out navigating to Contract page: {exc}") from exc
        finally:
            browser.close()


def login(page, login_url: str, username: str, password: str) -> None:
    page.goto(login_url, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_selector("role=textbox[name='Username']", timeout=20_000)
    page.get_by_role("textbox", name="Username").fill(username)
    page.get_by_role("textbox", name="Password").fill(password)
    start_url = page.url
    page.get_by_role("button", name="Log in").click()
    page.wait_for_url(lambda url: url.rstrip("/") != start_url.rstrip("/"), timeout=60_000)
    page.wait_for_selector("role=menuitem[name='Contract']", timeout=30_000)


def first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


if __name__ == "__main__":
    print(navigate_to_contract_page())
