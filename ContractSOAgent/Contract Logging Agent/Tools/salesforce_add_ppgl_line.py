"""
Tool: salesforce_add_ppgl_line.py
Purpose: Create a PPGL SKU contract line item in the JSW One Salesforce portal.

==============================================================================
PPGL-ONLY standalone script.
PPGI is already complete and fully tested -- do NOT modify salesforce_add_ppgi_line.py
for PPGL issues. All fixes and test iterations live here.
==============================================================================

Imports all proven helpers from salesforce_add_ppgi_line.py (shared Playwright
patterns: login, navigation, comboboxes, supply plant modal, TTT, tolerance type,
guard film, top color code, S plant, save).

The only PPGL-specific difference vs PPGI:
  * Uses "AL ZN Coating Min(GSM)" field instead of "Zin_Coating Min(GSM)"
  * No division branching -- this file is PPGL-only

PPGL form fields (in order):
  Product Name -> Customer Order Category -> Eq. Spec Group -> Eq. Specification ->
  Eq. Sub Specification -> End Application -> Order Quantity -> Customer Requested Date ->
  Supply Plant / Depot -> S Brand -> Width -> Thickness -> Length (sheet only) ->
  Thickness Tolerance Type -> Tolerance Type -> AL ZN Coating Min(GSM) ->
  Guard Film Required -> Top Color Code -> [Sleeve Required?] -> S Plant

Usage (local training / debug run):
    cd ".../Contract Logging Agent/Tools"

    # Quick create from built-in sample
    python salesforce_add_ppgl_line.py --contract 00180047 --mode create --sample ppgl-sheet --pause 120

    # Just open the contract (no form fill)
    python salesforce_add_ppgl_line.py --contract 00180047 --mode open

    # Pause before Thickness Tolerance Type so you can use Playwright Inspector
    python salesforce_add_ppgl_line.py --contract 00180047 --mode create --stop-at-tolerance --pause 0
"""

import os
import re
import sys
import time
import logging
import argparse

from playwright.sync_api import sync_playwright
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

BASE_URL  = "https://jswsteel.my.site.com"
DEBUG_DIR = os.path.join("C:\\tmp" if os.name == "nt" else "/tmp", "sf_ppgl_debug")
PORTAL_VP = {"width": 1920, "height": 1080}

# ---------------------------------------------------------------------------
# Import all tested helpers from PPGI module
# PPGI is complete -- we reuse its proven Playwright patterns unchanged.
# ---------------------------------------------------------------------------

from salesforce_add_ppgi_line import (  # noqa: E402
    _launch_browser,
    _new_page,
    _fix_viewport,
    _login,
    _search_and_open_contract,
    _click_new_contract_line,
    _select_product_name,
    _select_combobox,
    _select_combobox_and_commit,
    _fill_input,
    _fill_date,
    _fill_brand,
    _fill_supply_plant,
    _fill_thick_tol_type_direct,
    _fill_tolerance_type_direct,
    _close_open_dropdown_safely,
    _normalise_guard_film,
    _select_guard_film_required,
    _fill_top_color_code,
    _select_s_plant,
    _save,
    _latest_contract_line,
    _normalise_plant,
    _normalise_yes_no,
    _scroll_form,
    _scroll_modal_content,
    _scroll_field_into_view,
)


# ---------------------------------------------------------------------------
# PPGL-specific debug screenshot helper
# (PPGI helpers write to sf_ppgi_debug; PPGL form steps write here)
# ---------------------------------------------------------------------------

def _shot(page, name: str, full_page: bool = False) -> None:
    path = os.path.join(DEBUG_DIR, f"ppgl_{name}.png")
    try:
        page.screenshot(path=path, full_page=full_page)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Sample data for local testing
# Plant 1013 = Vasind Works (not in PPGI plant map -- passed as full string)
# ---------------------------------------------------------------------------

SAMPLES = {
    "ppgl-sheet": {
        "product_name":            "PPGL Sheet - (S_PPGLSF)",
        "customer_order_category": "STD",
        "eq_specif_grp":           "BIS",
        "eq_specifi":              "15961_2012",
        "eq_sub_grade":            "YS_250",
        "end_appn":                "GE",
        "order_qty":               "10",
        "cust_req_date":           "06/07/2026",
        "plant_code":              "1013 - Vasind Works",
        "s_brand":                 "JSW RADIANCE",
        "width":                   "1220.000",
        "thickness":               "0.800",
        "length":                  "3050.000",
        "thick_tol_type":          "TCTMAX",
        "tolerance_type":          "AS_STD",
        "al_zn_coating_min":       "150",
        "guard_film_required":     "Y",
        "top_color_code":          "JSWA034S",
    },
    "ppgl-coil": {
        "product_name":            "PPGL Coil - (S_PPGLCF)",
        "customer_order_category": "STD",
        "eq_specif_grp":           "BIS",
        "eq_specifi":              "15961_2012",
        "eq_sub_grade":            "YS_250",
        "end_appn":                "GE",
        "order_qty":               "10",
        "cust_req_date":           "06/07/2026",
        "plant_code":              "1013 - Vasind Works",
        "s_brand":                 "JSW RADIANCE",
        "width":                   "1220.000",
        "thickness":               "0.800",
        "thick_tol_type":          "TCTMAX",
        "tolerance_type":          "AS_STD",
        "al_zn_coating_min":       "150",
        "guard_film_required":     "N",
        "top_color_code":          "JSWA034S",
    },
}


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def add_ppgl_contract_line(contract_number: str, line_data: dict) -> str:
    """
    Headless production entry point.
    Returns the saved contract line name (e.g. '00180047_10'), or raises on failure.
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
            return _fill_ppgl_form(page, line_data, contract_number, baseline)
        finally:
            browser.close()


def add_ppgl_contract_line_for_training(
    contract_number: str,
    line_data: dict,
    pause_seconds: int = 300,
    stop_at_tolerance: bool = False,
    stop_at_s_plant: bool = False,
) -> str:
    """
    Headed (visible browser) entry point for local testing.
    Pauses for pause_seconds after completion so you can verify in Salesforce.
    stop_at_tolerance=True -- fills up to TTT then opens Playwright Inspector.
    stop_at_s_plant=True   -- fills up to S Plant then opens Playwright Inspector.
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
            line_name = _fill_ppgl_form(
                page, line_data, contract_number, baseline,
                stop_at_tolerance=stop_at_tolerance,
                stop_at_s_plant=stop_at_s_plant,
            )
            if stop_at_tolerance:
                log.info("stop_at_tolerance mode -- no Save performed.")
                return ""
            log.info("Contract line created: %s", line_name or "[not captured]")
            if pause_seconds > 0:
                log.info("Browser open for %s seconds -- verify in Salesforce.", pause_seconds)
                time.sleep(pause_seconds)
            return line_name
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# AL ZN Coating Min -- PPGL-specific field handler
# (replaces Zin_Coating Min used for PPGI)
# ---------------------------------------------------------------------------

def _fill_al_zn_coating_min(page, value: str) -> None:
    """
    Fill AL ZN Coating Min(GSM).

    Tries multiple label variants because the field label spelling varies:
      - "AL ZN Coating Min(GSM)"
      - "Al_Zn Coating Min(GSM)"
      - "AL ZN COATING MIN(GSM)"
      - "AL_ZN Coating Min"

    Uses click(click_count=3) to select-all before filling, then Tab to commit
    (same pattern as Zin_Coating Min in PPGI).
    """
    if not value:
        return
    log.info("Filling AL ZN Coating Min(GSM) = '%s'", value)

    label_variants = (
        "AL ZN Coating Min(GSM)",
        "Al_Zn Coating Min(GSM)",
        "AL ZN COATING MIN(GSM)",
        "AL_ZN Coating Min",
        "AL ZN Coating",
    )

    for label in label_variants:
        # Strategy 1: aria-label
        for sel in [f'input[aria-label="{label}"]', f'input[aria-label*="{label}"]']:
            try:
                loc = page.locator(sel).first
                if not loc.is_visible(timeout=800):
                    continue
                loc.scroll_into_view_if_needed()
                loc.click(click_count=3, timeout=2_000)
                loc.fill(value)
                page.wait_for_timeout(300)
                loc.press("Tab")
                log.info("  AL ZN Coating Min filled via aria-label '%s'", sel)
                return
            except Exception:
                pass

        # Strategy 2: label[for]
        try:
            lbl_el = page.locator(f'label:has-text("{label}")').first
            if not lbl_el.is_visible(timeout=600):
                continue
            for_id = lbl_el.get_attribute("for", timeout=1_000)
            if for_id:
                inp = page.locator(f"input#{for_id}")
                inp.scroll_into_view_if_needed()
                inp.click(click_count=3, timeout=2_000)
                inp.fill(value)
                page.wait_for_timeout(300)
                inp.press("Tab")
                log.info("  AL ZN Coating Min filled via label[for] '%s'", label)
                return
        except Exception:
            pass

    # Final fallback: plain fill
    _fill_input(page, "AL ZN Coating Min(GSM)", value)
    log.warning("  AL ZN Coating Min used plain _fill_input fallback")


# ---------------------------------------------------------------------------
# PPGL form fill
# ---------------------------------------------------------------------------

def _fill_ppgl_form(
    page,
    data: dict,
    contract_number: str = "",
    baseline_line: str = "",
    stop_at_tolerance: bool = False,
    stop_at_s_plant: bool = False,
) -> str:
    """
    Fill the PPGL New Contract Line form end-to-end.

    Field order matches the Salesforce modal top-to-bottom.
    All helpers imported from salesforce_add_ppgi_line (proven PPGI patterns).
    Only AL ZN Coating Min is handled locally -- the PPGL-specific field.
    """
    _fix_viewport(page)
    is_sheet = bool(data.get("length", "").strip())
    log.info("=== Filling PPGL form (sheet=%s) ===", is_sheet)

    # -- 1. Product Name -------------------------------------------------------
    _select_product_name(page, data.get("product_name", ""))
    page.wait_for_timeout(2_500)
    _shot(page, "05_product_name")

    # Dependent Fields section must appear before anything else
    page.wait_for_selector("text=Dependent Fields", timeout=10_000)
    _fix_viewport(page)
    log.info("Dependent Fields loaded OK")
    _shot(page, "06_dependent_fields")

    # -- 2. Customer Order Category -------------------------------------------
    _select_combobox(page, "Customer Order Category", data.get("customer_order_category", ""))
    page.wait_for_timeout(1_500)
    _shot(page, "07_cust_order_cat")

    # -- 3-6. Cascading specification comboboxes ------------------------------
    _select_combobox_and_commit(page, "Eq. Specification Group", data.get("eq_specif_grp", ""), wait_after=2_000)
    _shot(page, "08_eq_specif_grp")

    _select_combobox_and_commit(page, "Eq. Specification", data.get("eq_specifi", ""), wait_after=2_000)
    _shot(page, "09_eq_specifi")

    _select_combobox_and_commit(page, "Eq. Sub Specification", data.get("eq_sub_grade", ""), wait_after=1_500)
    _shot(page, "10_eq_sub_grade")

    _select_combobox_and_commit(page, "End Application", data.get("end_appn", ""), wait_after=1_500)
    _shot(page, "11_end_appn")

    # -- 7. Order Quantity -----------------------------------------------------
    _fill_input(page, "Order Quantity", data.get("order_qty", ""))
    page.wait_for_timeout(800)
    _shot(page, "12_order_qty")

    # -- 8. Customer Requested Date -------------------------------------------
    _fill_date(page, "Customer Requested Date", data.get("cust_req_date", ""))
    page.wait_for_timeout(1_500)
    _shot(page, "13_cust_req_date")

    # -- 9. Supply Plant / Depot ----------------------------------------------
    plant_raw  = _normalise_plant(data.get("plant_code", ""))
    plant_code = plant_raw.split()[0].rstrip("-") if plant_raw else ""
    if plant_raw:
        _fill_supply_plant(page, plant_code, plant_raw)
        page.wait_for_timeout(1_500)
        _shot(page, "14_supply_plant")

    # -- 10. S Brand ----------------------------------------------------------
    _fill_brand(page, data.get("s_brand", ""))
    page.wait_for_timeout(800)
    _shot(page, "15_s_brand")

    # -- 11-13. Dimensions ----------------------------------------------------
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

    # -- 14. Thickness Tolerance Type -----------------------------------------
    if stop_at_tolerance:
        log.info(
            "=== PAUSED: Playwright Inspector open. Fill Thickness Tolerance Type, "
            "Tolerance Type, and Top Color Code manually, then click Resume (>) in Inspector. ==="
        )
        page.pause()
        log.info("=== Resumed from Inspector ===")
        _shot(page, "19_after_inspector_resume")
        return ""

    _fill_thick_tol_type_direct(page, data.get("thick_tol_type", ""))
    _shot(page, "19_thick_tol_type")

    # -- 15. Tolerance Type ---------------------------------------------------
    _fill_tolerance_type_direct(page, data.get("tolerance_type", ""))
    _shot(page, "20_tolerance_type")

    # -- 16. AL ZN Coating Min(GSM) -- PPGL-specific --------------------------
    _scroll_form(page, 500)
    page.wait_for_timeout(500)
    _fill_al_zn_coating_min(page, data.get("al_zn_coating_min", ""))
    page.wait_for_timeout(600)
    _shot(page, "21_al_zn_coating_min")

    # -- 17. Scroll down -- Guard Film Required and Top Color Code are lower --
    _scroll_form(page, 500)
    page.wait_for_timeout(600)
    _shot(page, "22_scroll_other_spec")

    # -- 18. Guard Film Required ----------------------------------------------
    gfr = _normalise_guard_film(data.get("guard_film_required", ""))
    _scroll_field_into_view(page, "Guard Film Required")
    _select_guard_film_required(page, gfr)
    page.wait_for_timeout(800)
    _shot(page, "23_guard_film")

    # -- 19. Top Color Code ---------------------------------------------------
    _fill_top_color_code(page, data.get("top_color_code", ""))
    page.wait_for_timeout(800)
    _shot(page, "24_top_color_code")

    # -- 20. Sleeve Required? (optional PPGL field) ---------------------------
    sleeve = _normalise_yes_no(data.get("sleeve_required", ""))
    if sleeve:
        _select_combobox_and_commit(page, "Sleeve Required?", sleeve, wait_after=600)
        _shot(page, "25_sleeve_required")

    # -- 21. S Plant ----------------------------------------------------------
    if plant_raw:
        if stop_at_s_plant:
            log.info(
                "=== PAUSED: Playwright Inspector open at S Plant. "
                "Select S Plant manually, then click Resume (>) in Inspector. ==="
            )
            page.pause()
            log.info("=== Resumed from S Plant Inspector pause ===")
            _shot(page, "26_after_s_plant_inspector", full_page=True)
        else:
            _select_s_plant(page, plant_code, plant_raw)
        page.wait_for_timeout(1_200)
        _shot(page, "26_s_plant")

    _shot(page, "27_before_save", full_page=True)
    log.info("All PPGL fields filled -- ready to Save")

    return _save(page, contract_number, baseline_line)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Create a PPGL SKU contract line in Salesforce.")
    parser.add_argument("--contract", required=False, help="Contract number, e.g. 00180047")
    parser.add_argument(
        "--mode",
        choices=["create", "open"],
        default="open",
        help="create fills and saves; open just opens the contract (default).",
    )
    parser.add_argument(
        "--sample",
        choices=list(SAMPLES.keys()),
        default="ppgl-sheet",
        help="Built-in sample data to use when --mode create. Default: ppgl-sheet.",
    )
    parser.add_argument(
        "--pause",
        type=int,
        default=300,
        help="Seconds to keep browser open after create. Default: 300.",
    )
    parser.add_argument("--product-name",   help="Override product_name")
    parser.add_argument("--qty",            help="Override order_qty")
    parser.add_argument("--width",          help="Override width")
    parser.add_argument("--thickness",      help="Override thickness")
    parser.add_argument("--length",         help="Override length (sheet) or empty for coil")
    parser.add_argument("--al-zn-coating",  help="Override al_zn_coating_min")
    parser.add_argument("--guard-film",     help="Override guard_film_required (Y/N)")
    parser.add_argument("--top-color-code", help="Override top_color_code")
    parser.add_argument("--plant",          help="Override plant_code (e.g. 1013 - Vasind Works)")
    parser.add_argument("--cust-req-date",  help="Override cust_req_date (DD/MM/YYYY)")
    parser.add_argument("--eq-spec-grp",    help="Override eq_specif_grp")
    parser.add_argument("--eq-specifi",     help="Override eq_specifi")
    parser.add_argument("--eq-sub-grade",   help="Override eq_sub_grade")
    parser.add_argument("--sleeve",         help="Override sleeve_required (Y/N)")
    parser.add_argument(
        "--stop-at-tolerance",
        action="store_true",
        help="Fill fields up to Thickness Tolerance Type then open Playwright Inspector. No Save.",
    )
    parser.add_argument(
        "--stop-at-s-plant",
        action="store_true",
        help="Fill fields up to S Plant then open Playwright Inspector. Save continues after Resume.",
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
    data = dict(SAMPLES[args.sample])
    overrides = {
        "product_name":        args.product_name,
        "order_qty":           args.qty,
        "width":               args.width,
        "thickness":           args.thickness,
        "length":              args.length,
        "al_zn_coating_min":   args.al_zn_coating,
        "guard_film_required": args.guard_film,
        "top_color_code":      args.top_color_code,
        "plant_code":          args.plant,
        "cust_req_date":       args.cust_req_date,
        "eq_specif_grp":       args.eq_spec_grp,
        "eq_specifi":          args.eq_specifi,
        "eq_sub_grade":        args.eq_sub_grade,
        "sleeve_required":     args.sleeve,
    }
    for k, v in overrides.items():
        if v is not None:
            data[k] = v

    line_name = add_ppgl_contract_line_for_training(
        contract, data,
        pause_seconds=args.pause,
        stop_at_tolerance=args.stop_at_tolerance,
        stop_at_s_plant=args.stop_at_s_plant,
    )
    print(f"\nResult: {line_name}")


if __name__ == "__main__":
    main()