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
            baseline_line = _find_latest_contract_line_via_related_tab(page, contract_number)
            _click_new_contract_line(page)
            return _fill_contract_line(page, line_data, contract_number, baseline_line)
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
            baseline_line = _find_latest_contract_line_via_related_tab(page, contract_number)
            _click_new_contract_line(page)
            line_name = _fill_contract_line(page, line_data, contract_number, baseline_line) or ""
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

def _fill_contract_line(page, data: dict, contract_number: str = "", baseline_line: str = "") -> str:
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
    coc_value = data.get("customer_order_category", "") or data.get("cust_order_category", "")
    _select_lwc_combobox(page, "Customer Order Category", coc_value)
    if coc_value and not _coc_has_value(page, coc_value):
        page.wait_for_timeout(700)
        _select_lwc_combobox(page, "Customer Order Category", coc_value)
    if coc_value and not _coc_has_value(page, coc_value):
        page.wait_for_timeout(700)
        _select_lwc_combobox(page, "Customer Order Category", coc_value)
    if not _is_coc_selected(page) or (coc_value and not _coc_has_value(page, coc_value)):
        raise RuntimeError("Customer Order Category is still not selected. It is required before Cust key.")
    # Cust key is optional for this flow; do not auto-fill unless explicitly required.
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

    # 3. Eq. Specification Group — LWC combobox
    _select_lwc_combobox(page, "Eq. Specification Group", data.get("eq_specif_grp", ""))
    page.wait_for_timeout(2_000)  # cascading fields update after this
    _screenshot(page, "09_eq_specif_grp")

    # 4. Eq. Specification — cascading LWC combobox (depends on Eq. Spec Group)
    _select_lwc_combobox(page, "Eq. Specification", data.get("eq_specifi", ""))
    page.wait_for_timeout(2_000)
    _screenshot(page, "10_eq_specifi")

    # 5. Eq. Sub Specification — cascading LWC combobox (depends on Eq. Specification)
    _select_lwc_combobox(page, "Eq. Sub Specification", data.get("eq_sub_grade", ""))
    page.wait_for_timeout(1_500)
    _screenshot(page, "11_eq_sub_grade")

    # 6. End Application — LWC combobox
    _select_lwc_combobox(page, "End Application", data.get("end_appn", ""))
    page.wait_for_timeout(1_500)
    _screenshot(page, "12_end_appn")

    # 7. Skip optional Part Number.
    # Per latest requirement, we only fill mandatory (*) fields.
    page.wait_for_timeout(800)

    # 8. Order Quantity — plain number input (in General Fields section)
    _fill_input_by_label(page, "Order Quantity", data.get("order_qty", ""))
    page.wait_for_timeout(1_000)
    _screenshot(page, "13_order_qty")

    # Extract plant info for Supply Plant / Depot and optional S Plant selection.
    plant_raw = data.get("plant_code", "")
    plant_code = plant_raw.split()[0].rstrip("-") if plant_raw else ""
    division = str(data.get("division", "")).strip().upper()

    # 9. Customer Requested Date — date input
    # Keep this before Supply Plant lookup. Plant lookup can open overlays that intercept date clicks.
    _fill_date_by_label(page, "Customer Requested Date", data.get("cust_req_date", ""))
    page.wait_for_timeout(1_500)
    _screenshot(page, "14_cust_req_date")

    # 9b. Supply Plant / Depot lookup
    if plant_raw:
        _fill_supply_plant(page, plant_code, plant_raw)
        page.wait_for_timeout(1_500)
        _screenshot(page, "14b_supply_plant")

    # GI/ZM required fields.
    _fill_lookup_text_by_label(page, "S Brand", data.get("s_brand", ""))
    page.wait_for_timeout(800)
    _screenshot(page, "14c_s_brand")

    # 10. Width
    _fill_input_by_label(page, "Width", data.get("width", ""))
    page.wait_for_timeout(1_000)
    _screenshot(page, "15_width")

    # 11. Thickness
    _fill_input_by_label(page, "Thickness", data.get("thickness", ""))
    page.wait_for_timeout(1_000)
    _screenshot(page, "16_thickness")

    # Length is optional for this flow; skip by design.

    # 12. Edge Condition — LWC combobox
    _select_lwc_combobox(page, "Thickness Tolerance Type", data.get("thick_tol_type", ""))
    page.wait_for_timeout(1_000)
    _screenshot(page, "16c_thick_tol_type")

    _select_lwc_combobox(page, "Oil Required", data.get("oil_req", ""))
    page.wait_for_timeout(1_000)
    _screenshot(page, "16d_oil_required")

    _select_lwc_combobox(page, "Spangle Type", data.get("spangle_type", ""))
    page.wait_for_timeout(1_000)
    _screenshot(page, "16e_spangle_type")

    _fill_input_by_label(page, "Zin_Coating Min(GSM)", data.get("zinc_coating_min", ""))
    page.wait_for_timeout(800)
    _screenshot(page, "16f_zinc_coating_min")

    _fill_gl_coating_min(page, data.get("al_zn_coating_min", ""))
    page.wait_for_timeout(800)
    _screenshot(page, "16g_al_zn_coating_min")

    _select_lwc_combobox(page, "Sleeve Required?", data.get("sleeve_required", ""))
    page.wait_for_timeout(800)
    _screenshot(page, "16h_sleeve_required")

    _select_lwc_combobox(page, "Edge Condition", data.get("edge_con", ""))
    page.wait_for_timeout(1_500)
    _screenshot(page, "17_edge_condition")

    # 13. S Plant — required for some HRC variants.
    # CRCA flow already maps/uses Supply Plant / Depot and forcing S Plant causes flaky overlay issues.
    if plant_raw and division != "CRCA":
        _select_s_plant(page, plant_code, plant_raw)
        page.wait_for_timeout(1_500)
        _screenshot(page, "17b_s_plant")

    _screenshot(page, "18_before_save", full_page=True)
    log.info("All fields filled — ready to save")

    return _save(page, contract_number, baseline_line)


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------

def _select_product_name(page, value: str) -> None:
    """Click 'Please Select product' input — dropdown appears — click matching option."""
    if not value:
        return
    log.info("Selecting Product Name: '%s'", value)
    inp = _product_name_input(page)
    try:
        current = (inp.input_value(timeout=1_000) or "").strip()
        if current:
            log.info("  Product Name already populated: '%s'", current)
            return
    except Exception:
        pass
    inp.scroll_into_view_if_needed(timeout=5_000)
    inp.click(timeout=5_000)
    page.wait_for_timeout(1_000)
    option_scope = _product_name_option_scope(page, inp)

    # Strategy 1: exact/near-exact visible label match.
    try:
        option_scope.filter(
            has_text=re.compile(re.escape(value), re.IGNORECASE)
        ).first.click(timeout=8_000)
        log.info("  Product Name selected via exact label")
        return
    except Exception:
        pass

    # Strategy 2: match by material code token in parentheses, e.g. (S_GICF).
    token_match = re.search(r"\(([^)]+)\)", str(value or ""))
    token = token_match.group(1).strip() if token_match else ""
    if token:
        try:
            option_scope.filter(
                has_text=re.compile(re.escape(token), re.IGNORECASE)
            ).first.click(timeout=8_000)
            log.info("  Product Name selected via material token: %s", token)
            return
        except Exception:
            pass

    # Strategy 3: type + Enter fallback (some orgs resolve lookup on Enter).
    try:
        inp.fill("")
        inp.type(value, delay=20)
        inp.press("Enter")
        page.wait_for_timeout(1_200)
        current = (inp.input_value(timeout=1_000) or "").strip()
        if current:
            log.info("  Product Name selected via typed Enter fallback: '%s'", current)
            return
    except Exception:
        pass

    raise RuntimeError(f"Product Name selection failed for '{value}'")


def _product_name_input(page):
    # Prefer the Product Name field inside New Contract Line modal.
    try:
        handle = page.locator(
            "xpath=//label[normalize-space()='Product Name']/following::input[1]"
        ).first
        if handle.count() and handle.is_visible(timeout=1_500):
            return handle
    except Exception:
        pass
    # Fallback to old selector.
    return page.locator('input[placeholder="Please Select product"]').first


def _product_name_option_scope(page, input_locator):
    # Scope options to the Product Name lookup component to avoid global search options.
    try:
        component = input_locator.locator("xpath=ancestor::c-reusable-lookup[1]")
        if component.count():
            scoped = component.locator('li, [role="option"], lightning-base-combobox-item')
            if scoped.count():
                return scoped
    except Exception:
        pass
    return page.locator('li, [role="option"], lightning-base-combobox-item')


def _select_lwc_combobox(page, label: str, value: str) -> None:
    """
    Select a value from a Salesforce LWC combobox or native select.
    Tries multiple strategies in order of reliability.
    """
    if not value:
        return
    log.info("Selecting combobox '%s' = '%s'", label, value)

    if label in {"Oil Required", "Edge Condition", "Spangle Type"}:
        if _select_gi_recorded_picklist(page, label, value):
            log.info("  selected via recorded GI picklist flow")
            return

    if _select_nearest_native_select(page, label, value):
        log.info("  selected via nearest native <select>")
        return

    if _select_combobox_near_label(page, label, value):
        log.info("  selected via label-scoped combobox")
        return

    if _select_combobox_by_coordinates(page, label, value):
        log.info("  selected via coordinate-scoped combobox")
        return

    # Strategy 0: label row -> native <select> (high priority for Customer Order Category)
    try:
        selected = page.evaluate(
            """({ labelText, val }) => {
                const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const labels = Array.from(document.querySelectorAll('label, span, div'))
                    .filter((el) => norm(el.textContent).includes(norm(labelText)));
                for (const labelEl of labels) {
                    const row = labelEl.closest('tr, .slds-form-element, lightning-layout-item, div');
                    if (!row) continue;
                    const sel = row.querySelector('select');
                    if (!sel) continue;
                    const opts = Array.from(sel.options || []);
                    const idx = opts.findIndex((o) => norm(o.textContent) === norm(val) || norm(o.value) === norm(val));
                    if (idx >= 0) {
                        sel.value = opts[idx].value;
                        sel.dispatchEvent(new Event('input', { bubbles: true }));
                        sel.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    }
                }
                return false;
            }""",
            {"labelText": label, "val": value},
        )
        if selected:
            log.info("  selected via row-level native <select>")
            return
    except Exception:
        pass

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

    if _select_nearest_native_select(page, label, value):
        log.info("  selected via nearest native <select>")
        return

    log.warning("  could not select combobox '%s' = '%s'", label, value)


def _select_gi_recorded_picklist(page, label: str, value: str) -> bool:
    """Select GI picklists using the stable ARIA flow captured from Playwright Inspector."""
    if not value:
        return False
    try:
        if _select_combobox_role_value(page, label, value):
            return True

        if label == "Spangle Type":
            page.get_by_role("combobox", name="Spangle Type").click(timeout=5_000)
            page.wait_for_timeout(400)
            _click_visible_picklist_value(page, value)
        elif label == "Edge Condition":
            page.get_by_role("combobox", name="Edge Condition").click(timeout=5_000)
            page.wait_for_timeout(300)
            page.get_by_role("combobox", name="Edge Condition").click(timeout=5_000)
            page.wait_for_timeout(400)
            _click_visible_picklist_value(page, value)
        elif label == "Oil Required":
            page.get_by_role("combobox", name="Oil Required").click(timeout=5_000)
            page.wait_for_timeout(400)
            page.get_by_role("option", name=value, exact=True).click(timeout=5_000)
        else:
            return False

        page.wait_for_timeout(500)
        return True
    except Exception as exc:
        log.debug("  recorded GI picklist fallback missed for '%s' = '%s': %s", label, value, exc)
        return False


def _select_combobox_role_value(page, label: str, value: str) -> bool:
    """Select a Salesforce combobox by ARIA role using native select/keyboard paths."""
    try:
        combo = page.get_by_role("combobox", name=label).first
        combo.scroll_into_view_if_needed(timeout=3_000)
        try:
            combo.select_option(label=value, timeout=2_000)
            page.wait_for_timeout(500)
            if _field_contains_value(page, label, value):
                return True
        except Exception:
            pass
        try:
            combo.select_option(value=value, timeout=2_000)
            page.wait_for_timeout(500)
            if _field_contains_value(page, label, value):
                return True
        except Exception:
            pass

        combo.click(timeout=5_000)
        page.wait_for_timeout(300)
        if label == "Edge Condition":
            combo.click(timeout=5_000)
            page.wait_for_timeout(300)
        page.keyboard.type(str(value), delay=60)
        page.wait_for_timeout(200)
        page.keyboard.press("Enter")
        page.wait_for_timeout(700)
        page.keyboard.press("Tab")
        page.wait_for_timeout(500)
        return _field_contains_value(page, label, value)
    except Exception as exc:
        log.warning("  role combobox select failed for '%s' = '%s': %s", label, value, exc)
        return False


def _click_visible_picklist_value(page, value: str) -> None:
    pattern = re.compile(r"^\s*" + re.escape(value) + r"\s*$", re.IGNORECASE)
    for selector in [
        "lightning-base-combobox-item:visible",
        "[role='option']:visible",
        ".slds-listbox__item:visible",
        "span:visible",
    ]:
        try:
            page.locator(selector).filter(has_text=pattern).first.click(timeout=3_000)
            return
        except Exception:
            pass
    page.get_by_role("option", name=value, exact=True).click(timeout=5_000)


def _select_combobox_near_label(page, label: str, value: str) -> bool:
    """Open the combobox that belongs to an exact label, then select its value."""
    try:
        opened = page.evaluate(
            """({ labelText, val }) => {
                const norm = (s) => (s || '').replace(/^\\*\\s*/, '').replace(/\\s+/g, ' ').trim();
                const compact = (s) => norm(s).toLowerCase().replace(/[^a-z0-9]/g, '');
                const visible = (el) => {
                    const box = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return box.width > 0 && box.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                };
                const target = compact(labelText);
                const labels = Array.from(document.querySelectorAll('label, span'))
                    .filter((el) => visible(el) && compact(el.textContent) === target);
                for (const labelEl of labels) {
                    let root = labelEl.closest('.slds-form-element, lightning-layout-item, div');
                    for (let i = 0; i < 6 && root; i++, root = root.parentElement) {
                        const select = Array.from(root.querySelectorAll('select')).find(visible);
                        if (select) {
                            const opts = Array.from(select.options || []);
                            const match = opts.find((o) => compact(o.textContent) === compact(val) || compact(o.value) === compact(val));
                            if (match) {
                                select.value = match.value;
                                select.dispatchEvent(new Event('input', { bubbles: true }));
                                select.dispatchEvent(new Event('change', { bubbles: true }));
                                return 'selected';
                            }
                        }
                        const triggers = Array.from(root.querySelectorAll(
                            'button[role="combobox"], button[aria-haspopup="listbox"], button[aria-label], .slds-combobox__input, input[role="combobox"]'
                        )).filter(visible);
                        if (triggers.length) {
                            triggers[triggers.length - 1].click();
                            return 'opened';
                        }
                    }
                }
                return '';
            }""",
            {"labelText": label, "val": value},
        )
        if opened == "selected":
            return True
        if opened != "opened":
            return False
        page.wait_for_timeout(700)
        for sel in [
            f'[role="option"][data-value="{value}"]',
            f'[role="option"][data-mainfield="{value}"]',
            'lightning-base-combobox-item',
            '[role="option"]',
            '.slds-listbox__item',
        ]:
            try:
                page.locator(sel).filter(
                    has_text=re.compile(r'^\s*' + re.escape(value) + r'\s*$', re.IGNORECASE)
                ).first.click(timeout=4_000)
                page.wait_for_timeout(500)
                return True
            except Exception:
                pass
        return False
    except Exception:
        return False


def _select_combobox_by_coordinates(page, label: str, value: str) -> bool:
    """Fallback for Lightning controls whose label/control live inside shadow DOM."""
    try:
        label_loc = page.get_by_text(label, exact=True).last
        if not label_loc.is_visible(timeout=1_500):
            return False
        box = label_loc.bounding_box(timeout=2_000)
        if not box:
            return False
        # Salesforce lays these controls directly below the label. Click near the right
        # edge so native/lightning dropdown arrows open reliably.
        click_x = box["x"] + 600
        click_y = box["y"] + box["height"] + 18
        page.mouse.click(click_x, click_y)
        page.wait_for_timeout(700)
        for selector in [
            f'[role="option"][data-value="{value}"]',
            f'[role="option"][data-mainfield="{value}"]',
            'lightning-base-combobox-item',
            '[role="option"]',
            '.slds-listbox__item',
            f'text="{value}"',
        ]:
            try:
                page.locator(selector).filter(
                    has_text=re.compile(r'^\s*' + re.escape(value) + r'\s*$', re.IGNORECASE)
                ).first.click(timeout=4_000)
                page.wait_for_timeout(600)
                return True
            except Exception:
                pass
        try:
            page.keyboard.press("ArrowDown")
            page.wait_for_timeout(200)
            page.keyboard.press("Enter")
            page.wait_for_timeout(600)
            return True
        except Exception:
            return False
    except Exception:
        return False


def _select_nearest_native_select(page, label: str, value: str) -> bool:
    try:
        return bool(page.evaluate(
            """({ labelText, val }) => {
                const norm = (s) => (s || '').replace(/^\\*\\s*/, '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const compact = (s) => norm(s).replace(/[^a-z0-9]/g, '');
                const visible = (el) => {
                    const box = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return box.width > 0 && box.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                };
                const target = compact(labelText);
                const labels = Array.from(document.querySelectorAll('label, span, div'))
                    .filter((el) => {
                        if (!visible(el)) return false;
                        const text = compact(el.textContent);
                        return text === target || text.includes(target);
                    });
                const selects = Array.from(document.querySelectorAll('select')).filter(visible);
                for (const labelEl of labels) {
                    const labelBox = labelEl.getBoundingClientRect();
                    const ranked = selects
                        .map((sel) => ({ sel, box: sel.getBoundingClientRect() }))
                        .filter(({ box }) => box.top >= labelBox.top - 12 && box.top <= labelBox.bottom + 100)
                        .sort((a, b) => Math.abs(a.box.top - labelBox.bottom) - Math.abs(b.box.top - labelBox.bottom));
                    for (const { sel } of ranked) {
                        const opts = Array.from(sel.options || []);
                        const match = opts.find((o) => norm(o.textContent) === norm(val) || norm(o.value) === norm(val));
                        if (!match) continue;
                        sel.value = match.value;
                        sel.dispatchEvent(new Event('input', { bubbles: true }));
                        sel.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    }
                }
                return false;
            }""",
            {"labelText": label, "val": value},
        ))
    except Exception:
        return False


def _select_lwc_combobox_first_option(page, label: str) -> None:
    """Open combobox and select first visible option."""
    if not label:
        return
    log.info("Selecting first option for combobox '%s'", label)
    for trigger_sel in [f'button[aria-label="{label}"]', f'button[aria-label*="{label}"]']:
        try:
            trigger = page.locator(trigger_sel).first
            if trigger.is_visible(timeout=800):
                trigger.scroll_into_view_if_needed()
                trigger.click(timeout=3_000)
                page.wait_for_timeout(600)
                try:
                    page.locator(
                        '[role="option"], lightning-base-combobox-item, .slds-listbox__item'
                    ).first.click(timeout=5_000)
                    page.wait_for_timeout(700)
                    log.info("  selected first option via '%s'", trigger_sel)
                    return
                except Exception:
                    # Some LWC dropdowns require keyboard selection after opening.
                    page.keyboard.press("ArrowDown")
                    page.wait_for_timeout(200)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(700)
                    log.info("  selected first option via keyboard on '%s'", trigger_sel)
                    return
        except Exception:
            pass
    log.warning("  could not select first option for '%s'", label)


def _is_coc_selected(page) -> bool:
    """True when Customer Order Category is not blank/--None--."""
    try:
        btn = page.locator('button[aria-label="Customer Order Category"]').first
        text = (btn.inner_text(timeout=1_000) or "").strip()
        if not text:
            text = (btn.get_attribute("data-value") or "").strip()
        if not text:
            return False
        lowered = str(text).strip().lower()
        return lowered not in {"--none--", "none", "select customer order category", "select"}
    except Exception:
        return False


def _coc_has_value(page, expected: str) -> bool:
    try:
        btn = page.locator('button[aria-label="Customer Order Category"]').first
        text = (btn.inner_text(timeout=1_000) or "").strip()
        data_value = (btn.get_attribute("data-value") or "").strip()
        exp = str(expected or "").strip().lower()
        return text.lower() == exp or data_value.lower() == exp
    except Exception:
        return False


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
        log.debug("  dropdown option fallback missed for '%s': %s", value, e)


def _fill_part_number(page, value: str) -> bool:
    """Fill Part Number for both lookup and dropdown-style layouts."""
    if not value:
        return False
    log.info("Filling Part Number: '%s'", value)
    try:
        # Strategy 0: direct LWC trigger by aria-label, then choose first matching/visible option.
        for trigger_sel in ['button[aria-label="Part Number"]', 'button[aria-label*="Part Number"]']:
            try:
                trigger = page.locator(trigger_sel).first
                if trigger.is_visible(timeout=1_000):
                    trigger.scroll_into_view_if_needed(timeout=3_000)
                    trigger.click(timeout=3_000, force=True)
                    page.wait_for_timeout(700)
                    try:
                        page.locator(
                            '[role="option"], lightning-base-combobox-item, .slds-listbox__item'
                        ).filter(has_text=re.compile(re.escape(value), re.IGNORECASE)).first.click(timeout=4_000)
                    except Exception:
                        page.locator(
                            '[role="option"], lightning-base-combobox-item, .slds-listbox__item'
                        ).first.click(timeout=4_000)
                    page.wait_for_timeout(900)
                    if _field_has_any_value(page, "Part Number"):
                        log.info("  Part Number selected via direct LWC trigger")
                        return True
            except Exception:
                pass

        # New Contract Line (CRCA) frequently renders Part Number as a dropdown.
        if _open_dropdown_near_label(page, "Part Number"):
            page.wait_for_timeout(600)
            _click_dropdown_option(page, value, timeout=8_000)
            page.wait_for_timeout(900)
            if _field_contains_value(page, "Part Number", value):
                log.info("  Part Number selected via dropdown near label")
                return True
            # If exact text did not match, choose first visible row (user-approved behavior).
            try:
                page.locator(
                    '[role="option"], li[role="presentation"], lightning-base-combobox-item, .slds-listbox__item'
                ).first.click(timeout=5_000)
                page.wait_for_timeout(1_000)
                if _field_has_any_value(page, "Part Number"):
                    log.info("  Part Number selected via first visible dropdown option")
                    return True
            except Exception:
                pass

        # Scroll the disabled input into view first
        inp = page.locator(
            'input[placeholder="Select Part Number"], '
            'input[placeholder*="Part Number"], '
            'input[aria-label*="Part Number"]'
        ).first
        inp.scroll_into_view_if_needed(timeout=5_000)
        page.wait_for_timeout(500)
        try:
            if not inp.is_enabled(timeout=500):
                toggle = inp.locator(
                    'xpath=ancestor::*[contains(@class,"slds-combobox__form-element")][1]//button | '
                    'ancestor::*[contains(@class,"slds-combobox")][1]//button'
                ).first
                if toggle.is_visible(timeout=1_000):
                    toggle.click(timeout=3_000, force=True)
                    page.wait_for_timeout(700)
                    page.locator(
                        '[role="option"], lightning-base-combobox-item, .slds-listbox__item'
                    ).first.click(timeout=5_000)
                    page.wait_for_timeout(1_000)
                    if _field_has_any_value(page, "Part Number"):
                        log.info("  Part Number selected via disabled-input toggle fallback")
                        return True
        except Exception:
            pass

        # Click the search button (magnifying glass) — traverse up DOM to find it.
        clicked = _click_lookup_button_near_input(page, "Part Number")
        if not clicked:
            try:
                inp.click(timeout=3_000)
                clicked = True
            except Exception:
                pass
        if not clicked:
            log.warning("  Part Number search button not found; trying direct combobox option fallback")
            try:
                inp.click(timeout=3_000)
                page.wait_for_timeout(800)
                page.locator('li, [role="option"], lightning-base-combobox-item').filter(
                    has_text=re.compile(re.escape(value), re.IGNORECASE)
                ).first.click(timeout=6_000)
                page.wait_for_timeout(1_000)
                _screenshot(page, "11b_part_number_direct_option_fallback")
                log.info("  Part Number selected via direct option fallback")
                return True
            except Exception:
                pass
            try:
                inp.click(timeout=3_000)
                page.wait_for_timeout(800)
                page.locator('[role="option"], li, lightning-base-combobox-item, .slds-listbox__item').first.click(timeout=5_000)
                page.wait_for_timeout(1_000)
                _screenshot(page, "11c_part_number_first_option_fallback")
                if _field_has_any_value(page, "Part Number"):
                    log.info("  Part Number selected via first visible option fallback")
                    return True
            except Exception:
                pass
            try:
                inp.click(timeout=3_000)
                inp.fill(value)
                page.wait_for_timeout(1_200)
                page.keyboard.press("ArrowDown")
                page.wait_for_timeout(250)
                page.keyboard.press("Enter")
                page.wait_for_timeout(1_200)
                _screenshot(page, "11d_part_number_direct_typing_fallback")
                if _field_has_any_value(page, "Part Number"):
                    log.info("  Part Number selected via direct typing fallback")
                    return True
            except Exception:
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
        if _field_has_any_value(page, "Part Number"):
            log.info("  Part Number selected")
            return True
        return False
    except Exception as e:
        log.warning("  Part Number failed: %s", e)
        return False


def _open_dropdown_near_label(page, label: str) -> bool:
    try:
        clicked = page.evaluate(
            """(labelText) => {
                const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                const isVisible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                };
                const labels = Array.from(document.querySelectorAll('label, span'))
                    .filter((el) => norm(el.textContent).toLowerCase() === labelText.toLowerCase());
                for (const labelEl of labels) {
                    let root = labelEl.closest('.slds-form-element, lightning-layout-item, div');
                    for (let i = 0; i < 6 && root; i++, root = root.parentElement) {
                        const candidates = Array.from(root.querySelectorAll(
                            'button, [role="button"], .slds-combobox__input, input'
                        )).filter(isVisible);
                        const trigger = candidates.find((el) => /Part Number|Select Part Number/i.test(
                            norm(el.getAttribute('aria-label')) + ' ' + norm(el.getAttribute('placeholder'))
                        )) || candidates[candidates.length - 1];
                        if (trigger) {
                            trigger.click();
                            return true;
                        }
                    }
                }
                return false;
            }""",
            label,
        )
        return bool(clicked)
    except Exception:
        return False


def _field_contains_value(page, label: str, expected: str) -> bool:
    try:
        text = page.evaluate(
            """(labelText) => {
                const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                const labels = Array.from(document.querySelectorAll('label, span'))
                    .filter((el) => norm(el.textContent).toLowerCase() === labelText.toLowerCase());
                for (const labelEl of labels) {
                    const root = labelEl.closest('.slds-form-element, lightning-layout-item, div') || labelEl.parentElement;
                    if (!root) continue;
                    const valueEl = root.querySelector('input, button, .slds-combobox__input, .slds-truncate');
                    if (!valueEl) continue;
                    const value = norm(valueEl.value || valueEl.textContent || valueEl.getAttribute('title'));
                    if (value) return value;
                }
                return '';
            }""",
            label,
        )
        return str(expected or "").strip().lower() in str(text or "").strip().lower()
    except Exception:
        return False


def _field_has_any_value(page, label: str) -> bool:
    try:
        text = page.evaluate(
            """(labelText) => {
                const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                const labels = Array.from(document.querySelectorAll('label, span'))
                    .filter((el) => norm(el.textContent).toLowerCase() === labelText.toLowerCase());
                for (const labelEl of labels) {
                    const root = labelEl.closest('.slds-form-element, lightning-layout-item, div') || labelEl.parentElement;
                    if (!root) continue;
                    const valueEl = root.querySelector('input, button, .slds-combobox__input, .slds-truncate');
                    if (!valueEl) continue;
                    const value = norm(valueEl.value || valueEl.textContent || valueEl.getAttribute('title'));
                    if (value && !/^select /i.test(value)) return value;
                }
                return '';
            }""",
            label,
        )
        return bool(str(text or "").strip())
    except Exception:
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
            page.wait_for_timeout(1_000)
            if _supply_plant_lookup_modal_open(page):
                _save_supply_plant_lookup_modal(page)
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


def _wait_supply_plant_lookup_closed(page, timeout_ms: int = 12_000) -> bool:
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        if not _supply_plant_lookup_modal_open(page):
            return True
        page.wait_for_timeout(500)
    return not _supply_plant_lookup_modal_open(page)


def _select_supply_plant_result(page, value: str, plant_raw: str = "") -> bool:
    """Select the exact Supply Plant result from the JSW Locations full lookup modal."""
    plant_keyword = _plant_keyword(plant_raw or value)
    code = str(value or "").strip()

    # Salesforce lookup modals need a real browser click on the DESCRIPTION link.
    # JS element.click() can find the row but leave the modal open.
    for pattern in [code, plant_keyword]:
        if not pattern:
            continue
        try:
            row = page.locator("table tbody tr").filter(
                has_text=re.compile(re.escape(pattern), re.IGNORECASE)
            ).first
            if row.is_visible(timeout=2_000):
                link = row.locator("a").first
                link.scroll_into_view_if_needed(timeout=2_000)
                link.click(timeout=5_000, force=True)
                if _wait_supply_plant_lookup_closed(page):
                    return True
                if _save_supply_plant_lookup_modal(page):
                    return True
        except Exception:
            pass

    # Preferred path: click DESCRIPTION link for the row whose CODE matches.
    try:
        selected = page.evaluate(
            """({ code, keyword }) => {
                const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                const lower = (s) => norm(s).toLowerCase();
                const codeNorm = norm(code);
                const rows = Array.from(document.querySelectorAll('table tbody tr'));
                for (const row of rows) {
                    const cells = Array.from(row.querySelectorAll('td'));
                    if (!cells.length) continue;
                    const rowCode = cells.length > 1 ? norm(cells[1].innerText || cells[1].textContent) : '';
                    const rowText = lower(row.innerText || row.textContent);
                    const codeMatch = codeNorm && rowCode === codeNorm;
                    const keywordMatch = keyword && rowText.includes(lower(keyword));
                    if (codeMatch || keywordMatch) {
                        const descLink = cells[0].querySelector('a') || row.querySelector('a');
                        if (descLink) {
                            descLink.click();
                            return true;
                        }
                    }
                }
                return false;
            }""",
            {"code": code, "keyword": plant_keyword},
        )
        if selected:
            if _wait_supply_plant_lookup_closed(page):
                return True
            if _save_supply_plant_lookup_modal(page):
                return True
    except Exception:
        pass
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
            {"code": code, "keyword": plant_keyword},
        )
        if selected:
            if _wait_supply_plant_lookup_closed(page):
                return True
            if _save_supply_plant_lookup_modal(page):
                return True
    except Exception:
        pass
    return False


def _save_supply_plant_lookup_modal(page) -> bool:
    try:
        clicked = page.evaluate(
            """() => {
                const visible = (el) => {
                    const box = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return box.width > 0 && box.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                };
                const modals = Array.from(document.querySelectorAll('.modal-container, .slds-modal__container'))
                    .filter(visible);
                const modal = modals[modals.length - 1] || document;
                const buttons = Array.from(modal.querySelectorAll('button, input[type="button"], input[type="submit"]'))
                    .filter(visible);
                const save = buttons.reverse().find((btn) => {
                    const text = (btn.innerText || btn.value || btn.title || btn.getAttribute('aria-label') || '').trim();
                    return text.toLowerCase() === 'save';
                });
                if (!save) return false;
                save.click();
                return true;
            }"""
        )
        if clicked:
            if _wait_supply_plant_lookup_closed(page):
                return True
    except Exception:
        pass
    try:
        modal = page.locator(".modal-container, .slds-modal__container").filter(
            has_text=re.compile(r"Supply Plant\s*/\s*Depot", re.IGNORECASE)
        ).last
        btn = modal.locator('button:has-text("Save")').last
        btn.scroll_into_view_if_needed(timeout=2_000)
        btn.click(timeout=5_000, force=True)
        return _wait_supply_plant_lookup_closed(page)
    except Exception:
        return False


def _input_by_label(page, label: str):
    try:
        handle = page.evaluate_handle(
            """(labelText) => {
                const norm = (s) => (s || '').replace(/^\\*\\s*/, '').replace(/\\s+/g, ' ').trim();
                const labels = Array.from(document.querySelectorAll('label, span, div'))
                    .filter((el) => norm(el.textContent) === norm(labelText));
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

    def _click_first_real_option() -> bool:
        """Fallback for GI where S Plant option text may differ from the depot name."""
        for sel in ['[role="option"]', 'lightning-base-combobox-item', '.slds-listbox__item']:
            try:
                options = page.locator(sel)
                count = min(options.count(), 20)
                for idx in range(count):
                    option = options.nth(idx)
                    text = " ".join((option.inner_text(timeout=800) or "").split())
                    if not text or "--None--" in text:
                        continue
                    option.click(timeout=3_000)
                    log.info("  S Plant selected first available option: '%s'", text)
                    return True
            except Exception:
                pass
        return False

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
                if _click_first_real_option():
                    return
        except Exception:
            pass

    # Fallback: native <select> — try matching by keyword in option text
    for sel in ['select[aria-label="S Plant"]', 'select[aria-label*="S Plant"]']:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=800):
                options = loc.locator('option').all_inner_texts()
                match = next((o for o in options if keyword.lower() in o.lower()), None)
                if not match:
                    match = next((o for o in options if o.strip() and "--None--" not in o), None)
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


def _fill_gl_coating_min(page, value: str) -> None:
    """Fill GL coating minimum field; portal label may vary slightly by layout."""
    if not value:
        return
    for label in (
        "AL ZN Coating GSM MIN",
        "AL ZN Coating Min(GSM)",
        "AL ZN Coating Min",
        "AL ZN COATING MIN",
    ):
        try:
            log.info("Filling GL coating minimum '%s' = '%s'", label, value)
            for sel in [f'input[aria-label="{label}"]', f'input[aria-label*="{label}"]']:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=1_000):
                    loc.scroll_into_view_if_needed()
                    loc.fill(value)
                    log.info("  filled via aria-label: %s", sel)
                    return
            label_el = page.locator(f'label:has-text("{label}")').first
            for_id = label_el.get_attribute("for", timeout=1_000)
            if for_id:
                page.locator(f'input#{for_id}').fill(value)
                log.info("  filled via label[for]")
                return
            inp = label_el.locator(
                'xpath=following-sibling::div[1]//input | following-sibling::*[1]//input'
            )
            if inp.count() > 0:
                inp.first.scroll_into_view_if_needed()
                inp.first.fill(value)
                log.info("  filled via label sibling div//input")
                return
        except Exception:
            pass
    log.warning("  could not fill GL AL ZN coating minimum")


def _fill_lookup_text_by_label(page, label: str, value: str) -> None:
    """Fill a lookup-style text field by label and select the matching/first result."""
    if not value:
        return
    log.info("Filling lookup '%s' = '%s'", label, value)
    try:
        inp = _input_by_label(page, label)
        if inp is None:
            if label.strip().lower() == "s brand":
                inp = page.locator('input[placeholder*="Select Brand"], input[placeholder*="Brand"], input[aria-label*="Brand"]').first
            else:
                inp = page.locator(f'input[placeholder*="{label}"], input[aria-label*="{label}"]').first
        inp.scroll_into_view_if_needed(timeout=4_000)
        inp.click(timeout=4_000, force=True)
        page.wait_for_timeout(300)
        inp.fill(str(value))
        page.wait_for_timeout(1_000)
        try:
            page.locator('li, [role="option"], lightning-base-combobox-item, .slds-listbox__item').filter(
                has_text=re.compile(re.escape(str(value)), re.IGNORECASE)
            ).first.click(timeout=4_000, force=True)
        except Exception:
            try:
                page.keyboard.press("Enter")
            except Exception:
                pass
        page.wait_for_timeout(800)
    except Exception as exc:
        log.warning("  could not fill lookup '%s': %s", label, exc)


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


def _save(page, contract_number: str = "", baseline_line: str = "") -> str:
    """Click Save, wait for the detail page, then return the contract line name (e.g. '00170850_20')."""
    _fix_resolution(page)
    log.info("Clicking Save")
    try:
        # Wait for any animations/re-renders to settle before locating Save
        page.wait_for_timeout(1_500)
        save_btn = page.locator(
            '.modal-container button.slds-button_brand:has-text("Save"), '
            '.slds-modal button.slds-button_brand:has-text("Save"), '
            'button.slds-button_brand:has-text("Save"), '
            'button:has-text("Save")'
        ).first
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
        baseline_idx = _line_index(baseline_line)
        created_idx = _line_index(line_name)
        if baseline_idx and created_idx and created_idx <= baseline_idx and contract_number:
            # Salesforce occasionally shows stale Related data right after Save.
            # Retry with longer waits + reload before declaring failure.
            for attempt in range(1, 7):
                try:
                    page.wait_for_timeout(4_000 if attempt < 3 else 8_000)
                    page.reload(wait_until="domcontentloaded", timeout=25_000)
                    page.wait_for_timeout(2_500)
                except Exception:
                    pass
                retried = _find_latest_contract_line_via_related_tab(page, contract_number)
                retried_idx = _line_index(retried)
                if retried_idx > baseline_idx:
                    line_name = retried
                    created_idx = retried_idx
                    break
            if created_idx <= baseline_idx:
                raise RuntimeError(
                    f"No new Contract Line Item was created for contract {contract_number}. "
                    f"Latest line is still {line_name}."
                )
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


def _line_index(line_name: str) -> int:
    match = re.match(r"^\d{7,9}_(\d+)$", str(line_name or "").strip())
    if not match:
        return 0
    try:
        return int(match.group(1))
    except Exception:
        return 0


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
