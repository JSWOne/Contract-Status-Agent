# Tool Name   : Salesforce Contract Status Scraper (Playwright)
# Skill       : Contract Status Agent
# Version     : 1.1.0
# Last Updated: 2026-04-30
# Description : Uses Playwright to log into the JSW Steel Salesforce Experience Cloud
#               portal, navigates to "JSW One All Contracts" list view, sorts by
#               Created Date, scrapes all contracts created in the last 14 days
#               (date filtering done in Python after scraping), and returns a list
#               of dicts: contract_no, account_name, status, created_date.
#               Handles multi-page pagination and stops early when records exceed
#               14-day window (list is sorted descending by Created Date).
# Dependencies: playwright, python-dotenv
# ENV Vars    : SF_PORTAL_URL, SF_USERNAME, SF_PASSWORD, PLAYWRIGHT_HEADLESS
# DRY_RUN     : Scrapes data but skips writing anywhere; prints records to console only

import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ── Config ─────────────────────────────────────────────────────────────────────
load_dotenv(Path(__file__).with_name(".env"))

SF_PORTAL_URL = os.getenv("SF_PORTAL_URL")   # https://jswsteel.my.site.com/jswone/s/login/
SF_USERNAME   = os.getenv("SF_USERNAME")
SF_PASSWORD   = os.getenv("SF_PASSWORD")
HEADLESS      = os.getenv("PLAYWRIGHT_HEADLESS", "True") == "True"
DRY_RUN       = os.getenv("DRY_RUN", "True").strip().lower() == "true"

MEMORY_PATH = Path(__file__).parent.parent / "Memory" / "memory.json"
LOG_PATH    = Path("/tmp/error.log") if os.environ.get("GCS_MEMORY_BUCKET") else Path(__file__).parent.parent / "Logs" / "error.log"

# Date cutoff — only keep contracts created within the last 14 days
DATE_WINDOW_DAYS = 14

# ── Selectors — recorded via Playwright codegen on 2026-04-30 ─────────────────
# Login page
LOC_USERNAME  = ("role", "textbox", "Username")     # get_by_role("textbox", name="Username")
LOC_PASSWORD  = ("role", "textbox", "Password")     # get_by_role("textbox", name="Password")
LOC_LOGIN_BTN = ("role", "button",  "Log in")       # get_by_role("button",  name="Log in")

# Contracts list — direct URL confirmed from browser on 2026-04-30
CONTRACTS_URL = "https://jswsteel.my.site.com/jswone/s/recordlist/Contract/Default?Contract-filterId=JSW_One_All_Contracts"

# Contracts table — standard Salesforce LWR/Experience Cloud patterns
# ⚠️  VERIFY these selectors match the live page (run with PLAYWRIGHT_HEADLESS=False)
SEL_TABLE_ROWS   = "table tbody tr"                      # each contract row
SEL_CONTRACT_NO  = "td[data-label='Contract Number']"       # contract no cell
SEL_ACCOUNT      = "td[data-label='Account Name']"       # account name cell
SEL_STATUS       = "td[data-label='Status']"             # status cell
SEL_CREATED_DATE = "td[data-label='Created Date']"       # created date cell
SEL_NEXT_BTN     = "button[name='next']"                 # pagination next button
# ⚠️  If the above don't work, try these alternatives:
#   SEL_TABLE_ROWS   = "lightning-datatable tr"
#   SEL_CONTRACT_NO  = "td:nth-child(1) a"
#   SEL_NEXT_BTN     = "button[aria-label='Next Page']"


# ── Helper: write to Logs/error.log (NDJSON, append-only) ─────────────────────
def log_error(run_id, step, error_code, error_message,
              payload=None, resolution=None, status="pending",
              ticket_id=None, learning=None):
    entry = {
        "timestamp":            datetime.utcnow().isoformat(),
        "run_id":               run_id,
        "skill":                "Contract Status Agent",
        "tool":                 "scrape_contract_statuses.py",
        "step":                 step,
        "error_code":           error_code,
        "error_message":        error_message,
        "input_payload":        payload or {},
        "context":              step,
        "resolution_attempted": resolution,
        "resolution_status":    status,
        "learning":             learning,
        "ticket_id":            ticket_id,
    }
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as log_exc:
        import sys
        print(json.dumps(entry), file=sys.stderr)
        print(f"[log_error] Could not write to {LOG_PATH}: {log_exc}", file=sys.stderr)


# ── Helper: write step progress to Memory/memory.json ─────────────────────────
def write_memory_step(memory, step_name, status, detail="", extra=None):
    step_entry = {
        "step":      step_name,
        "status":    status,
        "detail":    detail,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if extra:
        step_entry.update(extra)
    if memory.get("state", {}).get("run_history"):
        memory["state"]["run_history"][-1]["steps"].append(step_entry)
    memory["last_action"] = detail
    # Memory persistence is handled by the orchestrator (run_contract_status_agent.py).
    # Skip local file write here to avoid crashing in Cloud Run (read-only /app filesystem).


# ── Phase 1: Login ─────────────────────────────────────────────────────────────
def login(page, run_id, memory):
    try:
        page.goto(SF_PORTAL_URL, wait_until="domcontentloaded", timeout=30000)

        # Wait for login form to be ready
        page.wait_for_selector("role=textbox[name='Username']", timeout=15000)

        page.get_by_role("textbox", name="Username").fill(SF_USERNAME)
        page.get_by_role("textbox", name="Password").fill(SF_PASSWORD)

        login_url = page.url   # capture exact login URL before clicking

        page.get_by_role("button", name="Log in").click()

        # Wait for URL to change away from the login page
        # 60s timeout to handle security/trust prompts that may appear
        page.wait_for_url(lambda url: url.rstrip("/") != login_url.rstrip("/"), timeout=60000)

        # LWR sites never reach networkidle — wait for nav menu instead
        page.wait_for_selector("role=menuitem[name='Contract']", timeout=30000)

        write_memory_step(memory, "login", "success",
                          f"Logged into Salesforce portal as {SF_USERNAME} | landed on {page.url}")

    except PlaywrightTimeout as e:
        log_error(run_id, "login", "TIMEOUT", str(e),
                  resolution="Check for MFA/trust prompt blocking redirect; increase timeout")
        write_memory_step(memory, "login", "failed", "TIMEOUT — possible MFA or trust prompt")
        raise

    except Exception as e:
        log_error(run_id, "login", "LOGIN_FAIL", str(e))
        write_memory_step(memory, "login", "failed", f"LOGIN_FAIL: {e}")
        raise


# ── Phase 2: Navigate directly to "JSW One All Contracts" list view ───────────
def navigate_to_contracts(page, run_id, memory):
    try:
        # Go directly to the confirmed contracts list URL
        page.goto(CONTRACTS_URL, wait_until="domcontentloaded", timeout=30000)

        # Wait for the table to render
        page.wait_for_selector(SEL_TABLE_ROWS, timeout=30000)

        # Ensure Created Date is sorted DESCENDING (↓) — check current state first
        # Salesforce sets aria-sort on the <th> element: "ascending" | "descending" | absent
        sort_th = page.locator("th[aria-label*='Created Date']")
        current_sort = sort_th.get_attribute("aria-sort") if sort_th.count() > 0 else None
        print(f"[DEBUG] Created Date current aria-sort: {current_sort!r}")

        if current_sort == "descending":
            print("[DEBUG] Already descending — no sort click needed")

        else:
            # Scroll page to top so the sticky column header is in the viewport
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(500)

            # Try clicking the anchor inside the th (the visible "Created Date" text link)
            sort_link = page.locator("th[aria-label='Created Date'] a")
            if sort_link.count() > 0:
                sort_link.first.click()
                print("[DEBUG] Clicked th anchor to sort")
            else:
                # Fallback: use getBoundingClientRect to click at actual viewport coordinates
                page.evaluate("""() => {
                    const th = document.querySelector('th[aria-label="Created Date"]');
                    if (th) {
                        const rect = th.getBoundingClientRect();
                        const el = document.elementFromPoint(
                            rect.left + rect.width / 2,
                            rect.top  + rect.height / 2
                        );
                        if (el) el.click(); else th.click();
                    }
                }""")
                print("[DEBUG] Used getBoundingClientRect click for sort")

            page.wait_for_timeout(2000)
            new_sort = sort_th.get_attribute("aria-sort") if sort_th.count() > 0 else None
            print(f"[DEBUG] After sort click, aria-sort: {new_sort!r}")

        write_memory_step(memory, "navigate_contracts", "success",
                          f"Navigated to JSW One All Contracts (descending by Created Date) | URL: {CONTRACTS_URL}")

    except PlaywrightTimeout as e:
        log_error(run_id, "navigate_contracts", "TIMEOUT", str(e))
        write_memory_step(memory, "navigate_contracts", "failed", "TIMEOUT during navigation")
        raise

    except Exception as e:
        log_error(run_id, "navigate_contracts", "ELEMENT_NOT_FOUND", str(e))
        write_memory_step(memory, "navigate_contracts", "failed", str(e))
        raise


# ── Phase 3: Parse Created Date from portal string ────────────────────────────
def parse_created_date(date_str):
    """Try common Salesforce date formats. Returns datetime or None."""
    for fmt in ("%d/%m/%Y, %I:%M %p", "%m/%d/%Y, %I:%M %p",
                "%d/%m/%Y %I:%M %p", "%Y-%m-%d",
                "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


# ── Phase 4: Scrape one page — collect ALL rows, filter by date in Python ──────
# Salesforce Aura tables have NO data-label on cells. Use positional JS evaluate:
#   cells[0] = error icon td (empty)
#   cells[1] = contract number th[scope='row']
#   cells[2] = account name td
#   cells[3] = status td
#   cells[4] = start date td
#   cells[5] = end date td
#   cells[6] = (other field)
#   cells[7] = created date td  ← has timestamp, e.g. '07/07/2024, 3:14 pm'
#   cells[8] = show actions button
def scrape_page(page):
    contracts = []
    rows = page.locator(SEL_TABLE_ROWS).all()
    print(f"  [DEBUG] Rows found on page: {len(rows)}")

    for i, row in enumerate(rows):
        try:
            cells = row.evaluate(
                "el => [...el.querySelectorAll('th, td')].map(c => c.innerText.trim())"
            )
            if i == 0:
                print(f"  [DEBUG] First row cells ({len(cells)}): {cells}")
            if len(cells) < 5:
                print(f"  [DEBUG] Row {i+1}: only {len(cells)} cells — skipping")
                continue
            contract_no  = cells[1]
            account_name = cells[2]
            status       = cells[3]
            created_date = cells[7]
            print(f"  [DEBUG] Row {i+1}: {contract_no} | {account_name} | {status} | {created_date}")
            contracts.append({
                "contract_no":  contract_no,
                "account_name": account_name,
                "status":       status,
                "created_date": created_date,
            })
        except Exception as e:
            print(f"  [DEBUG] Row {i+1}: FAILED — {e}")
            continue

    return contracts


# ── Phase 4 (cont.): Infinite-scroll through all rows, filter to last 14 days ──
# The list uses infinite scroll (no next-page button). Scroll the last visible
# row into view to trigger loading; stop when no new rows appear.
# With descending sort: bail out early once records are older than the cutoff.
def scrape_all_pages(page, run_id, memory):
    cutoff_date = datetime.utcnow() - timedelta(days=DATE_WINDOW_DAYS)
    all_contracts = []
    processed_count = 0
    no_growth_streak = 0
    MAX_NO_GROWTH = 3   # 3 consecutive scrolls with no new rows → done
    scroll_num = 0

    # Detect sort direction so we know whether to early-stop
    sort_th = page.locator("th[aria-label*='Created Date']")
    sort_dir = sort_th.get_attribute("aria-sort") if sort_th.count() > 0 else None
    print(f"[DEBUG] Sort direction at scrape start: {sort_dir!r}")

    while True:
        rows = page.locator(SEL_TABLE_ROWS).all()
        current_count = len(rows)
        new_rows = rows[processed_count:]

        if new_rows:
            print(f"\n[DEBUG] Scroll {scroll_num}: {len(new_rows)} new rows (total visible: {current_count})")
            stop_early = False
            for row in new_rows:
                try:
                    cells = row.evaluate(
                        "el => [...el.querySelectorAll('th, td')].map(c => c.innerText.trim())"
                    )
                    if len(cells) < 8:
                        continue
                    contract_no  = cells[1]
                    account_name = cells[2]
                    status       = cells[3]
                    created_date = cells[7]
                    print(f"  {contract_no} | {account_name} | {status} | {created_date}")
                    all_contracts.append({
                        "contract_no":  contract_no,
                        "account_name": account_name,
                        "status":       status,
                        "created_date": created_date,
                    })
                    # Early stop only when sorted descending (newest first)
                    if sort_dir == "descending":
                        parsed = parse_created_date(created_date)
                        if parsed and parsed < cutoff_date:
                            print(f"  [DEBUG] Reached record older than {DATE_WINDOW_DAYS} days — stopping scroll")
                            stop_early = True
                            break
                except Exception as e:
                    print(f"  [DEBUG] Row parse error: {e}")
                    continue
            processed_count = current_count
            if stop_early:
                break

        # Scroll last visible row into view to trigger Salesforce infinite scroll
        all_rows = page.locator(SEL_TABLE_ROWS).all()
        if all_rows:
            try:
                all_rows[-1].scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass
        page.wait_for_timeout(2000)

        new_count = page.locator(SEL_TABLE_ROWS).count()
        if new_count <= current_count:
            no_growth_streak += 1
            print(f"[DEBUG] No new rows (streak {no_growth_streak}/{MAX_NO_GROWTH})")
            if no_growth_streak >= MAX_NO_GROWTH:
                print(f"[DEBUG] End of list — {current_count} total rows loaded")
                break
        else:
            no_growth_streak = 0

        scroll_num += 1

    # Filter to last 14 days
    filtered = []
    for c in all_contracts:
        parsed = parse_created_date(c["created_date"])
        if parsed and parsed >= cutoff_date:
            filtered.append(c)
        elif parsed is None:
            filtered.append(c)

    print(f"\n[DEBUG] Total rows collected: {len(all_contracts)} | Within {DATE_WINDOW_DAYS} days: {len(filtered)}")
    return filtered


# ── Main run function ──────────────────────────────────────────────────────────
def run(run_id, memory):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page(viewport={"width": 1280, "height": 800})

        try:
            login(page, run_id, memory)
            navigate_to_contracts(page, run_id, memory)
            all_contracts = scrape_all_pages(page, run_id, memory)
            print(f"\n[DEBUG] Landing URL after navigation: {page.url}")

            if not all_contracts:
                log_error(run_id, "scrape", "SCRAPE_EMPTY",
                          "Zero contracts returned — check selectors or filter",
                          status="failed")
                write_memory_step(memory, "browser_scrape", "failed", "SCRAPE_EMPTY")
                if DRY_RUN:
                    print("[DRY_RUN] Warning: zero contracts in last 14 days — check sort/scroll")
                    return []
                raise Exception("SCRAPE_EMPTY: no contracts found in last 14 days")

            write_memory_step(
                memory, "browser_scrape", "success",
                f"Scraped {len(all_contracts)} contracts from Salesforce portal",
                extra={"contracts_fetched": len(all_contracts)},
            )

            if DRY_RUN:
                print(f"\n[DRY_RUN] Scraped {len(all_contracts)} contracts:\n")
                for c in all_contracts:
                    print(c)
                return all_contracts

            return all_contracts

        finally:
            browser.close()


# ── Standalone entry point ─────────────────────────────────────────────────────
if __name__ == "__main__":
    if MEMORY_PATH.exists():
        memory = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    else:
        memory = {"state": {"run_history": [{"steps": []}]}, "last_action": None}

    results = run("run_test", memory)
    print(f"\nTotal contracts scraped: {len(results)}")
