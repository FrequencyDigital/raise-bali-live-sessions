#!/usr/bin/env python3
"""Submit SEE Awards event nominations from JSON using Selenium.

Fills Most innovative music event or concept and Top event, then clicks
Submit. Locks each record in events.json while it is in progress and after
it succeeds so it is not submitted again.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

URL = "https://see-awards-2026.netlify.app/"
EMAIL_ID = "email-input"
INNOVATIVE_ID = "inp-most_innovative"
TOP_EVENT_ID = "inp-top_event"
SUBMIT_ID = "submit-btn"
SUCCESS_ID = "success-screen"

LOCKED_STATUSES = {"ok", "done", "in_progress"}


def jitter(min_s: float = 0.2, max_s: float = 0.8) -> None:
    time.sleep(random.uniform(min_s, max_s))


def build_driver(headless: bool) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,1600")
    options.add_argument("--disable-notifications")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def wait_visible(driver: webdriver.Chrome, element_id: str, timeout: int = 20):
    return WebDriverWait(driver, timeout).until(
        EC.visibility_of_element_located((By.ID, element_id))
    )


def scroll_into_view(driver: webdriver.Chrome, element) -> None:
    driver.execute_script(
        "arguments[0].scrollIntoView({behavior: 'instant', block: 'center'});",
        element,
    )


def fill_input(driver: webdriver.Chrome, element_id: str, value: str, timeout: int) -> None:
    field = wait_visible(driver, element_id, timeout)
    scroll_into_view(driver, field)
    field.click()
    field.clear()
    field.send_keys(value)
    actual = field.get_attribute("value") or ""
    if actual != value:
        driver.execute_script(
            """
            const el = arguments[0];
            el.value = arguments[1];
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            """,
            field,
            value,
        )
    jitter()


def submit_started(driver: webdriver.Chrome) -> bool:
    try:
        if driver.find_element(By.ID, SUCCESS_ID).is_displayed():
            return True
        button = driver.find_element(By.ID, SUBMIT_ID)
        text = (button.text or "").replace("🏆", "").strip()
        return (not button.is_enabled()) or text.lower().startswith("submitting")
    except Exception:
        return False


def toast_message(driver: webdriver.Chrome) -> str:
    try:
        toast = driver.find_element(By.ID, "toast")
        if "show" in (toast.get_attribute("class") or ""):
            return (toast.text or "").strip()
    except Exception:
        return ""
    return ""


def click_submit_button(driver: webdriver.Chrome, timeout: int) -> None:
    submit = WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.ID, SUBMIT_ID))
    )
    scroll_into_view(driver, submit)
    time.sleep(0.4)

    WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((By.ID, SUBMIT_ID)))
    try:
        ActionChains(driver).move_to_element(submit).pause(0.15).click().perform()
    except Exception:
        pass

    if not submit_started(driver):
        try:
            submit.click()
        except Exception:
            pass

    if not submit_started(driver):
        driver.execute_script("arguments[0].click();", submit)

    WebDriverWait(driver, timeout).until(submit_started)
    message = toast_message(driver)
    if message:
        raise RuntimeError(f"submit blocked: {message}")


def wait_for_nomination_post(driver: webdriver.Chrome, timeout: int) -> None:
    """Keep the browser open until the hidden iframe POST has left the page."""
    WebDriverWait(driver, timeout).until(
        lambda d: d.find_element(By.ID, SUCCESS_ID).is_displayed()
    )

    def iframe_posted(d) -> bool:
        return bool(
            d.execute_script(
                """
                const iframe = document.getElementById('hidden-iframe');
                if (!iframe) return false;
                try {
                    const href = iframe.contentWindow.location.href;
                    return Boolean(href && href !== 'about:blank');
                } catch (e) {
                    return true;
                }
                """
            )
        )

    try:
        WebDriverWait(driver, timeout).until(iframe_posted)
        time.sleep(1.5)
    except TimeoutException:
        time.sleep(3)


def fill_and_submit(driver: webdriver.Chrome, record: dict, timeout: int) -> None:
    wait_visible(driver, EMAIL_ID, timeout)
    wait_visible(driver, INNOVATIVE_ID, timeout)
    jitter()

    fill_input(driver, EMAIL_ID, record["email"], timeout)
    fill_input(driver, INNOVATIVE_ID, record["most_innovative"], timeout)
    fill_input(driver, TOP_EVENT_ID, record["top_event"], timeout)

    click_submit_button(driver, timeout)
    wait_for_nomination_post(driver, timeout)


def record_status(record: dict) -> str:
    return str(record.get("status") or "pending").strip().lower()


class NominationStore:
    """Thread-safe events.json with per-record lock/status fields."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        records = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(records, list) or not records:
            raise SystemExit(f"{path} must be a non-empty JSON list")
        required = {
            "id",
            "email",
            "most_innovative",
            "top_event",
        }
        for record in records:
            missing = required - set(record)
            if missing:
                raise SystemExit(
                    f"Record {record.get('id')} missing fields: {sorted(missing)}"
                )
            if "status" not in record:
                record["status"] = "pending"
        self.records: list[dict] = records
        self._save()

    def _save(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.records, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def counts(self) -> dict[str, int]:
        tallies: dict[str, int] = {}
        for record in self.records:
            status = record_status(record)
            tallies[status] = tallies.get(status, 0) + 1
        return tallies

    def reset_all_to_pending(self) -> int:
        """Set every record back to pending so the run starts from scratch."""
        with self._lock:
            reset = 0
            for record in self.records:
                if record_status(record) != "pending" or "error" in record:
                    reset += 1
                record["status"] = "pending"
                record.pop("error", None)
            self._save()
            return reset

    def runnable(self) -> list[dict]:
        with self._lock:
            return [
                dict(record)
                for record in self.records
                if record_status(record) not in LOCKED_STATUSES
            ]

    def claim(self, record_id: int) -> dict | None:
        """Lock a record as in_progress. Returns a copy, or None if already locked."""
        with self._lock:
            for record in self.records:
                if record["id"] != record_id:
                    continue
                if record_status(record) in LOCKED_STATUSES:
                    return None
                record["status"] = "in_progress"
                record.pop("error", None)
                self._save()
                return dict(record)
            return None

    def mark(self, record_id: int, status: str, error: str | None = None) -> None:
        with self._lock:
            for record in self.records:
                if record["id"] != record_id:
                    continue
                record["status"] = status
                if error:
                    record["error"] = error
                else:
                    record.pop("error", None)
                self._save()
                return


def submit_record(
    record: dict,
    headless: bool,
    timeout: int,
    store: NominationStore,
) -> dict:
    claimed = store.claim(record["id"])
    if claimed is None:
        return {
            "id": record["id"],
            "email": record["email"],
            "status": "skipped",
            "error": "already locked or completed",
            "elapsed_s": 0,
        }

    started = time.time()
    driver = None
    try:
        driver = build_driver(headless)
        driver.get(URL)
        fill_and_submit(driver, claimed, timeout)
        store.mark(claimed["id"], "ok")
        return {
            "id": claimed["id"],
            "email": claimed["email"],
            "status": "ok",
            "elapsed_s": round(time.time() - started, 2),
        }
    except TimeoutException as exc:
        error = f"timeout: {exc}"
        store.mark(claimed["id"], "error", error)
        return {
            "id": claimed["id"],
            "email": claimed["email"],
            "status": "error",
            "error": error,
            "elapsed_s": round(time.time() - started, 2),
        }
    except WebDriverException as exc:
        error = f"webdriver: {exc}"
        store.mark(claimed["id"], "error", error)
        return {
            "id": claimed["id"],
            "email": claimed["email"],
            "status": "error",
            "error": error,
            "elapsed_s": round(time.time() - started, 2),
        }
    except Exception as exc:  # noqa: BLE001 — keep worker from killing the pool
        error = str(exc)
        store.mark(claimed["id"], "error", error)
        return {
            "id": claimed["id"],
            "email": claimed["email"],
            "status": "error",
            "error": error,
            "elapsed_s": round(time.time() - started, 2),
        }
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def write_results(path: Path, results: list[dict]) -> None:
    path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fill and submit SEE Awards event nominations from JSON. "
            "Fills Most innovative music event or concept and Top event, "
            "then clicks Submit. Locks each record in events.json."
        )
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=Path("events.json"),
        help="Path to events JSON (default events.json).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Parallel Chrome workers after the smoke test (default 5).",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chrome in headless mode.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=25,
        help="Seconds to wait for page elements / success screen (default 25).",
    )
    parser.add_argument(
        "--results",
        type=Path,
        default=Path("events_results.json"),
        help="Where to write per-record results (default events_results.json).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="If > 0, only process the first N unlocked records (useful for a dry run).",
    )
    parser.add_argument(
        "--reset-locks",
        action="store_true",
        help="Set every record in events.json back to pending and start over.",
    )
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be at least 1")

    store = NominationStore(args.json)
    if args.reset_locks:
        reset = store.reset_all_to_pending()
        print(
            f"Reset all {len(store.records)} records to pending "
            f"({reset} were not pending). Starting over."
        )

    records = store.runnable()
    if args.limit > 0:
        records = records[: args.limit]

    tallies = store.counts()
    print(
        f"Loaded {len(store.records)} records from {args.json} "
        f"({tallies.get('ok', 0) + tallies.get('done', 0)} done, "
        f"{len(records)} runnable)."
    )
    if not records:
        print("Nothing to submit — every record is already locked or completed.")
        return

    smoke, *rest = records
    print(f"Smoke-testing record {smoke['id']} ({smoke['email']}) …")
    smoke_result = submit_record(smoke, args.headless, args.timeout, store)
    results = [smoke_result]
    write_results(args.results, results)

    if smoke_result["status"] != "ok":
        print(
            f"Smoke test failed for record {smoke['id']}: "
            f"{smoke_result.get('error', 'unknown error')}"
        )
        print(f"Wrote {args.results}; stopping before parallel run.")
        sys.exit(1)

    print(f"Smoke test succeeded in {smoke_result['elapsed_s']}s.")
    if not rest:
        print("No remaining unlocked records.")
        print(f"Wrote {args.results}")
        return

    workers = min(args.workers, len(rest))
    print(f"Submitting {len(rest)} remaining records with {workers} workers …")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(submit_record, record, args.headless, args.timeout, store): record
            for record in rest
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            write_results(args.results, results)
            status = result["status"]
            print(
                f"[{status}] id={result['id']} email={result['email']} "
                f"({result['elapsed_s']}s)"
            )

    results.sort(key=lambda item: item["id"])
    write_results(args.results, results)
    ok = sum(1 for item in results if item["status"] == "ok")
    failed = sum(1 for item in results if item["status"] == "error")
    skipped = sum(1 for item in results if item["status"] == "skipped")
    print(
        f"Done. {ok} ok, {failed} failed, {skipped} skipped. "
        f"Results: {args.results}"
    )
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
