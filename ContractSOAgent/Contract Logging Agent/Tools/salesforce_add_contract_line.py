"""
Tool: salesforce_add_contract_line.py
Purpose: Log into Salesforce, search for a contract by number,
         open it, click "New Contract Line", and fill in SKU line item details.

Usage (standalone test):
    python tools/salesforce_add_contract_line.py
"""

import os
import sys
import re
import logging
import argparse
import time

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from dotenv import load_dotenv

_ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=os.path.abspath(_ENV_PATH), override=True)

log = logging.getLogger(__name__)

BASE_URL  = "https://jswsteel.my.site.com"
# Use /tmp for debug screenshots — /app is read-only in Cloud Run
DEBUG_DIR = "/tmp/sf_sku_debug"
PORTAL_WIDTH = 1920
PORTAL_HEIGHT = 1080
PORTAL_VIEWPORT = {"width": PORTAL_WIDTH, "height": PORTAL_HEIGHT}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def salesforce_add_contract_line(contract_number: str, line_data: dict) -> str:
    """Returns the saved contract line name (e.g. '00170850_20'), or '' on failure."""
    os.makedirs(DEBUG_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = _launch_browser(p)
        page = _new_page(browser)
        try:
            _login(page)
            _search_and_open_contract(page, contract_number)
            _click_new_contract_line(page)
            return _fill_contract_line(page, line_data, contract_number)
        finally:
            browser.close()
    return ""


def salesforce_add_contract_line_for_training(
    contract_number: str,
    line_data: dict,
    pause_seconds: int = 300,
) -> str:
    """Visible local create-line test that pauses before closing the browser."""
    os.makedirs(DEBUG_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = _launch_browser(p, force_headed=True)
        page = _new_page(browser)
        try:
            _login(page)
            _search_and_open_contract(page, contract_number)
            _click_new_contract_line(page)
            line_name = _fill_contract_line(page, line_data, contract_number) or ""
            print(f"Contract line result: {line_name or '[not captured]'}")
            if pause_seconds > 0:
                print(f"Browser will stay open for {pause_seconds} seconds for verification.")
                time.sleep(pause_seconds)
            return line_name
        finally:
            browser.close()


def get_contract_division(contract_number: str) -> str:
    """
    Log in, open the contract detail page, and return the Division field value (e.g. 'HRC').
    Returns '' if not found or on any error.
    """
    os.makedirs(DEBUG_DIR, exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = _launch_browser(p)
            page = _new_page(browser)
            try:
                _login(page)
                _search_and_open_contract(page, contract_number)
                page.wait_for_timeout(3_000)
                _screenshot(page, "div_contract_detail")
                division = page.evaluate("""
                    () => {
                        // Salesforce Aura: dt/dd field pairs
                        for (const dt of document.querySelectorAll('dt')) {
                            if (dt.textContent.trim() === 'Division') {
                                const dd = dt.nextElementSibling;
                                if (dd) return dd.textContent.trim();
                            }
                        }
                        // Fallback: .slds-form-element__label -> .slds-form-element__static
                        for (const label of document.querySelectorAll(
                            'span.test-id__field-label, .slds-form-element__label'
                        )) {
                            if (label.textContent.trim() === 'Division') {
                                const parent = label.closest('.slds-form-element');
                                if (parent) {
                                    const val = parent.querySelector(
                                        '.slds-form-element__static, lightning-formatted-text, .uiOutputText'
                                    );
                                    if (val) return val.textContent.trim();
                                }
                            }
                        }
                        return '';
                    }
                """)
                log.info("Division for contract %s: '%s'", contract_number, division)
                return division or ""
            finally:
                browser.close()
    except Exception as exc:
        log.warning("Could not fetch division for %s: %s", contract_number, exc)
        return ""


# ---------------------------------------------------------------------------
# Step 1 — Login
# ---------------------------------------------------------------------------

def open_contract_for_training(contract_number: str, pause_seconds: int = 300) -> None:
    """
    Local smoke/training mode.

    Logs in, opens the contract detail page, takes screenshots, and keeps the
    visible browser open. It does not click New Contract Line or save anything.
    """
    os.makedirs(DEBUG_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = _launch_browser(p, force_headed=True)
        page = _new_page(browser)
        try:
            _login(page)
            _search_and_open_contract(page, contract_number)
            page.wait_for_timeout(2_000)
            _screenshot(page, "training_contract_open", full_page=True)
            print(f"Opened contract {contract_number}. Browser will stay open for {pause_seconds} seconds.")
            print("Use this window to verify login and show the HRC New Contract Line layout.")
            if pause_seconds > 0:
                time.sleep(pause_seconds)
        finally:
            browser.close()


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int = 0) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def _launch_browser(p, force_headed: bool = False):
    headless = False if force_headed else _env_flag("PLAYWRIGHT_HEADLESS", default=True)
    return p.chromium.launch(
        headless=headless,
        slow_mo=_env_int("PLAYWRIGHT_SLOW_MO_MS", 0),
        args=[
            "--start-maximized",
            "--start-fullscreen",
            f"--window-size={PORTAL_WIDTH},{PORTAL_HEIGHT}",
            "--force-device-scale-factor=1",
            "--high-dpi-support=1",
        ],
    )


def _new_page(browser):
    page = browser.new_page(
        viewport=PORTAL_VIEWPORT,
        screen=PORTAL_VIEWPORT,
        device_scale_factor=1,
    )
    _fix_resolution(page)
    return page


def _fix_resolution(page) -> None:
    """Keep Salesforce layout stable so selectors do not move into overflow menus."""
    try:
        page.set_viewport_size(PORTAL_VIEWPORT)
    except Exception:
        pass
    try:
        cdp = page.context.new_cdp_session(page)
        window = cdp.send("Browser.getWindowForTarget")
        cdp.send(
            "Browser.setWindowBounds",
            {
                "windowId": window["windowId"],
                "bounds": {
                    "left": 0,
                    "top": 0,
                    "width": PORTAL_WIDTH,
                    "height": PORTAL_HEIGHT,
                    "windowState": "maximized",
                },
            },
        )
    except Exception:
        pass
    _stabilise_salesforce_modal(page)


def _stabilise_salesforce_modal(page) -> None:
    """Keep long Salesforce modals usable in headed/local runs."""
    try:
        page.evaluate(
            """() => {
                document.documentElement.style.zoom = '0.9';
                document.body.style.zoom = '0.9';
                const styleId = 'codex-salesforce-modal-fix';
                if (!document.getElementById(styleId)) {
                    const style = document.createElement('style');
                    style.id = styleId;
                    style.textContent = `
                        .slds-modal__container, .uiModal .modal-container {
                            max-height: calc(100vh - 12px) !important;
                            height: calc(100vh - 12px) !important;
                        }
                        .slds-modal__content, .uiModal .modal-body {
                            max-height: calc(100vh - 160px) !important;
                        }
                        .slds-modal__footer, .forceModalActionContainer {
                            position: sticky !important;
                            bottom: 0 !important;
                            z-index: 20 !important;
                            background: white !important;
                        }
                    `;
                    document.head.appendChild(style);
                }
            }"""
        )
    except Exception:
        pass


def _login(page) -> None:
    url      = os.environ["SALESFORCE_URL"]
    username = os.environ["SALESFORCE_USERNAME"]
    password = os.environ["SALESFORCE_PASSWORD"]

    log.info("Navigating to Salesforce login")
    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_selector('input[placeholder="Username"]', timeout=20_000)
    page.locator('input[placeholder="Username"]').fill(username)
    page.locator('input[type="password"]').fill(password)
    page.locator('button:has-text("Log in")').click()
    page.wait_for_url(lambda u: "/login" not in u.lower(), timeout=30_000)
    log.info("Logged in")
    _screenshot(page, "01_logged_in")


# ---------------------------------------------------------------------------
# Step 2 — Search for contract and open it
# ---------------------------------------------------------------------------

def _search_and_open_contract(page, contract_number: str) -> None:
    log.info("Searching for contract: %s", contract_number)
    search_input = page.locator('input[placeholder="Search..."]').first
    search_input.click(timeout=10_000)
    page.wait_for_timeout(500)
    search_input.fill(contract_number)
    page.wait_for_timeout(2_000)  # wait for dropdown suggestions to appear
    _screenshot(page, "02_search_dropdown")

    # The dropdown shows two rows:
    #   Row 1: search-for-text row  (magnifier icon, shows "00170783" in quotes)
    #   Row 2: contract record row  (contract icon, shows 00170783 + "Contract" label)
    # We must click Row 2. Filter by the "Contract" sub-label to avoid Row 1.
    clicked = _click_exact_contract_search_result(page, contract_number)
    for sel in [
        # Exact record row — has both the number and the "Contract" object label
        f'li:has-text("{contract_number}"):has-text("Contract")',
        f'[role="option"]:has-text("{contract_number}"):has-text("Contract")',
        # Broader fallback: any li containing "Contract" (the object type label)
        'li:has-text("Contract")',
    ]:
        if clicked:
            break
        try:
            loc = page.locator(sel).filter(has_not_text="Contract Line").first
            if loc.is_visible(timeout=2_000):
                loc.click(timeout=5_000)
                clicked = True
                log.info("  clicked suggestion using: %s", sel)
                break
        except Exception:
            pass

    if not clicked:
        log.warning("  suggestion not found — pressing Enter as fallback")
        search_input.press("Enter")

    page.wait_for_timeout(4_000)
    _screenshot(page, "03_contract_detail")
    log.info("Opened contract %s", contract_number)


def _click_exact_contract_search_result(page, contract_number: str) -> bool:
    """Click search result with object label exactly 'Contract', never 'Contract Line'."""
    try:
        clicked = page.evaluate(
            """(contractNumber) => {
                const candidates = Array.from(document.querySelectorAll('li, [role="option"]'));
                for (const el of candidates) {
                    const lines = (el.innerText || '')
                        .split(/\\n+/)
                        .map((line) => line.trim())
                        .filter(Boolean);
                    const hasNumber = lines.some((line) => line === contractNumber);
                    const hasExactContractLabel = lines.some((line) => line === 'Contract');
                    const hasContractLineLabel = lines.some((line) => line === 'Contract Line');
                    if (hasNumber && hasExactContractLabel && !hasContractLineLabel) {
                        el.click();
                        return true;
                    }
                }
                return false;
            }""",
            contract_number,
        )
        if clicked:
            log.info("  clicked exact Contract suggestion")
            return True
    except Exception as exc:
        log.warning("  exact Contract suggestion click failed: %s", exc)
    return False


# ---------------------------------------------------------------------------
# Step 3 — Click New Contract Line
# ---------------------------------------------------------------------------

def _click_new_contract_line(page) -> None:
    _fix_resolution(page)
    log.info("Clicking 'New Contract Line'")
    # Wait for contract page to render
    page.wait_for_timeout(4_000)

    btn = page.locator(
        'button:has-text("New Contract Line"), '
        'a:has-text("New Contract Line"), '
        '[title="New Contract Line"]'
    ).first
    btn.wait_for(state="visible", timeout=15_000)
    btn.scroll_into_view_if_needed(timeout=5_000)
    btn.click(timeout=10_000)
    page.wait_for_timeout(3_000)
    _fix_resolution(page)
    _screenshot(page, "04_form_opened")
    log.info("New Contract Line form opened")


# ---------------------------------------------------------------------------
# Step 4 — Fill the contract line form
# ---------------------------------------------------------------------------

def _fill_contract_line(page, data: dict, contract_number: str = "") -> str:
    _fix_resolution(page)
    log.info("--- Filling contract line form ---")

    # 1. Product Name — click input, dropdown appears automatically, select matching option
    _select_product_name(page, data.get("product_name", ""))
    page.wait_for_timeout(2_500)
    _screenshot(page, "05_product_name_selected")

    # Dependent Fields should now be visible
    page.wait_for_selector('text=Dependent Fields', timeout=10_000)
    log.info("Dependent Fields section loaded")
    _screenshot(page, "06_dependent_fields_loaded")

    # 2. Customer Order Category — native <select> or LWC combobox
    _select_lwc_combobox(page, "Customer Order Category", data.get("customer_order_category", ""))
    # Wait for Part Number input to become enabled (it's disabled until COC is selected)
    try:
        page.wait_for_function(
            "() => { const el = document.querySelector('input[placeholder=\"Select Part Number\"]'); "
            "return el && !el.disabled; }",
            timeout=6_000,
        )
    except Exception:
        page.wait_for_timeout(3_000)
    _screenshot(page, "07_cust_order_cat")

    # 3. Part Number is optional for this HRC flow. Keep the earlier behavior:
    # try it only when Salesforce allows it, but do not block line creation.
    _fill_part_number(page, data.get("sku_description", ""))
    page.wait_for_timeout(2_000)
    _screenshot(page, "08_part_number")

    # 4. Eq. Specification Group — LWC combobox
    _select_lwc_combobox(page, "Eq. Specification Group", data.get("eq_specif_grp", ""))
    page.wait_for_timeout(2_000)  # cascading fields update after this
    _screenshot(page, "09_eq_specif_grp")

    # 5. Eq. Specification — cascading LWC combobox (depends on Eq. Spec Group)
    _select_lwc_combobox(page, "Eq. Specification", data.get("eq_specifi", ""))
    page.wait_for_timeout(2_000)
    _screenshot(page, "10_eq_specifi")

    # 6. Eq. Sub Specification — cascading LWC combobox (depends on Eq. Specification)
    _select_lwc_combobox(page, "Eq. Sub Specification", data.get("eq_sub_grade", ""))
    page.wait_for_timeout(1_500)
    _screenshot(page, "11_eq_sub_grade")

    # 7. End Application — LWC combobox
    _select_lwc_combobox(page, "End Application", data.get("end_appn", ""))
    page.wait_for_timeout(1_500)
    _screenshot(page, "12_end_appn")

    # 8. Order Quantity — plain number input (in General Fields section)
    _fill_input_by_label(page, "Order Quantity", data.get("order_qty", ""))
    page.wait_for_timeout(1_000)
    _screenshot(page, "13_order_qty")

    # Extract plant info for S Plant selection later — Supply Plant / Depot is not filled
    plant_raw  = data.get("plant_code", "")
    plant_code = plant_raw.split()[0].rstrip("-") if plant_raw else ""
    if plant_raw:
        _fill_supply_plant(page, plant_code, plant_raw)
        page.wait_for_timeout(1_500)
        _screenshot(page, "13b_supply_plant")

    # 9. Customer Requested Date — date input
    _fill_date_by_label(page, "Customer Requested Date", data.get("cust_req_date", ""))
    page.wait_for_timeout(1_500)
    _screenshot(page, "14_cust_req_date")

    # 10. Width
    _fill_input_by_label(page, "Width", data.get("width", ""))
    page.wait_for_timeout(1_000)
    _screenshot(page, "15_width")

    # 11. Thickness
    _fill_input_by_label(page, "Thickness", data.get("thickness", ""))
    page.wait_for_timeout(1_000)
    _screenshot(page, "16_thickness")

    _fill_input_by_label(page, "Length", data.get("length", ""))
    page.wait_for_timeout(1_000)
    _screenshot(page, "16b_length")

    # 12. Edge Condition — LWC combobox
    _select_lwc_combobox(page, "Thickness Tolerance Type", data.get("thick_tol_type", ""))
    page.wait_for_timeout(1_000)
    _screenshot(page, "16c_thick_tol_type")

    _select_lwc_combobox(page, "Oil Required", data.get("oil_req", ""))
    page.wait_for_timeout(1_000)
    _screenshot(page, "16d_oil_required")

    _select_lwc_combobox(page, "Edge Condition", data.get("edge_con", ""))
    page.wait_for_timeout(1_500)
    _screenshot(page, "17_edge_condition")

    # 13. S Plant — required dropdown in "Plant Description" section
    if plant_raw:
        _select_s_plant(page, plant_code, plant_raw)
        page.wait_for_timeout(1_500)
        _screenshot(page, "17b_s_plant")

    _screenshot(page, "18_before_save", full_page=True)
    log.info("All fields filled — ready to save")

    return _save(page, contract_number)


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------

def _select_product_name(page, value: str) -> None:
    """Click 'Please Select product' input — dropdown appears — click matching option."""
    if not value:
        return
    log.info("Selecting Product Name: '%s'", value)
    try:
        inp = page.locator('input[placeholder="Please Select product"]').first
        inp.scroll_into_view_if_needed(timeout=5_000)
        inp.click(timeout=5_000)
        page.wait_for_timeout(1_000)
        # Dropdown appears automatically — click the matching item
        page.locator('li, [role="option"]').filter(
            has_text=re.compile(re.escape(value), re.IGNORECASE)
        ).first.click(timeout=8_000)
        log.info("  Product Name selected")
    except Exception as e:
        log.warning("  Product Name failed: %s", e)


def _select_lwc_combobox(page, label: str, value: str) -> None:
    """
    Select a value from a Salesforce LWC combobox or native select.
    Tries multiple strategies in order of reliability.
    """
    if not value:
        return
    log.info("Selecting combobox '%s' = '%s'", label, value)

    # Strategy 1a: native <select> by aria-label
    for sel in [
        f'select[aria-label="{label}"]',
        f'select[aria-label*="{label}"]',
    ]:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=800):
                loc.select_option(label=value)
                log.info("  selected via <select> aria-label")
                return
        except Exception:
            pass

    # Strategy 1b: label[for] → native <select>  (covers Customer Order Category)
    try:
        label_el = page.locator(f'label:has-text("{label}")').first
        for_id   = label_el.get_attribute("for", timeout=1_500)
        if for_id:
            sel_el = page.locator(f'select#{for_id}')
            if sel_el.count() > 0 and sel_el.first.is_visible(timeout=800):
                sel_el.first.select_option(label=value)
                log.info("  selected via label[for] -> <select>")
                return
    except Exception:
        pass

    # Strategy 2: LWC combobox button trigger
    for btn_sel in [
        f'button[aria-label="{label}"]',
        f'button[aria-label*="{label}"]',
        f'[aria-label="{label}"] button',
    ]:
        try:
            btn = page.locator(btn_sel).first
            if btn.is_visible(timeout=800):
                btn.scroll_into_view_if_needed()
                btn.click(timeout=3_000)
                page.wait_for_timeout(800)
                _click_dropdown_option(page, value)
                log.info("  selected via LWC button: %s", btn_sel)
                return
        except Exception:
            pass

    # Strategy 3: label → sibling select (DOM traversal)
    try:
        label_el = page.locator(f'label:has-text("{label}")').first
        sel = label_el.locator('xpath=following-sibling::*/descendant::select | following::select[1]')
        if sel.is_visible(timeout=800):
            sel.select_option(label=value)
            log.info("  selected via label sibling <select>")
            return
    except Exception:
        pass

    log.warning("  could not select combobox '%s' = '%s'", label, value)


def _click_dropdown_option(page, value: str, timeout: int = 6_000) -> None:
    """Click a dropdown option — tries multiple role/element patterns."""
    patterns = [
        f'[role="option"][data-value="{value}"]',
        f'[role="option"][data-mainfield="{value}"]',
        '[role="option"]',
        'span[role="option"]',
        'lightning-base-combobox-item',
        '.slds-listbox__item',
    ]
    for i, sel in enumerate(patterns[:2]):
        try:
            page.locator(sel).first.click(timeout=2_000)
            return
        except Exception:
            pass

    # Text-filtered match
    for sel in ['[role="option"]', 'span[role="option"]', 'lightning-base-combobox-item', '.slds-listbox__item']:
        try:
            page.locator(sel).filter(
                has_text=re.compile(r'^\s*' + re.escape(value) + r'\s*$', re.IGNORECASE)
            ).first.click(timeout=timeout)
            return
        except Exception:
            pass

    # Loose text match
    try:
        page.locator('[role="option"]').filter(
            has_text=re.compile(re.escape(value), re.IGNORECASE)
        ).first.click(timeout=timeout)
    except Exception as e:
        log.warning("  could not click dropdown option '%s': %s", value, e)


def _fill_part_number(page, value: str) -> bool:
    """Fill the Part Number lookup by clicking the magnifying glass button next to the disabled input."""
    if not value:
        return False
    log.info("Filling Part Number: '%s'", value)
    try:
        # Scroll the disabled input into view first
        inp = page.locator(
            'input[placeholder="Select Part Number"], '
            'input[placeholder*="Part Number"], '
            'input[aria-label*="Part Number"]'
        ).first
        inp.scroll_into_view_if_needed(timeout=5_000)
        page.wait_for_timeout(500)

        # Click the search button (magnifying glass) — traverse up DOM to find it.
        clicked = _click_lookup_button_near_input(page, "Part Number")
        if not clicked:
            try:
                inp.click(timeout=3_000)
                clicked = True
            except Exception:
                pass
        if not clicked:
            log.warning("  Part Number search button not found")
            return False
        page.wait_for_timeout(1_500)
        log.info("  Part Number search button clicked")

        # Type the value into the search input that appears
        search_input = page.locator('input[placeholder*="Search"]').last
        search_input.fill(value)
        page.wait_for_timeout(1_500)

        # Click matching result in dropdown
        page.locator('li, [role="option"]').filter(
            has_text=re.compile(re.escape(value), re.IGNORECASE)
        ).first.click(timeout=8_000)
        log.info("  Part Number selected")
        return True
    except Exception as e:
        log.warning("  Part Number failed: %s", e)
        return False


def _click_lookup_button_near_input(page, label: str) -> bool:
    return bool(page.evaluate(
        """(labelText) => {
            const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
            const isVisible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
            };
            const inputs = Array.from(document.querySelectorAll('input')).filter((input) => {
                const text = [
                    input.placeholder,
                    input.getAttribute('aria-label'),
                    input.name,
                    input.id,
                ].map(norm).join(' ');
                return /part number/i.test(text) || /select part number/i.test(text);
            });
            const labels = Array.from(document.querySelectorAll('label, span, div'))
                .filter((el) => norm(el.textContent) === labelText);
            for (const label of labels) {
                const forId = label.getAttribute('for');
                if (forId) {
                    const byFor = document.getElementById(forId);
                    if (byFor && !inputs.includes(byFor)) inputs.unshift(byFor);
                }
            }
            for (const input of inputs) {
                const roots = [];
                let el = input;
                for (let i = 0; i < 8 && el; i++, el = el.parentElement) roots.push(el);
                for (const root of roots) {
                    const buttons = Array.from(root.querySelectorAll(
                        'button, [role="button"], lightning-button-icon, lightning-icon, .slds-button_icon'
                    )).filter(isVisible);
                    const preferred = buttons.find((btn) => {
                        const text = norm(btn.title || btn.getAttribute('aria-label') || btn.textContent);
                        return /search|lookup|part/i.test(text);
                    });
                    const target = preferred || buttons[buttons.length - 1];
                    if (target) {
                        const clickable = target.shadowRoot && target.shadowRoot.querySelector('button')
                            ? target.shadowRoot.querySelector('button')
                            : target;
                        clickable.click();
                        return true;
                    }
                }
            }
            return false;
        }""",
        label,
    ))


def _fill_supply_plant(page, value: str, plant_raw: str = "") -> None:
    """Fill the 'Supply Plant / Depot' lookup (placeholder: Search JSW Locations...)."""
    if not value:
        return
    log.info("Filling Supply Plant / Depot: '%s'", plant_raw or value)
    try:
        inp = _input_by_label(page, "Supply Plant / Depot")
        if inp is None:
            inp = page.locator(
                'input[placeholder*="JSW Locations"], '
                'input[placeholder*="Supply Plant"], '
                'input[placeholder*="Depot"]'
            ).first
        inp.scroll_into_view_if_needed(timeout=5_000)
        inp.click(timeout=5_000)
        page.wait_for_timeout(500)
        inp.fill(value)
        page.wait_for_timeout(1_200)

        selected = _click_lookup_suggestion(page, value, plant_raw)
        if selected and not _supply_plant_lookup_modal_open(page):
            log.info("  Supply Plant selected from lookup suggestion")
            return
        if selected:
            log.info("  Supply Plant lookup opened full results; selecting exact row")

        for text in [
            f'Show more results for "{value}"',
            f"Show more results for '{value}'",
            "Show more results",
        ]:
            try:
                page.locator(f'text={text}').first.click(timeout=3_000)
                page.wait_for_timeout(2_000)
                break
            except Exception:
                pass

        if _select_supply_plant_result(page, value, plant_raw):
            log.info("  Supply Plant selected by code '%s'", value)
            return

        # Fallback: click the first result link in the table
        try:
            plant_keyword = _plant_keyword(plant_raw or value)
            if plant_keyword:
                page.locator('table a, .lookup__list a, li, [role="option"]').filter(
                    has_text=re.compile(re.escape(plant_keyword), re.IGNORECASE)
                ).first.click(timeout=4_000)
            else:
                page.locator('table a, .lookup__list a').first.click(timeout=4_000)
            log.info("  Supply Plant selected (first table result)")
        except Exception as e2:
            log.warning("  Supply Plant fallback failed: %s", e2)
    except Exception as e:
        log.warning("  Supply Plant failed: %s", e)


def _supply_plant_lookup_modal_open(page) -> bool:
    try:
        return page.locator('text=JSW Locations').first.is_visible(timeout=700)
    except Exception:
        return False


def _select_supply_plant_result(page, value: str, plant_raw: str = "") -> bool:
    """Select the exact Supply Plant result from the JSW Locations full lookup modal."""
    plant_keyword = _plant_keyword(plant_raw or value)
    if plant_keyword:
        try:
            page.locator("a").filter(
                has_text=re.compile(re.escape(plant_keyword), re.IGNORECASE)
            ).first.click(timeout=4_000, force=True)
            page.wait_for_timeout(1_000)
            if not _supply_plant_lookup_modal_open(page):
                return True
        except Exception:
            pass
    try:
        selected = page.evaluate(
            """({ code, keyword }) => {
                const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                const visible = (el) => {
                    const box = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return box.width > 0 && box.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                };
                const rows = Array.from(document.querySelectorAll('tr, .slds-grid, .slds-listbox__item, div'));
                for (const row of rows) {
                    if (!visible(row)) continue;
                    const text = norm(row.innerText || row.textContent);
                    const hasCode = code && new RegExp(`(^|\\\\s)${code}(\\\\s|$)`).test(text);
                    const hasKeyword = keyword && text.toLowerCase().includes(keyword.toLowerCase());
                    if (hasCode || hasKeyword) {
                        const link = Array.from(row.querySelectorAll('a')).find(visible);
                        const target = link || row;
                        target.click();
                        return true;
                    }
                }
                return false;
            }""",
            {"code": str(value or "").strip(), "keyword": plant_keyword},
        )
        if selected:
            page.wait_for_timeout(1_000)
            return not _supply_plant_lookup_modal_open(page)
    except Exception:
        pass
    return False


def _input_by_label(page, label: str):
    try:
        handle = page.evaluate_handle(
            """(labelText) => {
                const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                const labels = Array.from(document.querySelectorAll('label, span, div'))
                    .filter((el) => norm(el.textContent) === labelText);
                for (const label of labels) {
                    const root = label.closest('div, lightning-layout-item, c-reusable-lookup') || label.parentElement;
                    const input = root && root.querySelector('input');
                    if (input) return input;
                    const parent = root && root.parentElement;
                    const nearby = parent && parent.querySelector('input');
                    if (nearby) return nearby;
                }
                return null;
            }""",
            label,
        )
        element = handle.as_element()
        if element:
            return element
    except Exception:
        pass
    return None


def _click_lookup_suggestion(page, value: str, plant_raw: str = "") -> bool:
    plant_keyword = _plant_keyword(plant_raw or value)
    patterns = [plant_keyword] if plant_keyword else []
    for pattern in patterns:
        try:
            page.locator('li, [role="option"], lightning-base-combobox-item').filter(
                has_text=re.compile(re.escape(pattern), re.IGNORECASE)
            ).first.click(timeout=2_000)
            return True
        except Exception:
            pass
    return False


def _plant_keyword(plant_raw: str) -> str:
    parts = re.split(r'\s*-\s*', str(plant_raw or ""), maxsplit=1)
    plant_name = parts[1].strip() if len(parts) > 1 else str(plant_raw or "").strip()
    return plant_name.split()[0] if plant_name else ""


def _select_s_plant(page, plant_code: str, plant_raw: str = "") -> None:
    """Select the S Plant dropdown in the Plant Description section.
    plant_raw is the full string e.g. '1001 - Vijayanagar Works'.
    Matches the dropdown option by the plant name keyword (e.g. 'Vijayanagar').
    """
    if not plant_raw:
        return
    log.info("Selecting S Plant for: '%s'", plant_raw)

    # Extract the significant plant name word(s) after the dash
    # e.g. "1001 - Vijayanagar Works" → "Vijayanagar"
    parts = re.split(r'\s*-\s*', plant_raw, maxsplit=1)
    plant_name = parts[1].strip() if len(parts) > 1 else plant_raw.strip()
    # Use first meaningful word as keyword (e.g. "Vijayanagar" from "Vijayanagar Works")
    keyword = plant_name.split()[0] if plant_name else ""
    log.info("  S Plant keyword: '%s'", keyword)

    # Scroll to Plant Description section
    try:
        page.locator('text=Plant Description').first.scroll_into_view_if_needed(timeout=3_000)
        page.wait_for_timeout(500)
    except Exception:
        pass

    # Open the S Plant dropdown, then click the option containing the keyword
    for btn_sel in ['button[aria-label="S Plant"]', 'button[aria-label*="S Plant"]']:
        try:
            btn = page.locator(btn_sel).first
            if btn.is_visible(timeout=1_500):
                btn.scroll_into_view_if_needed()
                btn.click(timeout=3_000)
                page.wait_for_timeout(800)
                # Click the option whose text contains the plant keyword
                for sel in ['[role="option"]', 'lightning-base-combobox-item', '.slds-listbox__item']:
                    try:
                        page.locator(sel).filter(
                            has_text=re.compile(re.escape(keyword), re.IGNORECASE)
                        ).first.click(timeout=5_000)
                        log.info("  S Plant selected: keyword='%s'", keyword)
                        return
                    except Exception:
                        pass
        except Exception:
            pass

    # Fallback: native <select> — try matching by keyword in option text
    for sel in ['select[aria-label="S Plant"]', 'select[aria-label*="S Plant"]']:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=800):
                options = loc.locator('option').all_inner_texts()
                match = next((o for o in options if keyword.lower() in o.lower()), None)
                if match:
                    loc.select_option(label=match)
                    log.info("  S Plant selected via <select>: '%s'", match)
                    return
        except Exception:
            pass

    log.warning("  could not select S Plant for keyword '%s'", keyword)


def _fill_input_by_label(page, label: str, value: str) -> None:
    """Fill a plain text/number input strictly by its label."""
    if not value:
        return
    log.info("Filling input '%s' = '%s'", label, value)

    # Try aria-label first (most reliable)
    for sel in [
        f'input[aria-label="{label}"]',
        f'input[aria-label*="{label}"]',
    ]:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=1_500):
                loc.scroll_into_view_if_needed()
                loc.fill(value)
                log.info("  filled via aria-label: %s", sel)
                return
        except Exception:
            pass

    # Label → directly associated input (for= id matching)
    try:
        label_el = page.locator(f'label:has-text("{label}")').first
        for_id   = label_el.get_attribute("for", timeout=2_000)
        if for_id:
            page.locator(f'input#{for_id}').fill(value)
            log.info("  filled via label[for]")
            return
    except Exception:
        pass

    # Label → immediate sibling input container
    try:
        inp = page.locator(f'label:has-text("{label}")').first.locator(
            'xpath=following-sibling::div[1]//input | following-sibling::*[1]//input'
        )
        if inp.count() > 0:
            inp.first.scroll_into_view_if_needed()
            inp.first.fill(value)
            log.info("  filled via label sibling div//input")
            return
    except Exception:
        pass

    log.warning("  could not fill input '%s'", label)


def _fill_date_by_label(page, label: str, value: str) -> None:
    """Fill a date input. Value in DD/MM/YYYY."""
    if not value:
        return
    log.info("Filling date '%s' = '%s'", label, value)

    def _type_into(inp):
        inp.scroll_into_view_if_needed(timeout=3_000)
        inp.click(timeout=3_000)
        page.wait_for_timeout(400)
        # Select all and clear — do NOT press Escape (it closes the modal)
        inp.click(click_count=3)  # triple-click to select all existing text
        page.keyboard.press("Delete")
        inp.press_sequentially(value, delay=80)
        page.wait_for_timeout(400)
        page.keyboard.press("Tab")  # Tab moves focus without closing the modal

    for sel in [f'input[aria-label="{label}"]', f'input[aria-label*="{label}"]']:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=1_500):
                _type_into(loc)
                log.info("  date filled via aria-label")
                return
        except Exception:
            pass

    try:
        label_el = page.locator(f'label:has-text("{label}")').first
        for_id   = label_el.get_attribute("for", timeout=2_000)
        if for_id:
            _type_into(page.locator(f'input#{for_id}'))
            log.info("  date filled via label[for]")
            return
    except Exception:
        pass

    try:
        inp = page.locator(f'label:has-text("{label}")').first.locator(
            'xpath=following-sibling::div[1]//input | following-sibling::*[1]//input'
        )
        if inp.count() > 0:
            _type_into(inp.first)
            log.info("  date filled via label sibling")
    except Exception as e:
        log.warning("  could not fill date '%s': %s", label, e)


def _save(page, contract_number: str = "") -> str:
    """Click Save, wait for the detail page, then return the contract line name (e.g. '00170850_20')."""
    _fix_resolution(page)
    log.info("Clicking Save")
    try:
        # Wait for any animations/re-renders to settle before locating Save
        page.wait_for_timeout(1_500)
        save_btn = page.locator('button:has-text("Save")').first
        save_btn.wait_for(state="visible", timeout=10_000)
        save_btn.scroll_into_view_if_needed(timeout=5_000)
        page.wait_for_timeout(800)
        # Use force=True to bypass stability checks that trip on LWC animations
        save_btn.click(timeout=15_000, force=True)
        page.wait_for_timeout(10_000)
        _screenshot(page, "19_after_save")
        save_error = _extract_save_error(page)
        if save_error:
            log.warning("Save was rejected by Salesforce: %s", save_error)
            raise RuntimeError(save_error)
        log.info("Saved. URL: %s", page.url)
    except Exception as e:
        log.warning("Save failed: %s", e)
        raise

    # Read the contract line name from the detail page heading (e.g. "00170850_20")
    line_name = ""
    all_heading_names = []
    for sel in [
        'h1 .slds-page-header__title',
        'h1[class*="title"]',
        '.slds-page-header__title',
        'h1',
        '[data-aura-class*="title"]',
    ]:
        try:
            for el in page.locator(sel).all():
                text = el.inner_text(timeout=1_000).strip()
                if re.match(r'\d{7,9}_\d+', text):
                    all_heading_names.append(text)
        except Exception:
            pass
    if all_heading_names:
        line_name = max(all_heading_names, key=lambda x: int(x.split('_')[1]))

    # Fallback: scan entire page text — pick the highest numbered line (newest)
    if not line_name:
        try:
            body_text = page.inner_text("body", timeout=3_000)
            matches = re.findall(r'\b(\d{7,9}_\d+)\b', body_text)
            if matches:
                line_name = max(matches, key=lambda x: int(x.split('_')[1]))
        except Exception:
            pass

    if not line_name and contract_number:
        line_name = _find_latest_contract_line_via_search(page, contract_number)

    if not line_name and contract_number:
        line_name = _find_latest_contract_line_via_related_tab(page, contract_number)

    if line_name:
        log.info("Contract line name: %s", line_name)
    else:
        diagnostic = _after_save_diagnostics(page)
        log.warning("Could not read contract line name from page. Diagnostics: %s", diagnostic)
        raise RuntimeError(f"Contract line name was not captured after Save. {diagnostic}")
    return line_name


def _find_latest_contract_line_via_search(page, contract_number: str) -> str:
    """If Salesforce redirects to contract detail after create, use global search suggestions to find the newest line."""
    try:
        log.info("Trying global search fallback for latest Contract Line under %s", contract_number)
        search_input = page.locator('input[placeholder="Search..."]').first
        search_input.scroll_into_view_if_needed(timeout=3_000)
        search_input.click(timeout=5_000)
        page.keyboard.press("Control+A")
        search_input.fill(contract_number)
        page.wait_for_timeout(2_500)
        _screenshot(page, "20_line_search_fallback")
        text = page.inner_text("body", timeout=3_000)
        candidates = []
        for line_name in re.findall(rf'\b({re.escape(contract_number)}_\d+)\b', text):
            if re.search(rf'{re.escape(line_name)}[\s\S]{{0,120}}Contract Line', text, re.IGNORECASE):
                candidates.append(line_name)
        if not candidates:
            candidates = re.findall(rf'\b({re.escape(contract_number)}_\d+)\b', text)
        if candidates:
            latest = max(set(candidates), key=lambda x: int(x.split("_")[1]))
            log.info("Latest Contract Line from search fallback: %s", latest)
            return latest
    except Exception as exc:
        log.warning("Contract line search fallback failed: %s", exc)
    return ""


def _find_latest_contract_line_via_related_tab(page, contract_number: str) -> str:
    """If Salesforce returns to the parent contract, read the latest line from Related."""
    try:
        log.info("Trying Related tab fallback for latest Contract Line under %s", contract_number)
        page.locator("a, button, span").filter(
            has_text=re.compile(r"^Related$", re.IGNORECASE)
        ).first.click(timeout=10_000, force=True)
        page.wait_for_timeout(5_000)
        _screenshot(page, "21_related_tab_fallback", full_page=True)
        body_text = page.inner_text("body", timeout=5_000)
        candidates = re.findall(rf"\b({re.escape(contract_number)}_\d+)\b", body_text)
        if candidates:
            latest = max(set(candidates), key=lambda x: int(x.split("_")[1]))
            log.info("Latest Contract Line from Related tab fallback: %s", latest)
            return latest
    except Exception as exc:
        log.warning("Contract line Related tab fallback failed: %s", exc)
    return ""


def _extract_save_error(page) -> str:
    """Return Salesforce validation/toast errors after clicking Save, if visible."""
    messages = []
    try:
        for sel in [
            '[role="alert"]',
            '.slds-notify_toast',
            '.slds-form-element__help',
            '.slds-has-error',
            'lightning-formatted-rich-text',
        ]:
            try:
                for text in page.locator(sel).all_inner_texts(timeout=1_000):
                    text = " ".join(str(text or "").split())
                    if text and text not in messages:
                        messages.append(text)
            except Exception:
                pass
        body_text = page.inner_text("body", timeout=2_000)
        for pattern in (
            r"Error!\s*([^\\n]+)",
            r"Review the errors on this page\.?",
            r"Complete this field\.?",
            r"cannot be greater than Contract's End Date",
        ):
            match = re.search(pattern, body_text, re.IGNORECASE)
            if match:
                text = " ".join(match.group(0).split())
                if text not in messages:
                    messages.append(text)
    except Exception:
        pass
    return " | ".join(messages[:8])[:700]


def _after_save_diagnostics(page) -> str:
    try:
        body_text = " ".join(page.inner_text("body", timeout=2_000).split())
    except Exception:
        body_text = ""
    if "New Contract Line" in body_text and "Save" in body_text:
        missing = _missing_required_fields(page)
        if missing:
            return f"Salesforce stayed on New Contract Line form. Missing/invalid fields: {', '.join(missing)}"
        return "Salesforce stayed on New Contract Line form after Save; no validation text was exposed."
    return f"URL after Save: {page.url}. Page text: {body_text[:350]}"


def _missing_required_fields(page) -> list[str]:
    try:
        return page.evaluate(
            """() => {
                const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                const fields = [];
                for (const label of document.querySelectorAll('label')) {
                    const text = norm(label.textContent).replace(/^\\*/, '').trim();
                    if (!text) continue;
                    const required = label.textContent.includes('*') || label.querySelector('.required, abbr');
                    if (!required) continue;
                    const root = label.closest('.slds-form-element, lightning-layout-item, div') || label.parentElement;
                    const input = root && root.querySelector('input, textarea, select');
                    const button = root && root.querySelector('button[aria-label], button[title]');
                    const value = input ? norm(input.value || input.getAttribute('value')) : norm(button && button.textContent);
                    if (!value || /^--None--$/i.test(value) || /^Select /i.test(value)) fields.push(text);
                }
                return Array.from(new Set(fields)).slice(0, 12);
            }"""
        )
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _screenshot(page, name: str, full_page: bool = False) -> None:
    path = os.path.join(DEBUG_DIR, f"sf_sku_{name}.png")
    try:
        page.screenshot(path=path, full_page=full_page)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Local Salesforce contract-line helper")
    parser.add_argument("--contract", default="00175457", help="Contract number to open")
    parser.add_argument(
        "--mode",
        choices=["open-contract", "division", "create-line"],
        default="open-contract",
        help="Use open-contract for safe local login/layout training",
    )
    parser.add_argument(
        "--pause-seconds",
        type=int,
        default=300,
        help="How long to keep the visible browser open in open-contract mode",
    )
    parser.add_argument(
        "--sample",
        choices=["hrc", "crca-coil", "crca-sheet"],
        default="hrc",
        help="Sample line data to use in create-line mode",
    )
    args = parser.parse_args()

    samples = {
        "hrc": {
        "sku_description":         "10X2000X6100.-P1-2062_2011-E350BR",
        "product_name":            "HR Sheet & Plate - (S_HRCTLF)",
        "customer_order_category": "STD",
        "eq_specif_grp":           "BIS",
        "eq_specifi":              "2062_2011",
        "eq_sub_grade":            "E350BR",
        "end_appn":                "STRL_HT",
        "order_qty":               "15",
        "plant_code":              "1001 - Vijayanagar Works",
        "cust_req_date":           "06/08/2026",
        "width":                   "2000.000",
        "thickness":               "10.000",
        "length":                  "6100.000",
        "edge_con":                "ME",
        "thick_tol_type":          "",
        "oil_req":                 "",
        },
        "crca-coil": {
            "division":                "CRCA",
            "sku_description":         "0.35X1250-P1-CR2_SKIN_P-O2",
            "product_name":            "CRCA Coil - (S_CRCACF)",
            "customer_order_category": "STD",
            "eq_specif_grp":           "BIS",
            "eq_specifi":              "513_2016",
            "eq_sub_grade":            "CR2_SKIN_PASS",
            "end_appn":                "GE",
            "order_qty":               "10",
            "plant_code":              "1014 - Tarapur Works",
            "cust_req_date":           "06/08/2026",
            "width":                   "1250.000",
            "thickness":               "0.350",
            "length":                  "",
            "edge_con":                "TE",
            "thick_tol_type":          "BILATERAL",
            "oil_req":                 "Y",
        },
        "crca-sheet": {
            "division":                "CRCA",
            "sku_description":         "0.35X1250-P1-CR2_SKIN_P-O2",
            "product_name":            "CRCA Sheet - (S_CRCASF)",
            "customer_order_category": "STD",
            "eq_specif_grp":           "BIS",
            "eq_specifi":              "513_2016",
            "eq_sub_grade":            "CR2_SKIN_PASS",
            "end_appn":                "GE",
            "order_qty":               "10",
            "plant_code":              "1014 - Tarapur Works",
            "cust_req_date":           "06/08/2026",
            "width":                   "1250.000",
            "thickness":               "0.350",
            "length":                  "2500.000",
            "edge_con":                "",
            "thick_tol_type":          "BILATERAL",
            "oil_req":                 "Y",
        },
    }
    test_data = samples[args.sample]

    if args.mode == "open-contract":
        open_contract_for_training(args.contract, pause_seconds=args.pause_seconds)
    elif args.mode == "division":
        division = get_contract_division(args.contract)
        print("Division:", division)
    else:
        result = salesforce_add_contract_line_for_training(
            args.contract,
            test_data,
            pause_seconds=args.pause_seconds,
        )
        print("Line name:", result)
