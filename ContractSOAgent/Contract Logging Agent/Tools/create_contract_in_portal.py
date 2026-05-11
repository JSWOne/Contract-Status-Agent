"""
Tool: create_contract_in_portal.py
Purpose: Open JSW Steel portal, create/fill a New Contract form, wait for save,
         and return the generated Contract Number.

Adapted from old working project:
C:\\Users\\2751342\\OneDrive - JSW\\Desktop\\VS Code\\SO Contract Agent\\Contract logging\\tools\\salesforce_login.py
"""

import logging
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright


load_dotenv(Path(__file__).with_name(".env"), override=True)

log = logging.getLogger(__name__)
DEBUG_DIR = Path(__file__).parent.parent / ".tmp"
CONTRACTS_LIST_URL = os.getenv(
    "JSW_CONTRACTS_URL",
    "https://jswsteel.my.site.com/jswone/s/recordlist/Contract/Default",
)
NEW_CONTRACT_URL = os.getenv(
    "JSW_NEW_CONTRACT_URL",
    "https://jswsteel.my.site.com/jswone/s/contract/new",
)

LOOKUP_SELECTORS = {
    "Sold to Party": [
        'c-reusable-lookup[data-id="Sold To"] input',
        'input[placeholder="Search Sold To Party..."]',
        'input[placeholder*="Sold To Party"]',
    ],
    "Ship to Party": [
        'c-reusable-lookup[data-id="Ship To"] input',
        'input[placeholder="Search Ship To Party..."]',
        'input[placeholder*="Ship To Party"]',
    ],
    "Payer": [
        'c-reusable-lookup[data-id="Payer"] input',
        'input[placeholder="Payer..."]',
        'input[placeholder*="Payer"]',
    ],
    "Division": [
        'c-reusable-lookup[data-id="Division"] input',
        'input[placeholder="Search Division..."]',
        'input[placeholder*="Division"]',
    ],
}

COMBOBOX_SELECTORS = {
    "Contract Type": [
        'lightning-combobox:has(label:has-text("Contract Type")) button',
        'button[name="Contract_Type"]',
        'button[name="Contract_Type__c"]',
        'button[aria-label*="Contract Type"]',
    ],
    "Contract Source": [
        'button[name="Contract_Source__c"]',
        'lightning-combobox:has(label:has-text("Contract Source")) button',
        'button[aria-label*="Contract Source"]',
    ],
    "Distribution Channel": [
        'button[name="Distribution_Channel"]',
        'lightning-combobox:has(label:has-text("Distribution Channel")) button',
        'button[aria-label*="Distribution Channel"]',
    ],
}


def create_contract_in_portal(contract_data: dict, ticket_id: str = "") -> str:
    """Fill the New Contract form and wait for save, then return contract number."""
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    headless = os.getenv("PLAYWRIGHT_HEADLESS", "False").strip().lower() == "true"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=["--start-maximized"])
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        try:
            print(f"[contract-create] {ticket_id}: login started", flush=True)
            login(page)
            print(f"[contract-create] {ticket_id}: login completed", flush=True)
            print(f"[contract-create] {ticket_id}: opening new contract form", flush=True)
            navigate_to_new_contract(page)
            print(
                f"[contract-create] {ticket_id}: new contract page ready "
                f"{compact_json(collect_form_diagnostics(page, contract_data), max_len=1800)}",
                flush=True,
            )
            print(f"[contract-create] {ticket_id}: filling contract form", flush=True)
            fill_contract_form(page, contract_data)
            print(
                f"[contract-create] {ticket_id}: form diagnostics "
                f"{json.dumps(collect_form_diagnostics(page, contract_data), ensure_ascii=True)}",
                flush=True,
            )
            print(f"[contract-create] {ticket_id}: saving contract", flush=True)
            click_save_button(page, contract_data)
            log.info("Waiting for save for ticket %s", ticket_id)
            wait_for_save(page, timeout_ms=600_000)
            contract_number = extract_contract_number(page)
            if not contract_number:
                raise RuntimeError("Contract was saved but generated Contract Number was not captured")
            print(f"[contract-create] {ticket_id}: created contract {contract_number}", flush=True)
            return contract_number
        finally:
            browser.close()


def open_new_contract_for_recording(hold_seconds: int = 1800, inspector: bool = False) -> None:
    """Open the New Contract modal and pause so the user can demonstrate the flow."""
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        page = browser.new_page(no_viewport=True)
        try:
            login(page)
            navigate_to_new_contract(page)
            dump_html(page, "recording_start_new_contract_form")
            screenshot(page, "recording_start_new_contract_form")
            print(f"New Contract form is open. Browser will stay open for {hold_seconds} seconds.")
            print("Close the browser manually when recording is complete.")
            if inspector:
                print("Opening Playwright Inspector. Click Resume after recording the needed actions.")
                page.pause()
            time.sleep(hold_seconds)
        finally:
            browser.close()


def login(page) -> None:
    url = first_env("SALESFORCE_URL", "SF_PORTAL_URL", "JSW_PORTAL_URL")
    username = first_env("SALESFORCE_USERNAME", "SF_USERNAME", "JSW_PORTAL_USERNAME")
    password = first_env("SALESFORCE_PASSWORD", "SF_PASSWORD", "JSW_PORTAL_PASSWORD")
    if not url or not username or not password:
        raise RuntimeError("Missing portal login config in .env")

    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_selector('input[placeholder="Username"]', timeout=20_000)
    page.locator('input[placeholder="Username"]').fill(username)
    page.locator('input[type="password"]').fill(password)
    start_url = page.url
    page.locator('button:has-text("Log in")').click()
    page.wait_for_url(lambda current: current.rstrip("/") != start_url.rstrip("/"), timeout=60_000)
    page.wait_for_timeout(2_000)
    screenshot(page, "01_logged_in")


def navigate_to_new_contract(page) -> None:
    page.goto(CONTRACTS_LIST_URL, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(3_000)
    screenshot(page, "02_contracts_list")

    clicked = click_new_button(page)
    if not clicked:
        page.goto(NEW_CONTRACT_URL, wait_until="domcontentloaded", timeout=20_000)

    page.wait_for_timeout(4_000)
    ensure_new_contract_form_ready(page)
    screenshot(page, "03_new_contract_form")


def click_new_button(page) -> bool:
    try:
        button = page.get_by_role("button", name="New")
        button.wait_for(state="visible", timeout=5_000)
        button.click(timeout=5_000)
        return True
    except Exception:
        pass

    for selector in (
        'a[title="New"]',
        'button[title="New"]',
        'a:has-text("New")',
        'button:has-text("New")',
        '[data-label="New"]',
    ):
        try:
            loc = page.locator(selector).first
            loc.wait_for(state="visible", timeout=4_000)
            loc.click(timeout=5_000)
            return True
        except Exception:
            pass

    try:
        page.evaluate(
            """
            () => {
                const buttons = Array.from(document.querySelectorAll('a, button'));
                const button = buttons.find(b => b.textContent.trim() === 'New');
                if (button) button.click();
            }
            """
        )
        page.wait_for_timeout(1_000)
        return True
    except Exception:
        return False


def fill_contract_form(page, data: dict) -> None:
    validate_contract_data(data)
    dump_html(page, "03_new_contract_form")
    ensure_new_contract_form_ready(page)
    run_fill_step(page, "Contract Type", data.get("contract_type", ""), lambda: fill_or_select(page, "Contract Type", data.get("contract_type", "")))
    page.wait_for_timeout(1_000)
    run_fill_step(page, "Sold to Party", data.get("sold_to_party", ""), lambda: fill_lookup(page, "Sold to Party", data.get("sold_to_party", "")))
    page.wait_for_timeout(1_500)
    clear_lookup(page, "Ship to Party")
    run_fill_step(page, "Ship to Party", data.get("ship_to_party", ""), lambda: fill_lookup(page, "Ship to Party", data.get("ship_to_party", "")))
    page.wait_for_timeout(1_500)
    clear_lookup(page, "Payer")
    run_fill_step(page, "Payer", data.get("payer", ""), lambda: fill_lookup(page, "Payer", data.get("payer", "")))
    page.wait_for_timeout(1_000)
    run_fill_step(page, "Division", data.get("division", ""), lambda: fill_lookup(page, "Division", data.get("division", "")))
    page.wait_for_timeout(1_000)
    run_fill_step(page, "Distribution Channel", data.get("distribution_channel", ""), lambda: fill_or_select(page, "Distribution Channel", data.get("distribution_channel", "")))
    page.wait_for_timeout(1_000)
    contract_source = (data.get("contract_source") or "Standard").strip()
    if contract_source.lower() == "standard":
        # Salesforce defaults Contract Source to Standard. Re-opening this picklist in
        # headless Cloud Run has repeatedly blocked the wizard from advancing.
        log_step("skipping Contract Source because Salesforce defaults it to Standard")
    else:
        run_fill_step(page, "Contract Source", contract_source, lambda: fill_or_select(page, "Contract Source", contract_source))
    page.wait_for_timeout(1_000)

    screenshot(page, "04_first_page_filled")
    log_step("clicking Next on New Contract first page")
    ensure_second_step(page)
    page.wait_for_timeout(2_000)

    dump_html(page, "04_after_first_next")
    screenshot(page, "04_after_first_next")
    run_fill_step(page, "Purchase Order No.", data.get("po_number", ""), lambda: fill_input(page, "Purchase Order No.", data.get("po_number", "")))
    page.wait_for_timeout(500)
    run_fill_step(page, "Purchase Order Date", data.get("po_date", ""), lambda: fill_date(page, "Purchase Order Date", data.get("po_date", "")))
    page.wait_for_timeout(500)
    run_fill_step(page, "Contract End Date", data.get("contract_end_date", ""), lambda: fill_date(page, "Contract End Date", data.get("contract_end_date", "")))
    page.wait_for_timeout(500)
    print(
        "[contract-create] page2 values "
        + json.dumps(collect_form_diagnostics(page, data), ensure_ascii=True),
        flush=True,
    )
    screenshot(page, "04_form_filled")


def today_date() -> str:
    return datetime.now().strftime("%d/%m/%Y")


def validate_contract_data(data: dict) -> None:
    required = {
        "contract_type": "Contract Type",
        "sold_to_party": "Sold To Party",
        "ship_to_party": "Ship To Party",
        "payer": "Payer",
        "division": "Division",
        "distribution_channel": "Distribution Channel",
        "contract_source": "Contract Source",
        "po_number": "PO Number",
        "po_date": "PO Date",
        "contract_end_date": "Contract End Date",
    }
    missing = [label for key, label in required.items() if is_blank_required_value(data.get(key))]
    if missing:
        raise RuntimeError("Missing required contract field(s): " + ", ".join(missing))


def is_blank_required_value(value) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text in {"", "-", "•", "null", "None"}


def log_step(message: str) -> None:
    print(f"[contract-create] {message}", flush=True)


def run_fill_step(page, label: str, value: str, action) -> None:
    expected = format_portal_date(value) if "Date" in label else value
    log_step(f"filling {label} with {expected or '-'}")
    action()
    observed = read_value_by_nearby_text_js(page, label_variants(label))
    if (
        expected
        and not observed
        and label not in COMBOBOX_SELECTORS
        and fill_by_nearby_text_js(page, label_variants(label), expected)
    ):
        observed = read_value_by_nearby_text_js(page, label_variants(label))
    log_step(f"filled {label}; observed={observed or '<blank>'}")


def ensure_new_contract_form_ready(page) -> None:
    for _ in range(3):
        try:
            body_text = page.inner_text("body", timeout=4_000)
            if "New Contract" in body_text and "Contract Type" in body_text and "Sold To Party" in body_text:
                return
        except Exception:
            pass
        page.wait_for_timeout(2_000)

    diagnostics = collect_form_diagnostics(page, {})
    raise RuntimeError(
        "New Contract form was not ready before filling. Diagnostics: "
        + compact_json(diagnostics, max_len=1800)
    )


def fill_or_select(page, label: str, value: str) -> None:
    if not value:
        return

    label_patterns = label_variants(label)

    if select_by_visible_label(page, label, value):
        return

    if select_named_combobox(page, label, value):
        return

    for selector in [f'select[aria-label="{item}"]' for item in label_patterns] + [
        f'select[aria-label*="{item}"]' for item in label_patterns
    ]:
        try:
            loc = page.locator(selector).first
            if loc.is_visible(timeout=1_000):
                loc.select_option(label=value)
                return
        except Exception:
            pass

    try:
        for item in label_patterns:
            label_el = page.locator(f'label:has-text("{item}")').first
            for_id = label_el.get_attribute("for", timeout=1_500)
            if for_id:
                select_el = page.locator(f"select#{for_id}")
                if select_el.count() > 0 and select_el.first.is_visible(timeout=800):
                    select_el.first.select_option(label=value)
                    return
    except Exception:
        pass

    for selector in build_button_selectors(label_patterns):
        try:
            button = page.locator(selector).first
            if button.is_visible(timeout=1_000):
                button.scroll_into_view_if_needed()
                button.click(timeout=3_000)
                page.wait_for_timeout(800)
                if click_option(page, value):
                    return
                page.keyboard.press("Escape")
        except Exception:
            pass

    try:
        for item in label_patterns:
            label_el = page.locator(f'label:has-text("{item}")').first
            if label_el.is_visible(timeout=1_000):
                label_el.scroll_into_view_if_needed()
                label_el.locator(
                    "xpath=../following-sibling::*//button | "
                    "xpath=../following-sibling::*//*[@role='combobox'] | "
                    "xpath=../..//button | "
                    "xpath=../..//*[@role='combobox']"
                ).first.click(timeout=3_000)
                page.wait_for_timeout(800)
                if click_option(page, value):
                    return
                page.keyboard.press("Escape")
    except Exception:
        pass

    if click_combobox_near_label_js(page, label_patterns, value):
        return

    if label in COMBOBOX_SELECTORS:
        # Before raising, check if the value is already displayed in the button (pre-selected default).
        try:
            for selector in build_button_selectors(label_patterns):
                btn = page.locator(selector).first
                if btn.count() > 0:
                    btn_text = btn.inner_text(timeout=1_000)
                    if value.strip().lower() in btn_text.strip().lower():
                        return
        except Exception:
            pass
        # Also check page body text — some fields show selected value as plain text not in button
        try:
            body_text = page.inner_text("body", timeout=2_000)
            for pattern in label_patterns:
                idx = body_text.lower().find(pattern.lower())
                if idx != -1 and value.strip().lower() in body_text[idx:idx + 120].lower():
                    return
        except Exception:
            pass
        diagnostics = collect_form_diagnostics(page, {})
        raise RuntimeError(
            f"Could not select {label} option {value}. Diagnostics: "
            + compact_json(diagnostics, max_len=1400)
        )

    fill_input(page, label, value)


def fill_input(page, label: str, value: str) -> None:
    if not value:
        return
    label_patterns = label_variants(label)
    if fill_input_by_role(page, label, value):
        return
    if fill_by_visible_label(page, label, value):
        return
    for selector in build_input_selectors(label_patterns):
        try:
            loc = page.locator(selector).first
            if loc.is_visible(timeout=800):
                loc.scroll_into_view_if_needed()
                loc.click(timeout=2_000)
                loc.click(click_count=3)
                page.keyboard.press("Delete")
                loc.fill(value)
                return
        except Exception:
            pass

    try:
        for item in label_patterns:
            label_el = page.locator(f'label:has-text("{item}")').first
            for_id = label_el.get_attribute("for", timeout=1_000)
            if for_id:
                page.locator(f"input#{for_id}").fill(value)
                return
    except Exception:
        pass

    if fill_by_nearby_text_js(page, label_patterns, value):
        log.info("Filled %s by nearby text JS fallback", label)
        return

    log.warning("Could not fill input %s", label)


def fill_date(page, label: str, value: str) -> None:
    if not value:
        return
    if fill_portal_date_direct(page, label, value):
        return
    if fill_date_by_picker(page, label, value):
        return
    for selector in build_input_selectors(label_variants(label)):
        try:
            loc = page.locator(selector).first
            if loc.is_visible(timeout=800):
                loc.scroll_into_view_if_needed()
                loc.click(timeout=3_000)
                loc.click(click_count=3)
                page.keyboard.press("Delete")
                loc.press_sequentially(value, delay=80)
                page.keyboard.press("Tab")
                return
        except Exception:
            pass

    try:
        for item in label_variants(label):
            label_el = page.locator(f'label:has-text("{item}")').first
            for_id = label_el.get_attribute("for", timeout=1_000)
            if for_id:
                loc = page.locator(f"input#{for_id}")
                loc.click(click_count=3)
                page.keyboard.press("Delete")
                loc.press_sequentially(value, delay=80)
                page.keyboard.press("Tab")
                return
    except Exception:
        log.warning("Could not fill date %s", label)


def fill_portal_date_direct(page, label: str, value: str) -> bool:
    formatted = format_portal_date(value)
    role_names = {
        "PO Date": ["Purchase Order Date", "PO Date"],
        "Purchase Order Date": ["Purchase Order Date", "PO Date"],
        "Contract Start Date": ["Contract Start Date"],
        "Contract End Date": ["Contract End Date"],
    }
    for role_name in role_names.get(label, [label]):
        try:
            loc = page.get_by_role("textbox", name=role_name).first
            loc.wait_for(state="visible", timeout=1_200)
            loc.scroll_into_view_if_needed()
            loc.click(timeout=3_000)
            loc.click(click_count=3)
            page.keyboard.press("Delete")
            loc.fill(formatted)
            page.keyboard.press("Tab")
            log.info("Filled %s directly as %s", label, formatted)
            return True
        except Exception:
            pass

        for xpath in (
            f"//*[contains(normalize-space(), {xpath_literal(role_name)})]/following::input[1]",
            f"//*[contains(normalize-space(), {xpath_literal(role_name)})]/ancestor::*[contains(@class,'slds-grid') or contains(@class,'slds-form-element')][1]//input",
        ):
            try:
                loc = page.locator(f"xpath={xpath}").first
                loc.wait_for(state="visible", timeout=1_200)
                loc.scroll_into_view_if_needed()
                loc.click(timeout=3_000)
                loc.click(click_count=3)
                page.keyboard.press("Delete")
                loc.fill(formatted)
                page.keyboard.press("Tab")
                log.info("Filled %s directly by nearby label as %s", label, formatted)
                return True
            except Exception:
                pass

    if fill_by_nearby_text_js(page, role_names.get(label, [label]), formatted):
        log.info("Filled %s by nearby text JS fallback as %s", label, formatted)
        return True

    return False


def format_portal_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%d/%m/%Y").strftime("%d-%b-%Y")
    except Exception:
        return value


def fill_lookup(page, label: str, value: str) -> None:
    if not value:
        return
    if label == "Division" and select_division_option(page, value):
        return
    if fill_lookup_by_placeholder(page, label, value):
        return
    if fill_named_lookup(page, label, value):
        return
    for selector in build_input_selectors(label_variants(label)):
        try:
            loc = page.locator(selector).first
            if loc.is_visible(timeout=800):
                loc.scroll_into_view_if_needed()
                loc.click(timeout=2_000)
                loc.click(click_count=3)
                page.keyboard.press("Delete")
                loc.fill(value)
                page.wait_for_timeout(1_500)
                if click_lookup_option(page, value):
                    return
                loc.press("Enter")
                return
        except Exception:
            pass
    fill_input(page, label, value)


def select_division_option(page, value: str) -> bool:
    try:
        loc = page.get_by_placeholder(re.compile("Division", re.IGNORECASE)).first
        loc.wait_for(state="visible", timeout=1_500)
        loc.scroll_into_view_if_needed()
        loc.click(timeout=3_000)
        page.wait_for_timeout(800)
    except Exception:
        pass

    patterns = [
        rf"^{re.escape(value)}\s*Division",
        rf"{re.escape(value)}\s*Division",
        rf"^{re.escape(value)}$",
    ]
    for pattern in patterns:
        try:
            page.get_by_text(re.compile(pattern, re.IGNORECASE)).first.click(timeout=4_000)
            log.info("Selected Division option %s from existing list", value)
            return True
        except Exception:
            pass

    for selector in ('[role="option"]', "li.slds-listbox__item", ".slds-listbox__item"):
        try:
            page.locator(selector).filter(
                has_text=re.compile(re.escape(value), re.IGNORECASE)
            ).first.click(timeout=3_000)
            log.info("Selected Division option %s from listbox", value)
            return True
        except Exception:
            pass
    return False


def fill_input_by_role(page, label: str, value: str) -> bool:
    role_names = {
        "PO Number": ["Purchase Order No.", "PO Number"],
        "Purchase Order No.": ["Purchase Order No.", "PO Number"],
    }
    for role_name in role_names.get(label, [label]):
        try:
            loc = page.get_by_role("textbox", name=role_name).first
            loc.wait_for(state="visible", timeout=1_500)
            loc.scroll_into_view_if_needed()
            loc.click(timeout=3_000)
            loc.fill(value)
            log.info("Filled %s by role textbox %s", label, role_name)
            return True
        except Exception:
            pass
    return False


def fill_date_by_picker(page, label: str, value: str) -> bool:
    role_names = {
        "PO Date": ["Purchase Order Date", "PO Date"],
        "Purchase Order Date": ["Purchase Order Date", "PO Date"],
        "Contract Start Date": ["Contract Start Date"],
        "Contract End Date": ["Contract End Date"],
    }
    for role_name in role_names.get(label, [label]):
        try:
            loc = page.get_by_role("textbox", name=role_name).first
            loc.wait_for(state="visible", timeout=1_500)
            loc.scroll_into_view_if_needed()
            loc.click(timeout=3_000)
            select_calendar_date(page, value)
            log.info("Filled %s with calendar picker", label)
            return True
        except Exception:
            pass
    return False


def select_calendar_date(page, value: str) -> None:
    target = datetime.strptime(value, "%d/%m/%Y")
    today = datetime.now()
    month_delta = (target.year - today.year) * 12 + (target.month - today.month)
    button_name = "Next Month" if month_delta > 0 else "Previous Month"
    for _ in range(abs(month_delta)):
        page.get_by_role("button", name=button_name).click(timeout=5_000)
        page.wait_for_timeout(300)
    day = str(target.day)
    page.get_by_role("button", name=re.compile(f"^{re.escape(day)}$")).first.click(timeout=5_000)


def select_by_visible_label(page, label: str, value: str) -> bool:
    for item in label_variants(label):
        try:
            field = field_root_by_label(page, item)
            trigger = field.locator('button, [role="combobox"]').first
            trigger.wait_for(state="visible", timeout=1_500)
            trigger.scroll_into_view_if_needed()
            trigger.click(timeout=4_000)
            page.wait_for_timeout(800)
            if click_option(page, value):
                log.info("Selected %s by visible label", label)
                return True
            page.keyboard.press("Escape")
        except Exception:
            pass
    return False


def fill_by_visible_label(page, label: str, value: str) -> bool:
    for item in label_variants(label):
        try:
            field = field_root_by_label(page, item)
            control = field.locator("input, textarea").first
            control.wait_for(state="visible", timeout=1_500)
            control.scroll_into_view_if_needed()
            control.click(timeout=3_000)
            control.click(click_count=3)
            page.keyboard.press("Delete")
            control.fill(value)
            log.info("Filled %s by visible label", label)
            return True
        except Exception:
            pass
    return False


SECOND_STEP_INDICATORS = (
    "Purchase Order",
    "Pricing Date",
    "Contract Header Details",
    "Contract Receiving Date",
)

# Page-1 fields — if these are gone from body text, we've navigated past step 1
_STEP1_MARKER = "Contract Type"


def ensure_second_step(page) -> None:
    """Advance past first wizard page; retries Next if page hasn't moved (handles ZCQT slow server validation)."""
    initial_url = page.url
    click_next_if_visible(page)
    diagnostics = {}
    for attempt in range(20):
        page.wait_for_timeout(1_000)
        try:
            # URL change is the most reliable signal — works for any contract type
            if page.url != initial_url:
                return
            body_text = page.inner_text("body", timeout=2_000)
            if any(ind in body_text for ind in SECOND_STEP_INDICATORS):
                return
            # If step-1 marker disappeared, we're past page 1 even if URL didn't change
            if _STEP1_MARKER not in body_text:
                return
            # Retry Next click at 5s and 10s — ZCQT server-side validation can be slow
            if attempt in (4, 9):
                click_next_if_visible(page)
        except Exception:
            pass
    diagnostics = collect_form_diagnostics(page, {})
    screenshot(page, "04_second_step_not_reached")
    raise RuntimeError(
        "New Contract wizard did not reach step 2 after Next. "
        "Check first-page required fields. Diagnostics: "
        + compact_json(diagnostics, max_len=1600)
    )


def click_combobox_near_label_js(page, labels: list[str], value: str) -> bool:
    """Click a Salesforce combobox trigger nearest to the field label, then choose an option."""
    clicked = bool(
        page.evaluate(
            """
            (labels) => {
                const clean = (text) => (text || '').replace(/\\*/g, '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const targetLabels = labels.map(clean).filter(Boolean);
                const visible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
                };
                const labelNodes = Array.from(document.querySelectorAll('label, span, div'))
                    .filter(visible)
                    .filter(el => {
                        const text = clean(el.textContent);
                        return targetLabels.some(target => {
                            if (text === target) return true;
                            if (!['LABEL', 'SPAN'].includes(el.tagName)) return false;
                            return text.includes(target) && text.length <= target.length + 14;
                        });
                    });
                const controls = Array.from(document.querySelectorAll('button, [role="combobox"]'))
                    .filter(el => !el.disabled && visible(el));
                for (const label of labelNodes) {
                    const lr = label.getBoundingClientRect();
                    const candidates = controls
                        .map(control => {
                            const cr = control.getBoundingClientRect();
                            const rowPenalty = Math.abs((cr.top + cr.bottom) / 2 - (lr.top + lr.bottom) / 2);
                            const rightPenalty = cr.left >= lr.left - 40 ? 0 : 5000;
                            const belowPenalty = cr.top >= lr.top - 20 ? 0 : 2500;
                            const horizontalPenalty = Math.abs(cr.left - lr.left);
                            const distance = rowPenalty * 10 + horizontalPenalty + rightPenalty + belowPenalty;
                            return {control, distance};
                        })
                        .sort((a, b) => a.distance - b.distance);
                    if (candidates.length && candidates[0].distance < 4200) {
                        candidates[0].control.scrollIntoView({block: 'center', inline: 'nearest'});
                        candidates[0].control.click();
                        return true;
                    }
                }
                return false;
            }
            """,
            labels,
        )
    )
    if not clicked:
        return False
    page.wait_for_timeout(800)
    if click_option(page, value):
        log.info("Selected combobox near label %s", labels[0])
        return True
    page.keyboard.press("Escape")
    return False


def fill_by_nearby_text_js(page, labels: list[str], value: str) -> bool:
    """Fill a Salesforce input by walking from visible label text to a nearby control."""
    return bool(
        page.evaluate(
            """
            ([labels, value]) => {
                const clean = (text) => (text || '').replace(/\\*/g, '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const targetLabels = labels.map(clean).filter(Boolean);
                const visible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
                };
                const setValue = (input) => {
                    input.scrollIntoView({block: 'center', inline: 'nearest'});
                    input.focus();
                    const proto = input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                    if (setter) setter.call(input, value);
                    else input.value = value;
                    input.dispatchEvent(new Event('input', {bubbles: true}));
                    input.dispatchEvent(new Event('change', {bubbles: true}));
                    input.dispatchEvent(new Event('blur', {bubbles: true}));
                    return true;
                };
                const labelsOnPage = Array.from(document.querySelectorAll('label, span, div'))
                    .filter(visible)
                    .filter(el => {
                        const text = clean(el.textContent);
                        return targetLabels.some(target => {
                            if (text === target) return true;
                            if (!['LABEL', 'SPAN'].includes(el.tagName)) return false;
                            return text.includes(target) && text.length <= target.length + 12;
                        });
                    });
                const controls = Array.from(document.querySelectorAll('input:not([type="hidden"]), textarea'))
                    .filter(input => !input.disabled && !input.readOnly && visible(input));
                for (const label of labelsOnPage) {
                    const lr = label.getBoundingClientRect();
                    const candidates = controls
                        .map(input => {
                            const ir = input.getBoundingClientRect();
                            const rowPenalty = Math.abs((ir.top + ir.bottom) / 2 - (lr.top + lr.bottom) / 2);
                            const rightPenalty = ir.left >= lr.left - 20 ? 0 : 5000;
                            const belowPenalty = ir.top >= lr.top - 12 ? 0 : 2500;
                            const horizontalPenalty = Math.abs(ir.left - lr.left);
                            const distance = rowPenalty * 10 + horizontalPenalty + rightPenalty + belowPenalty;
                            return {input, distance};
                        })
                        .sort((a, b) => a.distance - b.distance);
                    if (candidates.length && candidates[0].distance < 3500) {
                        return setValue(candidates[0].input);
                    }
                }
                return false;
            }
            """,
            [labels, value],
        )
    )


def click_button_by_text_js(page, text: str) -> bool:
    return bool(
        page.evaluate(
            """
            (text) => {
                const target = text.trim().toLowerCase();
                const visible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width >= 0 && rect.height >= 0;
                };
                const buttons = Array.from(document.querySelectorAll('button, a, input[type="button"], input[type="submit"]'));
                const button = buttons.find((el) => {
                    const label = (el.textContent || el.value || el.getAttribute('aria-label') || '').trim().toLowerCase();
                    return label === target && !el.disabled && visible(el);
                });
                if (!button) return false;
                button.scrollIntoView({block: 'center', inline: 'nearest'});
                button.click();
                return true;
            }
            """,
            text,
        )
    )


def collect_form_diagnostics(page, expected: dict) -> dict:
    labels = {
        "contract_type": ["Contract Type"],
        "sold_to_party": ["Sold To Party", "Sold to Party"],
        "ship_to_party": ["Ship To Party", "Ship to Party"],
        "payer": ["Payer"],
        "division": ["Division"],
        "distribution_channel": ["Distribution Channel"],
        "contract_source": ["Contract Source"],
        "po_number": ["Purchase Order No.", "PO Number"],
        "po_date": ["Purchase Order Date", "PO Date"],
        "contract_start_date": ["Contract Start Date"],
        "contract_end_date": ["Contract End Date"],
    }
    observed = {}
    for key, variants in labels.items():
        observed[key] = read_value_by_nearby_text_js(page, variants)

    return {
        "url": safe_page_value(lambda: page.url),
        "title": safe_page_value(page.title),
        "expected": {
            "contract_type": expected.get("contract_type"),
            "sold_to_party": expected.get("sold_to_party"),
            "ship_to_party": expected.get("ship_to_party"),
            "payer": expected.get("payer"),
            "division": expected.get("division"),
            "distribution_channel": expected.get("distribution_channel"),
            "contract_source": expected.get("contract_source"),
            "po_number": expected.get("po_number"),
            "po_date": format_portal_date(expected.get("po_date", "")),
            "contract_start_date": None,
            "contract_end_date": format_portal_date(expected.get("contract_end_date", "")),
        },
        "observed": observed,
        "buttons": visible_button_texts(page),
        "body_hint": visible_body_hint(page),
    }


def read_value_by_nearby_text_js(page, labels: list[str]) -> str:
    try:
        return str(
            page.evaluate(
                """
                (labels) => {
                    const clean = (text) => (text || '').replace(/\\*/g, '').replace(/\\s+/g, ' ').trim().toLowerCase();
                    const targetLabels = labels.map(clean).filter(Boolean);
                    const visible = (el) => {
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
                    };
                    const valueOf = (el) => {
                        if (!el) return '';
                        if (el.matches('input, textarea, select')) return el.value || '';
                        const text = (el.textContent || '').replace(/\\s+/g, ' ').trim();
                        return text;
                    };
                    const labelsOnPage = Array.from(document.querySelectorAll('label, span, div'))
                        .filter(visible)
                        .filter(el => {
                            const text = clean(el.textContent);
                            return targetLabels.some(target => {
                                if (text === target) return true;
                                if (!['LABEL', 'SPAN'].includes(el.tagName)) return false;
                                return text.includes(target) && text.length <= target.length + 12;
                            });
                        });
                    const controls = Array.from(document.querySelectorAll('input:not([type="hidden"]), textarea, select, lightning-base-combobox-formatted-text'))
                        .filter(visible);
                    for (const label of labelsOnPage) {
                        const lr = label.getBoundingClientRect();
                        const candidates = controls
                            .map(control => {
                                const ir = control.getBoundingClientRect();
                                const rowPenalty = Math.abs((ir.top + ir.bottom) / 2 - (lr.top + lr.bottom) / 2);
                                const rightPenalty = ir.left >= lr.left - 20 ? 0 : 5000;
                                const belowPenalty = ir.top >= lr.top - 12 ? 0 : 2500;
                                const horizontalPenalty = Math.abs(ir.left - lr.left);
                                const distance = rowPenalty * 10 + horizontalPenalty + rightPenalty + belowPenalty;
                                return {control, distance};
                            })
                            .sort((a, b) => a.distance - b.distance);
                        for (const candidate of candidates.slice(0, 3)) {
                            if (candidate.distance >= 3500) continue;
                            const value = valueOf(candidate.control);
                            if (value && !targetLabels.some(target => clean(value).includes(target))) return value;
                        }
                    }
                    return '';
                }
                """,
                labels,
            )
        )
    except Exception:
        return ""


def visible_button_texts(page) -> list[str]:
    try:
        values = page.evaluate(
            """
            () => Array.from(document.querySelectorAll('button, a, input[type="button"], input[type="submit"]'))
                .filter((el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
                })
                .map((el) => (el.textContent || el.value || el.getAttribute('aria-label') || el.title || '').replace(/\\s+/g, ' ').trim())
                .filter(Boolean)
                .slice(-20)
            """
        )
        return [str(item) for item in values]
    except Exception:
        return []


def visible_body_hint(page) -> str:
    try:
        text = page.inner_text("body", timeout=2_000)
        text = re.sub(r"\s+", " ", text).strip()
        return text[-900:]
    except Exception:
        return ""


def safe_page_value(func) -> str:
    try:
        return str(func())
    except Exception:
        return ""


def compact_json(value: dict, max_len: int = 1600) -> str:
    text = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def field_root_by_label(page, label: str):
    escaped = xpath_literal(label)
    return page.locator(
        "xpath="
        f"//*[self::label or self::span or self::div][contains(normalize-space(.), {escaped})]"
        "/ancestor::*[contains(@class,'slds-form-element') or contains(@class,'slds-form-element__control')][1]"
    ).first


def fill_lookup_by_placeholder(page, label: str, value: str) -> bool:
    placeholders = {
        "Sold to Party": ["Search Sold To Party", "Sold To Party"],
        "Ship to Party": ["Search Ship To Party", "Ship To Party"],
        "Payer": ["Payer"],
        "Division": ["Search Division", "Division"],
    }
    for placeholder in placeholders.get(label, []):
        try:
            loc = page.get_by_placeholder(re.compile(re.escape(placeholder), re.IGNORECASE)).first
            loc.wait_for(state="visible", timeout=1_500)
            component = loc.locator("xpath=ancestor::c-reusable-lookup[1]")
            return fill_lookup_control(page, loc, label, value, component)
        except Exception:
            pass
    return False


def clear_lookup(page, label: str) -> None:
    data_ids = {
        "Sold to Party": "Sold To",
        "Ship to Party": "Ship To",
        "Payer": "Payer",
        "Division": "Division",
    }
    if label in data_ids:
        try:
            component = page.locator(f'c-reusable-lookup[data-id="{data_ids[label]}"]').first
            if clear_lookup_component(component):
                return
        except Exception:
            pass
    for selector in LOOKUP_SELECTORS.get(label, []):
        try:
            component = page.locator(selector).first.locator("xpath=ancestor::c-reusable-lookup[1]")
            if clear_lookup_component(component):
                return
        except Exception:
            pass
    try:
        page.get_by_role("button", name="Remove selected option").nth(1).click(timeout=1_000)
    except Exception:
        pass


def clear_lookup_component(component) -> bool:
    for selector in (
        'button[title*="Remove"]',
        'button[aria-label*="Remove"]',
        'button:has-text("×")',
        'button:has-text("x")',
        'lightning-button-icon button',
    ):
        try:
            button = component.locator(selector).first
            button.wait_for(state="visible", timeout=800)
            button.click(timeout=2_000)
            return True
        except Exception:
            pass
    return False


def select_named_combobox(page, label: str, value: str) -> bool:
    for selector in COMBOBOX_SELECTORS.get(label, []):
        try:
            button = page.locator(selector).first
            if button.is_visible(timeout=1_200):
                button.scroll_into_view_if_needed()
                button.click(timeout=4_000)
                page.wait_for_timeout(800)
                if click_option(page, value):
                    log.info("Selected %s using %s", label, selector)
                    return True
                page.keyboard.press("Escape")
        except Exception:
            pass
    return False


def fill_named_lookup(page, label: str, value: str) -> bool:
    for selector in LOOKUP_SELECTORS.get(label, []):
        try:
            loc = page.locator(selector).first
            loc.wait_for(state="visible", timeout=1_500)
            component = page.locator(selector).first.locator(
                "xpath=ancestor::c-reusable-lookup[1]"
            )
            if fill_lookup_control(page, loc, label, value, component):
                log.info("Selected lookup %s using %s", label, selector)
                return True
        except Exception:
            pass
    return False


def fill_lookup_control(page, loc, label: str, value: str, component=None) -> bool:
    loc.scroll_into_view_if_needed()
    loc.click(timeout=3_000)
    loc.click(click_count=3)
    page.keyboard.press("Delete")
    loc.fill(value)
    page.wait_for_timeout(3_000)
    if component is not None and click_first_lookup_option(component):
        log.info("Selected first narrowed lookup option for %s", label)
        return True
    if click_lookup_option(page, value):
        log.info("Selected lookup %s", label)
        return True
    loc.press("ArrowDown")
    page.wait_for_timeout(300)
    loc.press("Enter")
    return True


def click_first_lookup_option(component) -> bool:
    for selector in (
        '[role="option"]',
        "li.slds-listbox__item",
        ".slds-listbox__item",
        ".slds-listbox__option",
    ):
        try:
            option = component.locator(selector).first
            option.wait_for(state="visible", timeout=1_500)
            option.click(timeout=3_000)
            return True
        except Exception:
            pass
    return False


def click_next_if_visible(page) -> bool:
    try:
        next_button = page.get_by_role("button", name=re.compile("^Next$", re.IGNORECASE))
        if next_button.is_visible(timeout=2_000):
            next_button.click(timeout=5_000)
            return True
    except Exception:
        pass
    return False


def click_save_button(page, contract_data: dict | None = None) -> None:
    screenshot(page, "04_before_save")
    for selector_fn in (
        lambda: page.get_by_role("button", name=re.compile("^Save$", re.IGNORECASE)).first,
        lambda: page.locator('button:has-text("Save")').first,
        lambda: page.locator(".slds-modal__footer button").filter(has_text="Save").first,
    ):
        try:
            button = selector_fn()
            button.wait_for(state="visible", timeout=5_000)
            button.scroll_into_view_if_needed()
            button.click(timeout=5_000)
            page.wait_for_timeout(2_000)
            return
        except Exception:
            pass
    if click_button_by_text_js(page, "Save"):
        page.wait_for_timeout(2_000)
        return
    diagnostics = collect_form_diagnostics(page, contract_data or {})
    raise RuntimeError(
        "Save button was not found on New Contract form. Diagnostics: "
        + compact_json(diagnostics, max_len=1600)
    )


def click_option(page, value: str) -> bool:
    option_texts = option_variants(value)
    for option_text in option_texts:
        for selector in ('[role="option"]', "lightning-base-combobox-item", "li", "span"):
            try:
                page.locator(selector).filter(
                    has_text=re.compile(re.escape(option_text), re.IGNORECASE)
                ).first.click(timeout=4_000)
                return True
            except Exception:
                pass
    return False


def click_lookup_option(page, value: str) -> bool:
    option_texts = option_variants(value)
    for option_text in option_texts:
        for selector in ('[role="option"]', "li.slds-listbox__item", "lightning-base-combobox-item"):
            try:
                page.locator(selector).filter(
                    has_text=re.compile(re.escape(option_text), re.IGNORECASE)
                ).first.click(timeout=4_000)
                return True
            except Exception:
                pass
    try:
        if value.upper() == "HRC":
            page.get_by_text(re.compile(r"^HRC\s*Division", re.IGNORECASE)).click(timeout=3_000)
            return True
    except Exception:
        pass
    return False


def build_input_selectors(labels: list[str]) -> list[str]:
    selectors = []
    for label in labels:
        selectors.extend(
            [
                f'lightning-input:has(label:has-text("{label}")) input',
                f'lightning-textarea:has(label:has-text("{label}")) textarea',
                f'input[aria-label="{label}"]',
                f'input[aria-label*="{label}"]',
                f'input[placeholder="{label}"]',
                f'input[placeholder*="{label}"]',
                f'textarea[aria-label="{label}"]',
                f'textarea[aria-label*="{label}"]',
                f'textarea[placeholder="{label}"]',
                f'textarea[placeholder*="{label}"]',
            ]
        )
    return selectors


def build_button_selectors(labels: list[str]) -> list[str]:
    selectors = []
    for label in labels:
        selectors.extend(
            [
                f'button[aria-label="{label}"]',
                f'button[aria-label*="{label}"]',
                f'[aria-label="{label}"] button',
                f'[aria-label*="{label}"] button',
                f'lightning-combobox[data-label="{label}"] button',
                f'lightning-combobox:has(label:has-text("{label}")) button',
                f'div:has(label:has-text("{label}")) button',
                f'div:has(label:has-text("{label}")) [role="combobox"]',
            ]
        )
    return selectors


def label_variants(label: str) -> list[str]:
    variants = {label}
    replacements = {
        "Sold to Party": ["Sold To Party", "Search Sold To Party", "Search Sold To Party..."],
        "Ship to Party": ["Ship To Party", "Search Ship To Party", "Search Ship To Party..."],
        "Payer": ["Payer", "Payer..."],
        "Contract Type": ["Contract Type", "Select an Option"],
        "Contract Source": ["Contract Source"],
        "Distribution Channel": ["Distribution Channel"],
        "PO Number": ["PO Number", "Purchase Order No."],
        "Purchase Order No.": ["Purchase Order No.", "PO Number"],
        "PO Date": ["PO Date", "Purchase Order Date", "PO Date (DD/MM/YYYY)"],
        "Purchase Order Date": ["Purchase Order Date", "PO Date"],
        "Contract Start Date": ["Contract Start Date"],
        "Contract End Date": ["Contract End Date", "Contract End Date (DD/MM/YYYY)"],
    }
    variants.update(replacements.get(label, []))
    return list(variants)


def option_variants(value: str) -> list[str]:
    values = [value]
    if value == "ZCQT":
        values.append("ZCQT - JSW Dom Contract")
        values.append("JSW Dom Contract")
    if value == "ZCQD":
        values.append("ZCQD")
    if value == "ZCQX":
        values.append("ZCQX")
    if value == "ZCDX":
        values.append("ZCDX")
        values.append("ZCDX - JSW DepoDom EXcontra")
    if value.isdigit():
        values.extend([value.zfill(8), value.zfill(10)])
    return values


def xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    return "concat(" + ", \"'\", ".join(f"'{part}'" for part in value.split("'")) + ")"


def wait_for_save(page, timeout_ms: int = 600_000) -> None:
    try:
        page.wait_for_url(
            lambda url: (
                "/new" not in url.lower()
                and "/edit" not in url.lower()
                and "recordlist" not in url.lower()
                and ("/contract/" in url.lower() or "/detail/" in url.lower())
            ),
            timeout=timeout_ms,
        )
        page.wait_for_timeout(2_000)
    except Exception as exc:
        log.warning("wait_for_save timed out or failed: %s", exc)


def extract_contract_number(page) -> str:
    page.wait_for_timeout(2_000)
    screenshot(page, "05_after_save")

    for selector in ("h1 .slds-page-header__title", ".slds-page-header__title", "h1"):
        try:
            for element in page.locator(selector).all():
                text = element.inner_text(timeout=1_000).strip()
                if re.match(r"^\d{7,9}$", text):
                    return text
        except Exception:
            pass

    try:
        body_text = page.inner_text("body", timeout=3_000)
        for match in re.findall(r"\b(\d{7,9})\b", body_text):
            if match.startswith("0"):
                return match
    except Exception:
        pass
    return ""


def screenshot(page, name: str) -> None:
    try:
        page.screenshot(path=str(DEBUG_DIR / f"contract_create_{name}.png"))
    except Exception:
        pass


def dump_html(page, name: str) -> None:
    try:
        (DEBUG_DIR / f"contract_create_{name}.html").write_text(
            page.content(), encoding="utf-8"
        )
    except Exception:
        pass


def first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    sample_data = {
        "contract_type": "ZCQT",
        "contract_source": "Standard",
        "sold_to_party": "40039807",
        "ship_to_party": "40111475",
        "payer": "40102336",
        "division": "HRC",
        "distribution_channel": "OEM",
        "po_number": "Test PO 24 Apr 2026",
        "po_date": "24/04/2026",
        "contract_end_date": "23/07/2026",
    }
    print(create_contract_in_portal(sample_data, "O360-15342"))
