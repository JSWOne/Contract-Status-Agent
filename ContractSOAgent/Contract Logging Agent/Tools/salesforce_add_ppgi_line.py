"""
Tool: salesforce_add_ppgi_line.py
Purpose: Create a PPGI (or PPGL) SKU contract line item in the JSW One Salesforce portal.

==============================================================================
CONFIRMED WORKING PATTERNS — DO NOT CHANGE WITHOUT RE-TESTING
(verified 2026-05-27 via Playwright Inspector recording + live runs)
==============================================================================

1. LWC PICKLIST / COMBOBOX (Customer Order Cat, Eq. Spec Group, Tolerance Type, etc.)
   ─────────────────────────────────────────────────────────────────────────────
   Playwright Inspector recording:
       page.get_by_role("combobox", name="Tolerance Type", exact=True).click()
       page.locator("span").filter(has_text="AS_STD").first.click()

   Key rules:
   • Use get_by_role("combobox", name=label, exact=True) — no scroll_into_view_if_needed
     before the click (scroll pushes the field to modal bottom, options land behind footer)
   • Use locator("span").filter(has_text=value) — NOT [role="option"] (those sit inside
     shadow roots and are not directly clickable)
   • Use force=True on the span click — the slds-media__body span resolves correctly but
     may not pass Playwright's visibility check while the dropdown is animating
   • For "Tolerance Type" specifically: call wait_for(state="visible") first because the
     field only renders after the Thickness Tolerance Type cascade update completes

2. TOP COLOR CODE (lookup combobox, search-and-select)
   ─────────────────────────────────────────────────────────────────────────────
   Playwright Inspector recording:
       page.get_by_role("combobox", name="Top Color Code").click()
       page.get_by_role("combobox", name="Top Color Code").fill("JSWA034S")
       page.get_by_text("JSWA034SRMP_BLUE_ULTRAMARINE").click()

   Key rules:
   • Use get_by_role("combobox", name="Top Color Code") + .fill(value) directly
   • Wait 2 s after fill for Salesforce to query color codes
   • Click option via [role="option"] or span.filter or get_by_text — all with force=True
   • The option text is the color code concatenated with description
     (e.g. "JSWA034SRMP_BLUE_ULTRAMARINE") — any of these approaches matches it
   • NEVER use ArrowDown+Enter — Enter opens a blank new block in this field

3. S PLANT (LWC combobox near bottom of form)
   ─────────────────────────────────────────────────────────────────────────────
   Playwright Inspector recording:
       page.get_by_role("combobox", name="S Plant").click()
       page.locator("span").filter(has_text="JSCPL – DHAR").first.click()

   Key rules:
   • Use get_by_role("combobox", name="S Plant") — no exact=True (asterisk on required label)
   • NO scroll_into_view_if_needed before click (same footer-overlay issue)
   • Option text contains keyword e.g. "DHAR" — span.filter(has_text="DHAR") matches it

4. SUPPLY PLANT / DEPOT (text lookup field, not combobox)
   ─────────────────────────────────────────────────────────────────────────────
   • Fill input with plant_code ("1044"), then wait 3 s (API is slow — 1.2 s too short)
   • The lookup opens a sub-modal table: DESCRIPTION (link) | CODE (span) | TYPE
   • Click the DESCRIPTION <a> link ("JSCPL - DHAR") — NOT the CODE span ("1044")!
     span.filter(has_text="1044") hits the CODE column which is plain text —
     clicking it does NOT close the modal or select the plant.
     Use: page.locator("table a").filter(has_text=re.compile("DHAR")).first.click()
   • Fallback: click "Show more results" → wait 3 s → click from modal table
   • ALWAYS close any leftover lookup modal in finally block — leaving it open
     blocks ALL subsequent form fields (TTT, Tolerance Type, Guard Film, etc.)

5. GUARD FILM REQUIRED
   ─────────────────────────────────────────────────────────────────────────────
   Inspector: page.get_by_role("combobox", name="Guard Film Required").click()
              page.locator("span").filter(has_text="Yes").first.click()
   • Same span.filter + force=True pattern as all other picklists

6. THICKNESS TOLERANCE TYPE / TOLERANCE TYPE ordering
   ─────────────────────────────────────────────────────────────────────────────
   • Fill Thickness Tolerance Type first via _fill_thick_tol_type_direct() — same
     footer-overlay issue as Tolerance Type; must NOT use _select_combobox()
   • wait_for(visible) + click WITHOUT scroll_into_view_if_needed + force=True on span
   • Then wait 3 s for cascade, then fill Tolerance Type via _fill_tolerance_type_direct()
   • NEVER use _select_combobox / _select_combobox_and_commit for either of these two fields
==============================================================================

Dedicated, clean script for PPGI/PPGL divisions only — no HRC/GI/GL branching.
Fixes the two bugs found in the general script:
  1. Top Color Code: detects already-selected state (data-value) and skips the second fill
  2. S Plant: keyword-based option matching for any plant, not just Kalmeshwar

PPGI form fields (in order):
  Product Name → Customer Order Category → Eq. Spec Group → Eq. Specification →
  Eq. Sub Specification → End Application → Order Quantity → Customer Requested Date →
  Supply Plant / Depot → S Brand → Width → Thickness → Length (sheet only) →
  Thickness Tolerance Type → Tolerance Type → Zin_Coating Min(GSM) [PPGI] /
  AL ZN Coating Min(GSM) [PPGL] → Guard Film Required → Top Color Code → S Plant

Usage (local training / debug run):
    cd ".../Contract Logging Agent/Tools"
    python salesforce_add_ppgi_line.py --contract 00179274 --mode create --pause 120

    # Dry-run: just open the contract without filling anything
    python salesforce_add_ppgi_line.py --contract 00179274 --mode open

Sample data built in for quick testing:
    python salesforce_add_ppgi_line.py --contract 00179274 --mode create --sample ppgi-sheet --pause 120
    python salesforce_add_ppgi_line.py --contract 00179274 --mode create --sample ppgi-coil --pause 120
    python salesforce_add_ppgi_line.py --contract 00179274 --mode create --sample ppgl-sheet --pause 120
"""

import os
import re
import sys
import time
import logging
import argparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

_ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=os.path.abspath(_ENV_PATH), override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

BASE_URL       = "https://jswsteel.my.site.com"
# /tmp works on Linux (Cloud Run); on Windows Python resolves it to C:\tmp
DEBUG_DIR      = os.path.join(
    "C:\\tmp" if os.name == "nt" else "/tmp", "sf_ppgi_debug"
)
PORTAL_WIDTH   = 1920
PORTAL_HEIGHT  = 1080
PORTAL_VP      = {"width": PORTAL_WIDTH, "height": PORTAL_HEIGHT}


# ---------------------------------------------------------------------------
# Sample data for local testing
# ---------------------------------------------------------------------------

SAMPLES = {
    "ppgi-sheet": {
        "division":                "PPGI",
        "product_name":            "PPGI Sheet - (S_PPGISF)",
        "customer_order_category": "STD",
        "eq_specif_grp":           "BIS",
        "eq_specifi":              "277_2018",
        "eq_sub_grade":            "GP_250",
        "end_appn":                "GE",
        "order_qty":               "40",
        "cust_req_date":           "06/08/2026",
        "plant_code":              "1018",
        "s_brand":                 "JSW RADIANCE",
        "width":                   "1220.000",
        "thickness":               "0.800",
        "length":                  "3050.000",
        "thick_tol_type":          "TCTMAX",
        "tolerance_type":          "AS_STD",
        "zinc_coating_min":        "120",
        "guard_film_required":     "Y",
        "top_color_code":          "JSWA034S",
    },
    "ppgi-coil": {
        "division":                "PPGI",
        "product_name":            "PPGI Coil - (S_PPGICF)",
        "customer_order_category": "STD",
        "eq_specif_grp":           "BIS",
        "eq_specifi":              "277_2018",
        "eq_sub_grade":            "GPL",
        "end_appn":                "GE",
        "order_qty":               "50",
        "cust_req_date":           "06/08/2026",
        "plant_code":              "1044",
        "s_brand":                 "JSW RADIANCE",
        "width":                   "800.000",
        "thickness":               "0.400",
        "thick_tol_type":          "TCTNOM",
        "tolerance_type":          "CUST_SPEC",
        "zinc_coating_min":        "90",
        "guard_film_required":     "N",
        "top_color_code":          "JSWV343S00",
    },
    "ppgl-sheet": {
        "division":                "PPGL",
        "product_name":            "PPGL Sheet - (S_PPGLSF)",
        "customer_order_category": "STD",
        "eq_specif_grp":           "BIS",
        "eq_specifi":              "277_2018",
        "eq_sub_grade":            "GP_250",
        "end_appn":                "GE",
        "order_qty":               "10",
        "cust_req_date":           "06/07/2026",
        "plant_code":              "1044",
        "s_brand":                 "JSW RADIANCE",
        "width":                   "1220.000",
        "thickness":               "0.800",
        "length":                  "3050.000",
        "thick_tol_type":          "TCTMAX",
        "tolerance_type":          "AS_STD",
        "al_zn_coating_min":       "120",
        "guard_film_required":     "Y",
        "top_color_code":          "JSWA034S",
    },
    "ppgl-coil": {
        "division":                "PPGL",
        "product_name":            "PPGL Coil - (S_PPGLCF)",
        "customer_order_category": "STD",
        "eq_specif_grp":           "BIS",
        "eq_specifi":              "277_2018",
        "eq_sub_grade":            "GP_250",
        "end_appn":                "GE",
        "order_qty":               "10",
        "cust_req_date":           "06/07/2026",
        "plant_code":              "1044",
        "s_brand":                 "JSW RADIANCE",
        "width":                   "1220.000",
        "thickness":               "0.800",
        "thick_tol_type":          "TCTMAX",
        "tolerance_type":          "AS_STD",
        "al_zn_coating_min":       "120",
        "guard_film_required":     "Y",
        "top_color_code":          "JSWA034S",
    },
}


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def add_ppgi_contract_line(contract_number: str, line_data: dict) -> str:
    """
    Headless production entry point.
    Returns the saved contract line name (e.g. '00179274_30'), or raises on failure.
    """
    os.makedirs(DEBUG_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = _launch_browser(p, headed=False)
        page    = _new_page(browser)
        try:
            _login(page)
            _search_and_open_contract(page, contract_number)
            baseline = _latest_contract_line(page, contract_number)
            _click_new_contract_line(page)
            return _fill_ppgi_form(page, line_data, contract_number, baseline)
        finally:
            browser.close()


def add_ppgi_contract_line_for_training(
    contract_number: str,
    line_data: dict,
    pause_seconds: int = 300,
    stop_at_tolerance: bool = False,
    stop_at_s_plant: bool = False,
) -> str:
    """
    Headed (visible browser) entry point for local testing.
    Pauses for `pause_seconds` after completion so you can verify in Salesforce.
    When stop_at_tolerance=True, fills all fields up to Thickness Tolerance Type then
    opens Playwright Inspector so you can manually record the remaining interactions.
    """
    os.makedirs(DEBUG_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = _launch_browser(p, headed=True)
        page    = _new_page(browser)
        try:
            _login(page)
            _search_and_open_contract(page, contract_number)
            baseline = _latest_contract_line(page, contract_number)
            _click_new_contract_line(page)
            line_name = _fill_ppgi_form(
                page, line_data, contract_number, baseline,
                stop_at_tolerance=stop_at_tolerance,
                stop_at_s_plant=stop_at_s_plant,
            )
            if stop_at_tolerance:
                log.info("stop_at_tolerance mode — no Save performed.")
                return ""
            log.info("Contract line created: %s", line_name or "[not captured]")
            if pause_seconds > 0:
                log.info("Browser open for %s seconds — verify in Salesforce.", pause_seconds)
                time.sleep(pause_seconds)
            return line_name
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

def _launch_browser(p, headed: bool = False):
    headless = not headed
    # Respect env override (PLAYWRIGHT_HEADLESS=false forces headed)
    env_val = os.getenv("PLAYWRIGHT_HEADLESS", "").strip().lower()
    if env_val in {"0", "false", "no", "n", "off"}:
        headless = False
    slow_mo = 0
    try:
        slow_mo = int(os.getenv("PLAYWRIGHT_SLOW_MO_MS", "0").strip())
    except Exception:
        pass
    return p.chromium.launch(
        headless=headless,
        slow_mo=slow_mo,
        args=[
            "--start-maximized",
            f"--window-size={PORTAL_WIDTH},{PORTAL_HEIGHT}",
            "--force-device-scale-factor=1",
        ],
    )


def _new_page(browser):
    page = browser.new_page(
        viewport=PORTAL_VP,
        screen=PORTAL_VP,
        device_scale_factor=1,
    )
    _fix_viewport(page)
    return page


def _fix_viewport(page) -> None:
    try:
        page.set_viewport_size(PORTAL_VP)
    except Exception:
        pass
    try:
        cdp = page.context.new_cdp_session(page)
        win = cdp.send("Browser.getWindowForTarget")
        cdp.send("Browser.setWindowBounds", {
            "windowId": win["windowId"],
            "bounds": {
                "left": 0, "top": 0,
                "width": PORTAL_WIDTH, "height": PORTAL_HEIGHT,
                "windowState": "maximized",
            },
        })
    except Exception:
        pass
    # Keep long PPGI modals usable on a 1080p Windows screen. Leave room for
    # the browser chrome and taskbar so S Plant dropdowns and Save stay visible.
    try:
        page.evaluate("""() => {
            const styleId = 'ppgi-modal-fix';
            document.getElementById(styleId)?.remove();
            const s = document.createElement('style');
            s.id = styleId;
            s.textContent = `
                .slds-modal__container, .uiModal .modal-container {
                    max-height: calc(100vh - 130px) !important;
                    height: calc(100vh - 130px) !important;
                    margin-top: 18px !important;
                    margin-bottom: 96px !important;
                }
                .slds-modal__content, .uiModal .modal-body {
                    max-height: calc(100vh - 270px) !important;
                    padding-bottom: 22px !important;
                    overflow-y: auto !important;
                }
                .slds-modal__footer, .forceModalActionContainer {
                    position: sticky !important;
                    bottom: 0 !important;
                    z-index: 1000 !important;
                    background: white !important;
                    box-shadow: 0 -2px 8px rgba(0,0,0,.08) !important;
                }
            `;
            document.head.appendChild(s);
        }""")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Step 1 — Login
# ---------------------------------------------------------------------------

def _login(page) -> None:
    url      = os.environ["SALESFORCE_URL"]
    username = os.environ["SALESFORCE_USERNAME"]
    password = os.environ["SALESFORCE_PASSWORD"]
    log.info("Logging in to Salesforce …")
    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_selector('input[placeholder="Username"]', timeout=20_000)
    page.locator('input[placeholder="Username"]').fill(username)
    page.locator('input[type="password"]').fill(password)
    page.locator('button:has-text("Log in")').click()
    page.wait_for_url(lambda u: "/login" not in u.lower(), timeout=30_000)
    log.info("Logged in OK")
    _shot(page, "01_logged_in")


# ---------------------------------------------------------------------------
# Step 2 — Search and open contract
# ---------------------------------------------------------------------------

def _search_and_open_contract(page, contract_number: str) -> None:
    log.info("Opening contract %s …", contract_number)
    search = page.locator('input[placeholder="Search..."]').first
    search.click(timeout=10_000)
    page.wait_for_timeout(500)
    search.fill(contract_number)
    page.wait_for_timeout(2_000)
    _shot(page, "02_search_dropdown")

    clicked = _click_exact_contract_result(page, contract_number)
    if not clicked:
        for sel in [
            f'li:has-text("{contract_number}"):has-text("Contract")',
            f'[role="option"]:has-text("{contract_number}"):has-text("Contract")',
            'li:has-text("Contract")',
        ]:
            try:
                loc = page.locator(sel).filter(has_not_text="Contract Line").first
                if loc.is_visible(timeout=2_000):
                    loc.click(timeout=5_000)
                    clicked = True
                    break
            except Exception:
                pass
    if not clicked:
        search.press("Enter")

    page.wait_for_timeout(4_000)
    _shot(page, "03_contract_detail")
    log.info("Contract %s opened OK", contract_number)


def _click_exact_contract_result(page, contract_number: str) -> bool:
    try:
        clicked = page.evaluate("""(num) => {
            for (const el of document.querySelectorAll('li, [role="option"]')) {
                const lines = (el.innerText || '').split(/\\n+/).map(s => s.trim()).filter(Boolean);
                if (lines.some(l => l === num) &&
                    lines.some(l => l === 'Contract') &&
                    !lines.some(l => l === 'Contract Line')) {
                    el.click();
                    return true;
                }
            }
            return false;
        }""", contract_number)
        if clicked:
            log.info("  exact Contract result clicked")
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Step 3 — Click New Contract Line
# ---------------------------------------------------------------------------

def _click_new_contract_line(page) -> None:
    _fix_viewport(page)
    log.info("Clicking New Contract Line …")
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
    _fix_viewport(page)
    _shot(page, "04_form_opened")
    log.info("New Contract Line form opened OK")


# ---------------------------------------------------------------------------
# Step 4 — Fill PPGI/PPGL form
# ---------------------------------------------------------------------------

def _fill_ppgi_form(
    page,
    data: dict,
    contract_number: str = "",
    baseline_line: str = "",
    stop_at_tolerance: bool = False,
    stop_at_s_plant: bool = False,
) -> str:
    _fix_viewport(page)
    division = str(data.get("division", "PPGI")).strip().upper()
    is_sheet = bool(data.get("length", "").strip())  # sheet if length is provided
    log.info("=== Filling PPGI/PPGL form (division=%s, sheet=%s) ===", division, is_sheet)

    # ── 1. Product Name ──────────────────────────────────────────────────────
    _select_product_name(page, data.get("product_name", ""))
    page.wait_for_timeout(2_500)
    _shot(page, "05_product_name")

    # Dependent Fields section must appear before anything else
    page.wait_for_selector("text=Dependent Fields", timeout=10_000)
    _fix_viewport(page)
    log.info("Dependent Fields loaded OK")
    _shot(page, "06_dependent_fields")

    # ── 2. Customer Order Category ──────────────────────────────────────────
    _select_combobox(page, "Customer Order Category", data.get("customer_order_category", ""))
    page.wait_for_timeout(1_500)
    _shot(page, "07_cust_order_cat")

    # ── 3–6. Cascading specification comboboxes ─────────────────────────────
    # Each selection must be committed and dropdown closed before the next one
    _select_combobox_and_commit(page, "Eq. Specification Group", data.get("eq_specif_grp", ""), wait_after=2_000)
    _shot(page, "08_eq_specif_grp")

    _select_combobox_and_commit(page, "Eq. Specification", data.get("eq_specifi", ""), wait_after=2_000)
    _shot(page, "09_eq_specifi")

    _select_combobox_and_commit(page, "Eq. Sub Specification", data.get("eq_sub_grade", ""), wait_after=1_500)
    _shot(page, "10_eq_sub_grade")

    _select_combobox_and_commit(page, "End Application", data.get("end_appn", ""), wait_after=1_500)
    _shot(page, "11_end_appn")

    # ── 7. Order Quantity ───────────────────────────────────────────────────
    _fill_input(page, "Order Quantity", data.get("order_qty", ""))
    page.wait_for_timeout(800)
    _shot(page, "12_order_qty")

    # ── 8. Customer Requested Date ──────────────────────────────────────────
    _fill_date(page, "Customer Requested Date", data.get("cust_req_date", ""))
    page.wait_for_timeout(1_500)
    _shot(page, "13_cust_req_date")

    # ── 9. Supply Plant / Depot ─────────────────────────────────────────────
    plant_raw  = _normalise_plant(data.get("plant_code", ""))
    plant_code = plant_raw.split()[0].rstrip("-") if plant_raw else ""
    if plant_raw:
        _fill_supply_plant(page, plant_code, plant_raw)
        page.wait_for_timeout(1_500)
        _shot(page, "14_supply_plant")

    # ── 10. S Brand ─────────────────────────────────────────────────────────
    _fill_brand(page, data.get("s_brand", ""))
    page.wait_for_timeout(800)
    _shot(page, "15_s_brand")

    # ── 11–13. Dimensions ───────────────────────────────────────────────────
    _fill_input(page, "Width", data.get("width", ""))
    page.wait_for_timeout(800)
    _shot(page, "16_width")

    _fill_input(page, "Thickness", data.get("thickness", ""))
    page.wait_for_timeout(800)
    _shot(page, "17_thickness")

    if is_sheet:
        _fill_input(page, "Length", data.get("length", ""))
        page.wait_for_timeout(800)
        _shot(page, "18_length")

    # ── 14. Thickness Tolerance Type ────────────────────────────────────────
    if stop_at_tolerance:
        # Open Playwright Inspector so you can manually record how to fill
        # Thickness Tolerance Type, Tolerance Type, and Top Color Code.
        # Resume the script in the inspector (click the ▶ button) when done.
        log.info("=== PAUSED: Playwright Inspector open. Fill Thickness Tolerance Type, "
                 "Tolerance Type, and Top Color Code manually, then click Resume (>) in Inspector. ===")
        page.pause()
        log.info("=== Resumed from Inspector ===")
        _shot(page, "19_after_inspector_resume")
        return ""   # caller should not try to save in stop_at_tolerance mode
    # Direct handler — scroll_into_view_if_needed causes footer-overlay on this field.
    _fill_thick_tol_type_direct(page, data.get("thick_tol_type", ""))
    _shot(page, "19_thick_tol_type")

    # ── 15. Tolerance Type ──────────────────────────────────────────────────
    _fill_tolerance_type_direct(page, data.get("tolerance_type", ""))
    _shot(page, "20_tolerance_type")

    # ── 16. Coating minimum (scroll into view first) ─────────────────────────
    _scroll_form(page, 500)
    page.wait_for_timeout(500)

    if division == "PPGL":
        _fill_input(page, "AL ZN Coating Min(GSM)", data.get("al_zn_coating_min", ""))
        # Try variant label names if the first fails
        if not data.get("al_zn_coating_min"):
            for lbl in ("AL ZN COATING MIN", "AL ZN Coating GSM MIN"):
                _fill_input(page, lbl, data.get("al_zn_coating_min", ""))
    else:
        _fill_zinc_coating_min(page, data.get("zinc_coating_min", ""))
    page.wait_for_timeout(600)
    _shot(page, "21_coating_min")

    # ── 17. Scroll down — Guard Film Required and Top Color Code are lower ───
    _scroll_form(page, 500)
    page.wait_for_timeout(600)
    _shot(page, "22_scroll_other_spec")

    # ── 18. Guard Film Required ──────────────────────────────────────────────
    gfr = _normalise_guard_film(data.get("guard_film_required", ""))
    _scroll_field_into_view(page, "Guard Film Required")
    _select_guard_film_required(page, gfr)
    page.wait_for_timeout(800)
    _shot(page, "23_guard_film")

    # ── 19. Top Color Code ──────────────────────────────────────────────────
    _fill_top_color_code(page, data.get("top_color_code", ""))
    page.wait_for_timeout(800)
    _shot(page, "24_top_color_code")

    # ── 20. PPGL only: Sleeve Required? ─────────────────────────────────────
    if division == "PPGL":
        sleeve = _normalise_yes_no(data.get("sleeve_required", ""))
        if sleeve:
            _select_combobox_and_commit(page, "Sleeve Required?", sleeve, wait_after=600)
            _shot(page, "25_sleeve_required")

    # ── 21. S Plant ─────────────────────────────────────────────────────────
    if plant_raw:
        if stop_at_s_plant:
            log.info("=== PAUSED: Playwright Inspector open at S Plant. Select S Plant manually, then click Resume (>) in Inspector. ===")
            page.pause()
            log.info("=== Resumed from S Plant Inspector pause ===")
            _shot(page, "26_after_s_plant_inspector", full_page=True)
        else:
            _select_s_plant(page, plant_code, plant_raw)
        page.wait_for_timeout(1_200)
        _shot(page, "26_s_plant")

    _shot(page, "27_before_save", full_page=True)
    log.info("All fields filled — ready to Save")

    return _save(page, contract_number, baseline_line)


# ---------------------------------------------------------------------------
# Field helpers — Product Name
# ---------------------------------------------------------------------------

def _select_product_name(page, value: str) -> None:
    if not value:
        return
    log.info("Selecting Product Name: '%s'", value)
    # Find the product name lookup input
    inp = None
    for sel in [
        'input[placeholder="Please Select product"]',
        'input[placeholder*="Select product"]',
        'input[aria-label*="Product Name"]',
    ]:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=2_000):
                inp = loc
                break
        except Exception:
            pass
    if inp is None:
        log.warning("  Product Name input not found")
        return

    inp.scroll_into_view_if_needed(timeout=5_000)
    inp.click(timeout=5_000)
    page.wait_for_timeout(1_000)

    # Scope option lookup to the c-reusable-lookup ancestor if possible
    def _option_scope():
        try:
            ancestor = inp.locator("xpath=ancestor::c-reusable-lookup[1]")
            if ancestor.count():
                s = ancestor.locator('li, [role="option"], lightning-base-combobox-item')
                if s.count():
                    return s
        except Exception:
            pass
        return page.locator('li, [role="option"], lightning-base-combobox-item')

    scope = _option_scope()

    # Strategy 1: exact/near-exact label match
    try:
        scope.filter(has_text=re.compile(re.escape(value), re.IGNORECASE)).first.click(timeout=8_000)
        log.info("  Product Name selected (exact match)")
        return
    except Exception:
        pass

    # Strategy 2: match by material code in parens e.g. (S_PPGISF)
    token_m = re.search(r"\(([^)]+)\)", str(value))
    if token_m:
        token = token_m.group(1).strip()
        try:
            scope.filter(has_text=re.compile(re.escape(token), re.IGNORECASE)).first.click(timeout=8_000)
            log.info("  Product Name selected via token: %s", token)
            return
        except Exception:
            pass

    # Strategy 3: type + Enter
    try:
        inp.fill("")
        inp.type(value[:20], delay=50)
        page.wait_for_timeout(1_200)
        scope = _option_scope()
        scope.filter(has_text=re.compile(re.escape(value), re.IGNORECASE)).first.click(timeout=6_000)
        log.info("  Product Name selected via type+pick")
        return
    except Exception:
        pass

    log.warning("  Could not select Product Name '%s'", value)


# ---------------------------------------------------------------------------
# Field helpers — Combobox (LWC picklist / dropdown)
# ---------------------------------------------------------------------------

def _select_combobox(page, label: str, value: str) -> bool:
    """
    Open a Salesforce LWC combobox by label, find the matching option, click it.
    Returns True if selection was confirmed.

    KEY PATTERN (from Playwright Inspector recording on this form):
      page.get_by_role("combobox", name=label, exact=True).click()
      page.locator("span").filter(has_text=value).first.click()

    LWC combobox options render the clickable text inside a <span> — searching
    [role="option"] misses the actual target because those elements sit inside
    shadow roots. Playwright's locator("span") pierces all shadow roots.
    """
    if not value:
        return False
    log.info("Selecting combobox '%s' = '%s'", label, value)

    # Strategy A: get_by_role(combobox, exact=True) + span.filter click
    # Playwright Inspector recorded pattern for LWC picklist fields.
    # Always use force=True — the modal footer (z-index:20 sticky) can overlay the
    # dropdown options when the combobox is near the bottom of the modal, making them
    # non-actionable without force. Exact regex prevents substring false-matches
    # (e.g. "GE" must not match "LARGE").
    try:
        combo = page.get_by_role("combobox", name=label, exact=True).first
        combo.scroll_into_view_if_needed(timeout=3_000)
        combo.click(timeout=3_000)
        page.wait_for_timeout(500)  # wait for dropdown options to render
        page.locator("span").filter(
            has_text=re.compile(rf"^\s*{re.escape(value)}\s*$", re.IGNORECASE)
        ).first.click(timeout=3_000, force=True)
        log.info("  '%s' selected via get_by_role + span filter", label)
        return True
    except Exception:
        pass

    # Strategy B: native <select> via aria-label
    for sel in [f'select[aria-label="{label}"]', f'select[aria-label*="{label}"]']:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=800):
                loc.select_option(label=value, timeout=3_000)
                log.info("  '%s' selected via aria-label select", label)
                return True
        except Exception:
            pass

    # Strategy C: label[for] → nearest <select>
    try:
        lbl_el = page.locator(f'label:has-text("{label}")').first
        for_id  = lbl_el.get_attribute("for", timeout=1_500)
        if for_id:
            sel_el = page.locator(f"#{for_id}").first
            tag = sel_el.evaluate("el => el.tagName.toLowerCase()", timeout=1_000)
            if tag == "select":
                sel_el.select_option(label=value, timeout=3_000)
                log.info("  '%s' selected via label[for] select", label)
                return True
    except Exception:
        pass

    # Strategy D: JavaScript label-walk to open the combobox button (light DOM only)
    # then span filter to click the option.
    selected = page.evaluate(
        """({ labelText }) => {
            const norm = s => (s || '').replace(/^\\*\\s*/, '').replace(/\\s+/g, ' ').trim().toLowerCase();
            for (const lbl of document.querySelectorAll('label, span.slds-form-element__label')) {
                if (!norm(lbl.textContent).includes(norm(labelText))) continue;
                if (norm(lbl.textContent).length > norm(labelText).length + 4) continue;
                const root = lbl.closest(
                    '.slds-form-element, lightning-layout-item, c-reusable-combobox, div'
                );
                if (!root) continue;
                const btn = root.querySelector('button[aria-haspopup="listbox"], [role="combobox"]');
                if (btn) { btn.click(); return true; }
            }
            return false;
        }""",
        {"labelText": label},
    )
    if selected:
        page.wait_for_timeout(400)
        try:
            page.locator("span").filter(
                has_text=re.compile(rf"^\s*{re.escape(value)}\s*$", re.IGNORECASE)
            ).first.click(timeout=5_000)
            log.info("  '%s' selected via JS open + span filter", label)
            return True
        except Exception:
            pass

    log.warning("  could not select combobox '%s' = '%s'", label, value)
    return False


def _select_combobox_and_commit(
    page, label: str, value: str, wait_after: int = 1_000
) -> bool:
    """
    Select a combobox value, then wait for the DOM to settle.

    IMPORTANT: Do NOT press Escape here. Pressing Escape in a Salesforce modal
    closes the entire modal (not just the open dropdown). Clicking the option
    already closes the dropdown naturally — just wait for the cascade to update.
    """
    result = _select_combobox(page, label, value)
    page.wait_for_timeout(wait_after)
    return result


def _click_visible_dropdown_text(page, value: str, exact: bool = True) -> bool:
    pattern = (
        re.compile(rf"^\s*{re.escape(str(value))}\s*$", re.IGNORECASE)
        if exact
        else re.compile(re.escape(str(value)), re.IGNORECASE)
    )
    for selector in [
        '[role="listbox"] span',
        '[role="option"]',
        '.slds-listbox__item span',
        '.slds-listbox__option span',
        'span',
    ]:
        try:
            page.locator(selector).filter(has_text=pattern).first.click(timeout=4_000, force=True)
            return True
        except Exception:
            pass
    return False


# ---------------------------------------------------------------------------
# Dedicated Thickness Tolerance Type handler — same pattern as Tolerance Type
# ---------------------------------------------------------------------------

def _fill_thick_tol_type_direct(page, value: str) -> bool:
    """
    Thickness Tolerance Type — scroll modal content then click WITHOUT scroll_into_view.

    Two known issues solved here:
    1. ACCESSIBLE NAME MISMATCH: Required fields have an asterisk prefix (* Thickness
       Tolerance Type) so get_by_role(exact=True) cannot find the element.
       Fix: use exact=False (substring match — "Thickness Tolerance Type" is long enough
       to be unambiguous; no other combobox label contains this string).
    2. LWC LAZY RENDERING: LWC only computes aria attributes when the element is
       visible in the viewport. If TTT is below the fold, wait_for(visible) still
       times out even though the element is in the DOM.
       Fix: scroll the MODAL CONTENT AREA (not scroll_into_view_if_needed which
       pushes field to bottom edge behind sticky footer) by a fixed amount first.

    After selection, wait 3 s for the cascade that refreshes Tolerance Type options.
    """
    if not value:
        return False
    log.info("Filling Thickness Tolerance Type = '%s' (direct pattern)", value)

    try:
        _scroll_field_into_view(page, "Thickness Tolerance Type")
        page.get_by_role("combobox", name="Thickness Tolerance Type").click(timeout=4_000, force=True)
        page.wait_for_timeout(500)
        page.locator("span").filter(has_text=value).nth(1).click(timeout=4_000, force=True)
        log.info("  Thickness Tolerance Type = '%s' OK", value)
        page.wait_for_timeout(3_000)   # cascade wait — Tolerance Type renders after this
        return True
    except Exception as e:
        log.warning("  Thickness Tolerance Type direct failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Dedicated Tolerance Type handler — exact Playwright Inspector pattern
# ---------------------------------------------------------------------------

def _fill_tolerance_type_direct(page, value: str) -> bool:
    """
    Tolerance Type — exact two-line Playwright Inspector recording, zero extras.

    Inspector recorded:
        page.get_by_role("combobox", name="Tolerance Type", exact=True).click()
        page.locator("span").filter(has_text="AS_STD").first.click()

    The wrapper _select_combobox must NOT be used here because its
    scroll_into_view_if_needed call pushes the combobox to the bottom of the modal
    and the dropdown options land behind the sticky footer — making them un-clickable.
    """
    if not value:
        return False
    log.info("Filling Tolerance Type = '%s' (direct Inspector pattern)", value)
    try:
        _scroll_field_into_view(page, "Tolerance Type")
        loc = page.get_by_role("combobox", name="Tolerance Type", exact=True)
        loc.wait_for(state="visible", timeout=5_000)
        loc.click(timeout=3_000)
        page.wait_for_timeout(500)
        page.locator("span").filter(has_text=value).nth(2).click(timeout=4_000, force=True)
        log.info("  Tolerance Type = '%s' OK", value)
        page.wait_for_timeout(800)
        return True
    except Exception as e:
        log.warning("  Tolerance Type direct failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Safe dropdown-close helper
# ---------------------------------------------------------------------------

def _close_open_dropdown_safely(page) -> None:
    """
    Close any open LWC combobox dropdown WITHOUT pressing Escape (which closes
    the whole modal) and WITHOUT clicking 'New Contract Line' text (which can
    match the background button behind the modal and close it).

    Strategy: find the button whose aria-expanded is 'true' and click it to
    toggle the listbox closed.  Falls back to clicking the modal header element.
    """
    try:
        closed = page.evaluate("""() => {
            const btn = document.querySelector('button[aria-expanded="true"]');
            if (btn) { btn.click(); return true; }
            return false;
        }""")
        if closed:
            page.wait_for_timeout(200)
            return
    except Exception:
        pass
    # Fallback: click the modal header <h2> (not the background <button>)
    try:
        page.locator("h2.slds-text-heading_medium, .slds-modal__header h2").first.click(
            force=True, timeout=1_000
        )
        page.wait_for_timeout(200)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Guard Film Required — dedicated handler
# ---------------------------------------------------------------------------

def _normalise_guard_film(value: str) -> str:
    """
    Salesforce Guard Film Required picklist has labels/data-values 'Yes', 'No', 'GF_WM', 'WM'.
    Normalise Y/Yes → 'Yes';  N/No → 'No'.  Use the display label, not the API code.
    """
    v = str(value or "").strip().upper()
    if v in {"Y", "YES", "1", "TRUE"}:
        return "Yes"
    if v in {"N", "NO", "0", "FALSE"}:
        return "No"
    return value  # pass through if already correct (e.g. 'GF_WM', 'WM')


def _select_guard_film_required(page, value: str) -> None:
    """
    Guard Film Required picklist.  Playwright Inspector pattern:
        page.get_by_role("combobox", name="Guard Film Required").click()
        page.locator("span").filter(has_text="Yes").first.click()
    """
    if not value:
        return
    log.info("Selecting Guard Film Required = '%s'", value)
    # Delegate to the generic handler which now uses the correct span-filter pattern.
    if _select_combobox(page, "Guard Film Required", value):
        return
    log.warning("  Guard Film Required could not be set to '%s'", value)


# ---------------------------------------------------------------------------
# Top Color Code — dedicated handler (fixes double-fill crash)
# ---------------------------------------------------------------------------

def _fill_top_color_code(page, value: str) -> None:
    """
    Top Color Code — LWC lookup combobox (search-and-select).

    Playwright Inspector recorded pattern:
        page.get_by_role("combobox", name="Top Color Code").click()
        page.get_by_role("combobox", name="Top Color Code").fill("JSWA034S")
        page.get_by_text("JSWA034SRMP_BLUE_ULTRAMARINE").click()   # first match
    """
    if not value:
        return
    log.info("Filling Top Color Code: '%s'", value)

    # ── Close any lingering open dropdown safely ──────────────────────────────
    _close_open_dropdown_safely(page)

    # ── Open and fill the combobox ────────────────────────────────────────────
    try:
        _scroll_field_into_view(page, "Top Color Code")
        combo = page.get_by_role("combobox", name="Top Color Code", exact=True).first
        if not combo.is_visible(timeout=2_000):
            combo = page.get_by_role("combobox", name="Top Color Code").first
        combo.click(timeout=4_000)
        page.wait_for_timeout(300)
        try:
            combo.press("CapsLock")
        except Exception:
            pass
        combo.fill(str(value).strip())
        log.info("  Top Color Code typed: '%s'", value)
    except Exception as e:
        log.warning("  Could not open/fill Top Color Code combobox: %s", e)
        return

    # Wait for Salesforce to query and render results
    page.wait_for_timeout(2_000)

    # ── Select matching option from the dropdown ─────────────────────────────────
    # Inspector recorded: page.get_by_text("JSWA034SRMP_BLUE_ULTRAMARINE").click()
    # The option text = colorCode + description concatenated.
    # Try [role="option"] first — lookup fields render options in the main DOM
    # (unlike LWC picklists which use shadow DOM — those need span.filter).
    # Do NOT fall back to ArrowDown+Enter — Enter opens a blank new block here.

    exact_dropdown_texts = []
    if str(value).strip().upper() == "JSWA034S":
        exact_dropdown_texts.append("JSWA034SRMP_BLUE_ULTRAMARINE")
    if str(value).strip().upper() == "JSWV343S00":
        exact_dropdown_texts.append("JSWV343S00WHITE DEEP REF")

    for text in exact_dropdown_texts:
        try:
            page.get_by_text(text, exact=False).first.click(timeout=5_000, force=True)
            log.info("  Top Color Code selected via exact dropdown text: '%s'", text)
            return
        except Exception:
            pass

    try:
        page.locator('lightning-base-combobox-item, [role="option"], li.slds-listbox__item, .slds-listbox__item').filter(
            has_text=re.compile(r"^\s*" + re.escape(value), re.IGNORECASE)
        ).first.click(timeout=4_000, force=True)
        log.info("  Top Color Code selected via dropdown row prefix: '%s'", value)
        return
    except Exception:
        pass

    try:
        page.locator('[role="listbox"] [role="option"], [role="listbox"] span, .slds-listbox__item span').filter(
            has_text=re.compile(re.escape(value), re.IGNORECASE)
        ).first.click(timeout=4_000, force=True)
        log.info("  Top Color Code selected via dropdown fallback: '%s'", value)
        return
    except Exception:
        pass

    log.warning("  Top Color Code option '%s' not found — left unfilled. "
                "Do NOT use ArrowDown+Enter (opens blank block).", value)


# ---------------------------------------------------------------------------
# Field helpers — numeric inputs
# ---------------------------------------------------------------------------

def _fill_input(page, label: str, value: str) -> None:
    """Fill a plain text/number input by label."""
    if not value:
        return
    log.info("Filling input '%s' = '%s'", label, value)

    for sel in [f'input[aria-label="{label}"]', f'input[aria-label*="{label}"]']:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=1_500):
                loc.scroll_into_view_if_needed()
                loc.fill(value)
                log.info("  filled via aria-label")
                return
        except Exception:
            pass

    try:
        lbl_el = page.locator(f'label:has-text("{label}")').first
        for_id  = lbl_el.get_attribute("for", timeout=2_000)
        if for_id:
            page.locator(f"input#{for_id}").fill(value)
            log.info("  filled via label[for]")
            return
    except Exception:
        pass

    try:
        inp = page.locator(f'label:has-text("{label}")').first.locator(
            "xpath=following-sibling::div[1]//input | following-sibling::*[1]//input"
        )
        if inp.count():
            inp.first.scroll_into_view_if_needed()
            inp.first.fill(value)
            log.info("  filled via label sibling")
            return
    except Exception:
        pass

    log.warning("  could not fill input '%s'", label)


# ---------------------------------------------------------------------------
# Zin_Coating Min — special handler (field label varies, value clears on blur)
# ---------------------------------------------------------------------------

def _fill_zinc_coating_min(page, value: str) -> None:
    """
    Fill Zin_Coating Min(GSM).
    Uses click(click_count=3) to select-all before filling, then Tab to commit.
    """
    if not value:
        return
    log.info("Filling Zin_Coating Min(GSM) = '%s'", value)

    for label in ("Zin_Coating Min(GSM)", "Zin Coating Min GSM", "ZIN_COATING MIN(GSM)"):
        # Try aria-label first
        for sel in [f'input[aria-label="{label}"]', f'input[aria-label*="{label}"]']:
            try:
                loc = page.locator(sel).first
                if not loc.is_visible(timeout=800):
                    continue
                loc.scroll_into_view_if_needed()
                loc.click(click_count=3, timeout=2_000)   # select-all
                loc.fill(value)
                page.wait_for_timeout(300)
                loc.press("Tab")   # commit without closing modal
                log.info("  Zin_Coating Min filled via aria-label '%s'", sel)
                return
            except Exception:
                pass
        # label[for]
        try:
            lbl_el = page.locator(f'label:has-text("{label}")').first
            if not lbl_el.is_visible(timeout=600):
                continue
            for_id = lbl_el.get_attribute("for", timeout=1_000)
            if for_id:
                inp = page.locator(f"input#{for_id}")
                inp.scroll_into_view_if_needed()
                inp.click(click_count=3, timeout=2_000)   # select-all
                inp.fill(value)
                page.wait_for_timeout(300)
                inp.press("Tab")
                log.info("  Zin_Coating Min filled via label[for] '%s'", label)
                return
        except Exception:
            pass

    # Final fallback: plain fill (same as _fill_input)
    _fill_input(page, "Zin_Coating Min(GSM)", value)
    log.warning("  Zin_Coating Min used plain fill fallback")


# ---------------------------------------------------------------------------
# Field helpers — date
# ---------------------------------------------------------------------------

def _fill_date(page, label: str, value: str) -> None:
    """Fill a date input field. Value in DD/MM/YYYY format."""
    if not value:
        return
    log.info("Filling date '%s' = '%s'", label, value)

    def _type_date(inp):
        inp.scroll_into_view_if_needed(timeout=3_000)
        inp.click(timeout=3_000)
        page.wait_for_timeout(400)
        inp.click(click_count=3)
        page.keyboard.press("Delete")
        inp.press_sequentially(value, delay=80)
        page.wait_for_timeout(400)
        page.keyboard.press("Tab")

    for sel in [f'input[aria-label="{label}"]', f'input[aria-label*="{label}"]']:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=1_500):
                _type_date(loc)
                log.info("  date filled via aria-label")
                return
        except Exception:
            pass

    try:
        lbl_el = page.locator(f'label:has-text("{label}")').first
        for_id  = lbl_el.get_attribute("for", timeout=2_000)
        if for_id:
            _type_date(page.locator(f"input#{for_id}"))
            log.info("  date filled via label[for]")
            return
    except Exception:
        pass

    log.warning("  could not fill date '%s'", label)


# ---------------------------------------------------------------------------
# Field helpers — S Brand (lookup)
# ---------------------------------------------------------------------------

def _fill_brand(page, value: str) -> None:
    """Fill S Brand via its lookup combobox (placeholder: 'Select Brand')."""
    if not value:
        return
    log.info("Filling S Brand = '%s'", value)
    try:
        inp = page.get_by_role(
            "textbox", name=re.compile(r"Select Brand", re.IGNORECASE)
        ).first
        inp.scroll_into_view_if_needed(timeout=4_000)
        inp.click(timeout=4_000, force=True)
        page.wait_for_timeout(300)
        # Brand options appear immediately — click exact match
        page.locator("span").filter(
            has_text=re.compile(rf"^\s*{re.escape(value)}\s*$", re.IGNORECASE)
        ).first.click(timeout=5_000)
        log.info("  S Brand selected: '%s'", value)
        return
    except Exception:
        pass

    # Fallback: type + pick from dropdown
    try:
        inp = page.locator(
            'input[placeholder*="Select Brand"], input[placeholder*="Brand"], '
            'input[aria-label*="Brand"]'
        ).first
        inp.scroll_into_view_if_needed(timeout=4_000)
        inp.click(timeout=4_000, force=True)
        inp.fill(str(value))
        page.wait_for_timeout(1_000)
        page.locator('li, [role="option"], lightning-base-combobox-item').filter(
            has_text=re.compile(re.escape(value), re.IGNORECASE)
        ).first.click(timeout=4_000, force=True)
        log.info("  S Brand selected via type+pick fallback")
    except Exception as e:
        log.warning("  Could not fill S Brand: %s", e)


# ---------------------------------------------------------------------------
# Field helpers — Supply Plant / Depot (lookup)
# ---------------------------------------------------------------------------

def _normalise_plant(raw: str) -> str:
    """Resolve a plant_code like '1044' or '1044 - JSCPL - DHAR' to a clean display name."""
    PLANT_MAP = {
        "1001": "1001 - Vijayanagar Works",
        "1014": "1014 - Tarapur Works",
        "1018": "1018 - Kalmeshwar Works",
        "1044": "1044 - JSCPL - DHAR",
    }
    raw = str(raw or "").strip()
    if not raw:
        return ""
    # If it looks like just a code, look it up
    if re.match(r"^\d{4}$", raw):
        return PLANT_MAP.get(raw, raw)
    return raw


def _supply_plant_lookup_modal_open(page) -> bool:
    """Return True if the Supply Plant / Depot lookup sub-modal is still visible."""
    try:
        return page.locator('text=JSW Locations').first.is_visible(timeout=700)
    except Exception:
        return False


def _wait_supply_plant_lookup_closed(page, timeout_ms: int = 12_000) -> bool:
    """Poll until the Supply Plant lookup modal closes. Return True when closed."""
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        if not _supply_plant_lookup_modal_open(page):
            return True
        page.wait_for_timeout(500)
    return not _supply_plant_lookup_modal_open(page)


def _save_supply_plant_lookup_modal(page) -> bool:
    """
    Click the Save button inside the Supply Plant / Depot lookup sub-modal.
    The modal has Cancel | Save buttons at the bottom — clicking Save confirms
    the selected row and closes the modal.
    """
    # Try JS click on the Save button inside the modal
    try:
        clicked = page.evaluate(
            """() => {
                const modals = document.querySelectorAll('.modal-container, .slds-modal__container');
                for (const m of modals) {
                    const text = (m.innerText || m.textContent || '').toLowerCase();
                    if (!text.includes('jsw locations') && !text.includes('supply plant')) continue;
                    const btns = Array.from(m.querySelectorAll('button'));
                    const saveBtn = btns.find(b => (b.innerText || b.textContent || '').trim().toLowerCase() === 'save');
                    if (saveBtn) { saveBtn.click(); return true; }
                }
                return false;
            }"""
        )
        if clicked and _wait_supply_plant_lookup_closed(page):
            return True
    except Exception:
        pass
    # Playwright click fallback
    try:
        modal = page.locator(".modal-container, .slds-modal__container").filter(
            has_text=re.compile(r"Supply Plant\s*/\s*Depot|JSW Locations", re.IGNORECASE)
        ).last
        btn = modal.locator('button:has-text("Save")').last
        btn.scroll_into_view_if_needed(timeout=2_000)
        btn.click(timeout=5_000, force=True)
        return _wait_supply_plant_lookup_closed(page)
    except Exception:
        return False


def _select_supply_plant_result(page, plant_code: str, plant_raw: str = "") -> bool:
    """
    Select the exact Supply Plant result from the JSW Locations lookup modal.

    The modal shows a table:  DESCRIPTION (link) | CODE | TYPE
    We must click the <a> link in the DESCRIPTION column — NOT the CODE text.
    After clicking we verify the modal actually closed; if not, click its Save button.
    """
    plant_keyword = _plant_keyword(plant_raw or plant_code)
    code = str(plant_code or "").strip()

    # Strategy 1: Find table row by code or keyword, click its <a> description link
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
                # Modal still open — try its Save button
                if _save_supply_plant_lookup_modal(page):
                    return True
        except Exception:
            pass

    # Strategy 2: JS — find row by code/keyword, click its description <a>
    try:
        selected = page.evaluate(
            """({ code, keyword }) => {
                const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                const lower = (s) => norm(s).toLowerCase();
                for (const row of document.querySelectorAll('table tbody tr')) {
                    const cells = Array.from(row.querySelectorAll('td'));
                    if (!cells.length) continue;
                    const rowCode = cells.length > 1 ? norm(cells[1].innerText || cells[1].textContent) : '';
                    const rowText = lower(row.innerText || row.textContent);
                    const codeMatch = code && rowCode === norm(code);
                    const keyMatch  = keyword && rowText.includes(lower(keyword));
                    if (codeMatch || keyMatch) {
                        const link = cells[0].querySelector('a') || row.querySelector('a');
                        if (link) { link.click(); return true; }
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

    # Strategy 3: Broad <a> filter by keyword
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

    return False


def _fill_supply_plant(page, plant_code: str, plant_raw: str = "") -> None:
    """
    Fill Supply Plant / Depot lookup.

    CONFIRMED WORKING APPROACH (ported from salesforce_add_contract_line.py):
    1. Fill the input with plant_code ("1044")
    2. Wait 1.2 s for inline suggestion OR the lookup sub-modal to open
    3. Try inline suggestion (li/[role=option]) — if found and modal closed → done
    4. Try "Show more results" to open the full lookup modal
    5. _select_supply_plant_result: find table row → click <a> description link →
       verify modal closed (via _wait_supply_plant_lookup_closed)
    6. If modal still open, _save_supply_plant_lookup_modal clicks the modal's Save btn
    7. Fallback: click first table link

    CRITICAL LESSONS:
    • Use 'table a' / row.locator('a') — NOT span.filter.
      span.filter(has_text="1044") hits the CODE column plain text, not the
      DESCRIPTION link → modal stays open → blocks all subsequent form fields.
    • Always verify the modal closed after clicking — use _wait_supply_plant_lookup_closed.
    • The modal has a Save button (bottom right) as a guaranteed close mechanism.
    """
    if not plant_code and not plant_raw:
        return
    log.info("Filling Supply Plant: '%s'", plant_raw or plant_code)
    try:
        inp = page.locator(
            'input[placeholder*="JSW Locations"], '
            'input[placeholder*="Supply Plant"], '
            'input[placeholder*="Depot"]'
        ).first
        if not inp.is_visible(timeout=3_000):
            inp = page.locator('input[aria-label*="Supply Plant"]').first
        inp.scroll_into_view_if_needed(timeout=5_000)
        inp.click(timeout=5_000)
        page.wait_for_timeout(500)
        inp.fill(plant_code)
        page.wait_for_timeout(1_200)

        # ── Try inline suggestion (li / [role="option"]) ─────────────────────────
        # NOTE: clicking the inline suggestion often opens the full JSW Locations
        # lookup modal rather than selecting directly. We MUST wait 1.5 s after the
        # click before checking — the modal takes ~1 s to render, so a 700 ms check
        # returns False (not open yet) and we incorrectly assume "selected", exit the
        # function, and the modal appears a second later blocking all subsequent fields.
        plant_keyword = _plant_keyword(plant_raw or plant_code)
        for kw in ([plant_keyword] if plant_keyword else []):
            try:
                page.locator('li, [role="option"], lightning-base-combobox-item').filter(
                    has_text=re.compile(re.escape(kw), re.IGNORECASE)
                ).first.click(timeout=2_000)
                page.wait_for_timeout(1_500)   # wait for modal to render if triggered
                if not _supply_plant_lookup_modal_open(page):
                    log.info("  Supply Plant selected from inline suggestion: '%s'", kw)
                    return
                log.info("  Supply Plant lookup opened full results; selecting row")
                break
            except Exception:
                pass

        # ── "Show more results" to open full lookup modal ─────────────────────────
        for text in [f'Show more results for "{plant_code}"', "Show more results"]:
            try:
                page.locator(f'text={text}').first.click(timeout=3_000)
                page.wait_for_timeout(2_000)
                break
            except Exception:
                pass

        # ── Select from the lookup modal table ────────────────────────────────────
        if _select_supply_plant_result(page, plant_code, plant_raw):
            log.info("  Supply Plant selected via table result")
            return

        # ── Last resort: click first table link ───────────────────────────────────
        try:
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
            return
        except Exception as e2:
            log.warning("  Supply Plant last-resort failed: %s", e2)

    except Exception as e:
        log.warning("  Supply Plant failed: %s", e)
    finally:
        # If the lookup modal is still open for any reason, close it so it doesn't
        # block all subsequent form fields (TTT, Tolerance Type, Guard Film, etc.)
        # Wait 1 s first — the modal may still be rendering after the last click.
        page.wait_for_timeout(1_000)
        if _supply_plant_lookup_modal_open(page):
            log.warning("  Supply Plant modal still open — force-closing.")
            _save_supply_plant_lookup_modal(page)
            if _supply_plant_lookup_modal_open(page):
                for close_sel in ['button[title="Cancel"]', 'button:has-text("Cancel")',
                                   '.slds-modal__close', 'button[aria-label="Close"]']:
                    try:
                        btn = page.locator(close_sel).last
                        if btn.is_visible(timeout=600):
                            btn.click(timeout=1_500)
                            page.wait_for_timeout(400)
                            break
                    except Exception:
                        pass


def _plant_keyword(plant_raw: str) -> str:
    """Extract a short memorable keyword from plant name, e.g. 'DHAR' from '1044 - JSCPL - DHAR'."""
    parts = re.split(r"\s*-\s*", str(plant_raw or ""), maxsplit=2)
    # Return the last meaningful segment
    for part in reversed(parts):
        word = part.strip().split()[0] if part.strip() else ""
        if word and word.upper() not in {"JSW", "JSWSTEEL"}:
            return word
    return parts[-1].strip() if parts else plant_raw


# ---------------------------------------------------------------------------
# Field helpers — S Plant (combobox)
# ---------------------------------------------------------------------------

def _select_s_plant(page, plant_code: str, plant_raw: str = "") -> None:
    """
    Select S Plant combobox.

    Playwright Inspector recorded pattern:
        page.get_by_role("combobox", name="S Plant").click()
        page.locator("span").filter(has_text="JSCPL - DHAR").first.click()
    """
    if not plant_code and not plant_raw:
        return
    log.info("Selecting S Plant: '%s'", plant_raw or plant_code)

    # Scroll Plant Description section into view first
    try:
        _scroll_field_into_view(page, "S Plant")
        page.wait_for_timeout(500)
    except Exception:
        pass

    # Build keyword candidates from most-specific to least.
    # Inspector showed option text is e.g. "JSCPL – DHAR" so include "JSCPL" too.
    parts = re.split(r"\s*[-–]\s*", str(plant_raw or ""), maxsplit=2)
    plant_name = parts[-1].strip() if len(parts) > 1 else plant_raw
    middle     = parts[1].strip() if len(parts) > 2 else ""   # e.g. "JSCPL"
    keyword    = plant_name.split()[0] if plant_name else ""
    candidates = []
    for c in [plant_code, keyword, plant_name, middle, plant_raw]:
        c = str(c or "").strip()
        if c and c not in candidates:
            candidates.append(c)
    log.info("  S Plant candidates: %s", candidates)

    def _click_s_plant_candidate() -> bool:
        option_candidates = []
        for c in [plant_name, middle, keyword, plant_code, plant_raw, "Kalmeshwar Works"]:
            c = str(c or "").strip()
            if c and c not in option_candidates:
                option_candidates.append(c)
        for candidate in option_candidates:
            try:
                page.locator(
                    'lightning-base-combobox-item, [role="option"], '
                    '.slds-listbox__item, span'
                ).filter(
                    has_text=re.compile(re.escape(candidate), re.IGNORECASE)
                ).first.click(timeout=4_000, force=True)
                log.info("  S Plant selected via dropdown candidate: '%s'", candidate)
                return True
            except Exception:
                pass
        return False

    # Label-walk opener: avoids matching the earlier "Supply Plant / Depot" lookup.
    try:
        opened = page.evaluate("""() => {
            const norm = (s) => (s || '').replace(/^\\*\\s*/, '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const labels = Array.from(document.querySelectorAll('label, span.slds-form-element__label, .slds-form-element__label'));
            const label = labels.find((el) => norm(el.innerText || el.textContent) === 's plant');
            if (!label) return false;
            const root = label.closest('.slds-form-element, lightning-layout-item, .slds-col, div');
            if (!root) return false;
            const combo = root.querySelector('button[aria-haspopup="listbox"], [role="combobox"], button');
            if (!combo) return false;
            combo.click();
            return true;
        }""")
        if opened:
            page.wait_for_timeout(600)
            if _click_s_plant_candidate():
                return
    except Exception:
        pass

    # Open via get_by_role (Inspector-confirmed — no exact=True, no scroll_into_view).
    # scroll_into_view_if_needed causes the same footer-overlay problem as Tolerance Type.
    # force=True on span click: needed because the dropdown animates open and the span
    # may not pass Playwright's visibility check during animation.
    try:
        s_plant_name = re.compile(r"^\*?\s*S Plant\s*$", re.IGNORECASE)
        page.get_by_role("combobox", name=s_plant_name).click(timeout=4_000, force=True)
        page.wait_for_timeout(500)
        if _click_s_plant_candidate():
            return
    except Exception:
        pass

    # Fallback: native <select>
    for sel in ['select[aria-label="S Plant"]', 'select[aria-label*="S Plant"]']:
        try:
            loc = page.locator(sel).first
            if not loc.is_visible(timeout=800):
                continue
            options = loc.locator("option").all_inner_texts()
            match = next(
                (o for o in options if any(c.lower() in o.lower() for c in candidates)),
                None,
            )
            if match:
                loc.select_option(label=match)
                log.info("  S Plant selected via <select>: '%s'", match)
                return
        except Exception:
            pass

    log.warning("  S Plant could not be selected for candidates: %s", candidates)


# ---------------------------------------------------------------------------
# Field helpers — Scroll
# ---------------------------------------------------------------------------

def _scroll_modal_content(page, delta_y: int = 400) -> None:
    """
    Scroll the MODAL CONTENT AREA (not the whole page) by delta_y pixels.

    Use this instead of scroll_into_view_if_needed for fields near the bottom
    of the modal — scroll_into_view_if_needed pushes the element to the very
    bottom edge, where the sticky modal footer (z-index:20) overlays the
    open dropdown and makes options un-clickable.

    Scrolling the modal's own scrollable div brings the field into view without
    touching the sticky footer position.
    """
    try:
        page.evaluate("""(dy) => {
            const sel = '.slds-modal__content, .modal-body, .slds-modal__container';
            const el = document.querySelector(sel);
            if (el) el.scrollBy(0, dy);
        }""", delta_y)
    except Exception:
        pass


def _scroll_field_into_view(page, label: str) -> bool:
    """
    Bring a labelled field into the visible middle of the Salesforce modal.

    Headless Cloud Run does not always scroll the modal when Playwright calls
    scroll_into_view_if_needed on LWC comboboxes. Moving the modal content by
    label first makes lower PPGI fields visible before we click them.
    """
    try:
        found = page.evaluate(
            """(labelText) => {
                const norm = (s) => (s || '')
                    .replace(/^\\*\\s*/, '')
                    .replace(/\\s+/g, ' ')
                    .trim()
                    .toLowerCase();
                const wanted = norm(labelText);
                const labels = Array.from(document.querySelectorAll(
                    'label, span.slds-form-element__label, .slds-form-element__label'
                ));
                const label = labels.find((el) => {
                    const text = norm(el.innerText || el.textContent);
                    return text === wanted || text.includes(wanted);
                });
                if (!label) return false;
                const target = label.closest('.slds-form-element, lightning-layout-item, .slds-col, div') || label;
                const scroller = target.closest('.slds-modal__content, .modal-body') ||
                    document.querySelector('.slds-modal__content, .modal-body');
                if (scroller) {
                    const tr = target.getBoundingClientRect();
                    const sr = scroller.getBoundingClientRect();
                    scroller.scrollTop += tr.top - sr.top - Math.max(80, scroller.clientHeight * 0.35);
                } else {
                    target.scrollIntoView({ block: 'center', inline: 'nearest' });
                }
                return true;
            }""",
            label,
        )
        page.wait_for_timeout(500)
        return bool(found)
    except Exception:
        return False


def _scroll_form(page, delta_y: int = 500) -> None:
    _scroll_modal_content(page, delta_y)
    try:
        page.mouse.wheel(0, delta_y)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Normalise helpers
# ---------------------------------------------------------------------------

def _normalise_yes_no(value: str) -> str:
    v = str(value or "").strip().upper()
    if v in {"Y", "YES", "1", "TRUE"}:
        return "Yes"
    if v in {"N", "NO", "0", "FALSE"}:
        return "No"
    return value


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def _save(page, contract_number: str = "", baseline_line: str = "") -> str:
    """Click Save, wait for Salesforce to redirect, return the contract line name."""
    _fix_viewport(page)
    log.info("Clicking Save …")
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
    save_btn.click(timeout=15_000, force=True)
    page.wait_for_timeout(10_000)
    _shot(page, "30_after_save")

    # Check for validation errors
    save_error = _extract_save_error(page)
    if save_error:
        log.warning("Save rejected: %s", save_error)
        _shot(page, "31_save_error", full_page=True)
        raise RuntimeError(save_error)

    log.info("Save successful. URL: %s", page.url)

    # Extract the line name (e.g. '00179274_30')
    line_name = _extract_line_name(page, contract_number, baseline_line)
    if line_name:
        log.info("Contract line created: %s", line_name)
    else:
        log.warning("Could not read contract line name from page")
        raise RuntimeError("Contract line name was not captured after Save.")
    return line_name


def _extract_save_error(page) -> str:
    messages = []
    for sel in ['[role="alert"]', '.slds-notify_toast', '.slds-form-element__help', '.slds-has-error']:
        try:
            for text in page.locator(sel).all_inner_texts(timeout=1_000):
                text = " ".join(str(text or "").split())
                if text and text not in messages:
                    messages.append(text)
        except Exception:
            pass
    try:
        body = page.inner_text("body", timeout=2_000)
        for pat in (r"Error!\s*([^\n]+)", r"Complete this field\.?", r"Review the errors"):
            m = re.search(pat, body, re.IGNORECASE)
            if m:
                t = " ".join(m.group(0).split())
                if t not in messages:
                    messages.append(t)
    except Exception:
        pass
    return " | ".join(messages[:8])[:700]


def _extract_line_name(page, contract_number: str, baseline_line: str) -> str:
    """Try multiple strategies to read the newly-created contract line name."""
    line_name = ""

    # 1. Page heading
    for sel in ['h1 .slds-page-header__title', '.slds-page-header__title', 'h1']:
        try:
            for el in page.locator(sel).all():
                text = el.inner_text(timeout=1_000).strip()
                if re.match(r"\d{7,9}_\d+", text):
                    line_name = text
        except Exception:
            pass
        if line_name:
            break

    # 2. Full body text scan
    if not line_name:
        try:
            body = page.inner_text("body", timeout=3_000)
            matches = re.findall(r"\b(\d{7,9}_\d+)\b", body)
            if matches:
                line_name = max(matches, key=lambda x: int(x.split("_")[1]))
        except Exception:
            pass

    # 3. Related tab fallback
    if not line_name and contract_number:
        line_name = _latest_contract_line(page, contract_number)

    # Validate it's newer than baseline
    if line_name and baseline_line:
        baseline_idx = _line_index(baseline_line)
        created_idx  = _line_index(line_name)
        if baseline_idx and created_idx and created_idx <= baseline_idx:
            # Retry with reloads
            for attempt in range(1, 6):
                try:
                    page.wait_for_timeout(4_000 if attempt < 3 else 8_000)
                    page.reload(wait_until="domcontentloaded", timeout=25_000)
                    page.wait_for_timeout(2_500)
                except Exception:
                    pass
                retried = _latest_contract_line(page, contract_number)
                if _line_index(retried) > baseline_idx:
                    line_name = retried
                    break
            if _line_index(line_name) <= baseline_idx:
                raise RuntimeError(
                    f"No NEW contract line was created for {contract_number}. "
                    f"Latest is still {line_name}."
                )

    return line_name


def _latest_contract_line(page, contract_number: str) -> str:
    """Open Related tab and return the highest-indexed contract line name."""
    try:
        page.locator("a, button, span").filter(
            has_text=re.compile(r"^Related$", re.IGNORECASE)
        ).first.click(timeout=10_000, force=True)
        page.wait_for_timeout(5_000)
        _shot(page, "related_tab", full_page=True)
        body = page.inner_text("body", timeout=5_000)
        candidates = re.findall(rf"\b({re.escape(contract_number)}_\d+)\b", body)
        if candidates:
            return max(set(candidates), key=lambda x: int(x.split("_")[1]))
    except Exception as exc:
        log.warning("Related tab fallback failed: %s", exc)
    return ""


def _line_index(line_name: str) -> int:
    m = re.match(r"^\d{7,9}_(\d+)$", str(line_name or "").strip())
    return int(m.group(1)) if m else 0


# ---------------------------------------------------------------------------
# Screenshot helper
# ---------------------------------------------------------------------------

def _shot(page, name: str, full_page: bool = False) -> None:
    path = os.path.join(DEBUG_DIR, f"ppgi_{name}.png")
    try:
        page.screenshot(path=path, full_page=full_page)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Create a PPGI/PPGL SKU contract line in Salesforce.")
    parser.add_argument("--contract", required=False, help="Contract number, e.g. 00179274")
    parser.add_argument(
        "--mode",
        choices=["create", "open"],
        default="open",
        help="'create' fills and saves a new line; 'open' just opens the contract (default).",
    )
    parser.add_argument(
        "--sample",
        choices=list(SAMPLES.keys()),
        default="ppgi-sheet",
        help="Built-in sample data to use when --mode create. Default: ppgi-sheet.",
    )
    parser.add_argument(
        "--pause",
        type=int,
        default=300,
        help="Seconds to keep browser open after create. Default: 300.",
    )
    # Individual field overrides
    parser.add_argument("--product-name",    help="Override product_name")
    parser.add_argument("--qty",             help="Override order_qty")
    parser.add_argument("--width",           help="Override width")
    parser.add_argument("--thickness",       help="Override thickness")
    parser.add_argument("--length",          help="Override length (sheet) or '' for coil")
    parser.add_argument("--zinc-coating",    help="Override zinc_coating_min")
    parser.add_argument("--al-zn-coating",   help="Override al_zn_coating_min (PPGL)")
    parser.add_argument("--guard-film",      help="Override guard_film_required (Y/N)")
    parser.add_argument("--top-color-code",  help="Override top_color_code")
    parser.add_argument("--plant",           help="Override plant_code")
    parser.add_argument("--cust-req-date",   help="Override cust_req_date (DD/MM/YYYY)")
    parser.add_argument("--eq-spec-grp",     help="Override eq_specif_grp")
    parser.add_argument("--eq-specifi",      help="Override eq_specifi")
    parser.add_argument("--eq-sub-grade",    help="Override eq_sub_grade")
    parser.add_argument(
        "--stop-at-tolerance",
        action="store_true",
        help=(
            "Fill all fields up to (but not including) Thickness Tolerance Type, "
            "then open Playwright Inspector so you can manually record how those fields work. "
            "No Save is performed."
        ),
    )
    parser.add_argument(
        "--stop-at-s-plant",
        action="store_true",
        help=(
            "Fill all fields up to S Plant, then open Playwright Inspector so the "
            "S Plant dropdown can be selected manually. Save continues after Resume."
        ),
    )

    args = parser.parse_args()

    if not args.contract:
        parser.error("--contract is required")

    contract = args.contract.upper().strip()

    if args.mode == "open":
        os.makedirs(DEBUG_DIR, exist_ok=True)
        with sync_playwright() as p:
            browser = _launch_browser(p, headed=True)
            page    = _new_page(browser)
            try:
                _login(page)
                _search_and_open_contract(page, contract)
                log.info("Contract %s open. Browser will close in %ss.", contract, args.pause)
                if args.pause > 0:
                    time.sleep(args.pause)
            finally:
                browser.close()
        return

    # --mode create
    data = dict(SAMPLES[args.sample])  # start from sample, apply overrides
    overrides = {
        "product_name":       args.product_name,
        "order_qty":          args.qty,
        "width":              args.width,
        "thickness":          args.thickness,
        "length":             args.length,
        "zinc_coating_min":   args.zinc_coating,
        "al_zn_coating_min":  args.al_zn_coating,
        "guard_film_required": args.guard_film,
        "top_color_code":     args.top_color_code,
        "plant_code":         args.plant,
        "cust_req_date":      args.cust_req_date,
        "eq_specif_grp":      args.eq_spec_grp,
        "eq_specifi":         args.eq_specifi,
        "eq_sub_grade":       args.eq_sub_grade,
    }
    for k, v in overrides.items():
        if v is not None:
            data[k] = v

    line_name = add_ppgi_contract_line_for_training(
        contract, data,
        pause_seconds=args.pause,
        stop_at_tolerance=args.stop_at_tolerance,
        stop_at_s_plant=args.stop_at_s_plant,
    )
    print(f"\nResult: {line_name}")


if __name__ == "__main__":
    main()
