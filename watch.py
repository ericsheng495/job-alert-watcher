import json
import os
import re
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

import yaml

from sources import fetch_company

ROOT = Path(__file__).parent
SEEN_FILE = ROOT / "seen.json"


def load_config():
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def load_seen():
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=0))


def matches(job, filters):
    text = job["title"].lower()
    if not any(re.search(p, text) for p in filters["include"]):
        return False
    if any(re.search(p, text) for p in filters.get("exclude", [])):
        return False
    return True


def send_email(cfg, new_jobs):
    lines = []
    for company, jobs in new_jobs.items():
        lines.append(f"{company}")
        for j in jobs:
            loc = f" — {j['location']}" if j["location"] else ""
            lines.append(f"  • {j['title']}{loc}")
            lines.append(f"    {j['url']}")
        lines.append("")

    total = sum(len(v) for v in new_jobs.values())
    msg = MIMEText("\n".join(lines))
    msg["Subject"] = f"[Job Alert] {total} new matching posting(s)"
    msg["From"] = cfg["email"]["from"]
    msg["To"] = cfg["email"]["to"]

    password = os.environ["EMAIL_APP_PASSWORD"]
    with smtplib.SMTP_SSL(cfg["email"]["smtp_host"], cfg["email"]["smtp_port"]) as s:
        s.login(cfg["email"]["from"], password)
        s.send_message(msg)


def main():
    cfg = load_config()
    seen = load_seen()
    first_run = not SEEN_FILE.exists()
    new_jobs = {}

    for company in cfg["companies"]:
        try:
            jobs = fetch_company(company)
        except Exception as e:
            print(f"[warn] {company['name']}: {e}", file=sys.stderr)
            continue

        for job in jobs:
            if job["id"] in seen:
                continue
            seen.add(job["id"])
            if matches(job, cfg["filters"]):
                new_jobs.setdefault(company["name"], []).append(job)

    save_seen(seen)

    if first_run:
        # baseline run: record everything currently posted, don't spam
        total = sum(len(v) for v in new_jobs.values())
        print(f"First run — baselined {len(seen)} postings ({total} would have matched). No email sent.")
        return

    if new_jobs:
        send_email(cfg, new_jobs)
        for company, jobs in new_jobs.items():
            for j in jobs:
                print(f"[new] {company}: {j['title']} -> {j['url']}")
    else:
        print("No new matching postings.")


if __name__ == "__main__":
    main()
