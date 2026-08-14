import json
import os
import re
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
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

    loc_includes = filters.get("location_include", [])
    if loc_includes:
        loc = (job.get("location") or "").lower()
        # empty location = can't determine, let it through
        if loc and not any(re.search(p, loc) for p in loc_includes):
            return False

    return True


def build_html(new_jobs):
    all_jobs = [(company, j) for company, jobs in new_jobs.items() for j in jobs]
    total = len(all_jobs)

    # Header summary: list exact titles
    if total == 1:
        company, j = all_jobs[0]
        header_title = f"{j['title']} at {company}"
    elif total <= 3:
        header_title = " &nbsp;·&nbsp; ".join(f"{j['title']} at {company}" for company, j in all_jobs)
    else:
        companies = list(new_jobs.keys())
        header_title = f"{total} new roles at {', '.join(companies[:3])}{'&hellip;' if len(companies) > 3 else ''}"

    job_cards = ""
    for company, jobs in new_jobs.items():
        for j in jobs:
            loc = j["location"] or ""
            loc_row = f'<tr><td style="padding:0 0 12px;font-size:13px;color:#6b7280;">{loc}</td></tr>' if loc else ""
            job_cards += f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:12px;background:#ffffff;border:1px solid #e5e7eb;border-radius:6px;">
      <tr><td style="padding:20px 24px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr><td style="padding:0 0 4px;font-size:11px;font-weight:600;color:#6b7280;letter-spacing:0.08em;text-transform:uppercase;">{company}</td></tr>
          <tr><td style="padding:0 0 8px;font-size:16px;font-weight:600;color:#111827;line-height:1.4;">{j['title']}</td></tr>
          {loc_row}
          <tr><td>
            <a href="{j['url']}" style="display:inline-block;padding:8px 18px;background:#111827;color:#ffffff;border-radius:4px;font-size:13px;font-weight:500;text-decoration:none;letter-spacing:0.01em;">View Posting</a>
          </td></tr>
        </table>
      </td></tr>
    </table>"""

    return f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 16px;">
    <tr><td align="center">
      <table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;">

        <!-- Header -->
        <tr><td style="padding:0 0 20px;">
          <p style="margin:0 0 4px;font-size:11px;font-weight:600;color:#6b7280;letter-spacing:0.08em;text-transform:uppercase;">Job Alert</p>
          <p style="margin:0;font-size:20px;font-weight:700;color:#111827;line-height:1.3;">{header_title}</p>
        </td></tr>

        <!-- Divider -->
        <tr><td style="padding:0 0 20px;"><div style="height:1px;background:#e5e7eb;"></div></td></tr>

        <!-- Job cards -->
        <tr><td>{job_cards}</td></tr>

        <!-- Footer -->
        <tr><td style="padding:24px 0 0;">
          <p style="margin:0;font-size:12px;color:#9ca3af;">Checks every 30 minutes &nbsp;·&nbsp; Watching for 2027 New Grad &amp; Intern roles</p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def build_plain(new_jobs):
    lines = []
    for company, jobs in new_jobs.items():
        lines.append(f"== {company} ==")
        for j in jobs:
            loc = f" | {j['location']}" if j["location"] else ""
            lines.append(f"  {j['title']}{loc}")
            lines.append(f"  {j['url']}")
        lines.append("")
    return "\n".join(lines)


def send_email(cfg, new_jobs):
    all_jobs = [(company, j) for company, jobs in new_jobs.items() for j in jobs]
    total = len(all_jobs)
    if total == 1:
        company, j = all_jobs[0]
        subject = f"{j['title']} at {company}"
    else:
        companies = ", ".join(new_jobs.keys())
        subject = f"{total} new roles — {companies}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Job Alert Bot <{cfg['email']['from']}>"
    msg["To"] = cfg["email"]["to"]
    msg.attach(MIMEText(build_plain(new_jobs), "plain"))
    msg.attach(MIMEText(build_html(new_jobs), "html"))

    password = os.environ["EMAIL_APP_PASSWORD"]
    with smtplib.SMTP_SSL(cfg["email"]["smtp_host"], cfg["email"]["smtp_port"]) as s:
        s.login(cfg["email"]["from"], password)
        s.send_message(msg)


def main():
    test_mode = "--test" in sys.argv
    cfg = load_config()

    if test_mode:
        fake_jobs = {
            "Stripe": [{"title": "Software Engineer, New Grad 2027", "location": "San Francisco, CA", "url": "https://stripe.com/jobs/example"}],
            "Google": [{"title": "Software Engineer, Early Career 2027", "location": "Mountain View, CA", "url": "https://careers.google.com/jobs/example"}],
        }
        send_email(cfg, fake_jobs)
        print("Test email sent.")
        return

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
