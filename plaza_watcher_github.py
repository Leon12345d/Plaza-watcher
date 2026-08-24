#!/usr/bin/env python3
"""
Plaza watcher — GitHub Actions version
========================================
Same idea as the original script, but designed to run ONCE per execution
(GitHub Actions calls this on a schedule, e.g. every 5 minutes, instead of
this script looping forever itself).

State (what the page looked like last time) is saved to plaza_state.json,
which the GitHub Actions workflow commits back to the repo after each run
so the next run can compare against it.

You should NOT need to edit anything in this file -- the topic name is read
from a GitHub "secret" (set up in the guide), not hardcoded here.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

URL = "https://plaza.newnewnew.space/en/availables-places/living-place"

# Read from a GitHub Actions secret (see setup guide) -- never hardcoded here.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")

MUST_CONTAIN = "Enschede"
STATE_FILE = Path(__file__).parent / "plaza_state.json"
LOG_FILE = Path(__file__).parent / "plaza_watcher.log"
CONTENT_SELECTOR = "body"

KNOWN_BOILERPLATE = {
    "high contrast", "english", "find a home", "find your space",
    "with our living and working spaces, we offer you the freedom to live a vibrant city life.",
    "living place", "workspace", "parking/storage", "eligibility & documents",
    "can i apply for a home?", "which documents do i need?", "how it works",
    "locations", "netherlands", "maastrichtamsterdamutrechteindhovenenschededdelftbredaarnhem",
    "germany", "bochum", "poland", "poznan", "faq & help", "contact", "menu",
    "search", "what are you looking for?", "or is your question listed here?",
    "view all questions and answers", "registration", "login",
    "login to plaza resident services", "already have an account with us?",
    "then log in with your known login data.",
    "no account yet?", "register to respond quickly and easily to our vacant properties.",
    "subscribe", "language", "choose your language", "nederlands",
    "or translate with google translate",
    "pay attention: the use of google translate may affect the functioning and display of the website, which means that perhaps not everything will work as expected.",
    "available places", "living spaces", "workspaces", "parking / storage",
    "newnewnew app", "info & contact", "faq", "email", "my page", "account",
    "forgotten username", "forgotten password", "disclaimer", "privacy statement",
    "developed by zig websoftware",
}


def send_notification(title: str, message: str):
    if not NTFY_TOPIC:
        log("!! NTFY_TOPIC secret is not set -- cannot send notification.")
        return
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": "urgent", "Tags": "house,rotating_light"},
            timeout=15,
        )
    except Exception as e:
        log(f"!! Failed to send notification: {e}")


def log(msg: str):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def fetch_rendered_text() -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        )
        page.goto(URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        text = page.inner_text(CONTENT_SELECTOR)
        browser.close()
        return text


def normalize_lines(raw_text: str) -> list[str]:
    lines = [ln.strip() for ln in raw_text.splitlines()]
    lines = [ln for ln in lines if ln]
    seen = set()
    cleaned = []
    for ln in lines:
        key = re.sub(r"\s+", " ", ln.lower()).strip()
        if key in KNOWN_BOILERPLATE or key in seen:
            continue
        seen.add(key)
        cleaned.append(ln)
    return cleaned


def load_previous_lines() -> set:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return set(data.get("lines", []))
        except Exception:
            return set()
    return set()


def save_lines(lines: list[str]):
    STATE_FILE.write_text(
        json.dumps({"lines": lines, "checked_at": datetime.now().isoformat()}, indent=2),
        encoding="utf-8",
    )


def main():
    is_first_run = not STATE_FILE.exists()
    text = fetch_rendered_text()
    current_lines = normalize_lines(text)
    previous_set = load_previous_lines()

    new_lines = [ln for ln in current_lines if ln not in previous_set]
    if MUST_CONTAIN:
        new_lines = [ln for ln in new_lines if MUST_CONTAIN.lower() in ln.lower()]

    save_lines(current_lines)

    if is_first_run:
        log(f"First run -- captured baseline ({len(current_lines)} lines). No alert sent.")
        return

    if new_lines:
        preview = "\n".join(new_lines[:15])
        log(f"NEW CONTENT DETECTED ({len(new_lines)} new line(s)):\n{preview}")
        send_notification(
            title="Plaza: possible new listing!",
            message=f"New content on the Plaza page:\n\n{preview}\n\n{URL}",
        )
    else:
        log("Checked -- no new content.")


if __name__ == "__main__":
    main()
