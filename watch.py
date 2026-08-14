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
    total = sum(len(v) for v in new_jobs.values())
    company_blocks = ""
    for company, jobs in new_jobs.items():
        job_rows = ""
        for j in jobs:
            loc = j["location"] or "Location not listed"
            job_rows += f"""
            <tr>
              <td style="padding:12px 16px;border-bottom:1px solid #f0f0f0;">
                <a href="{j['url']}" style="font-size:15px;font-weight:600;color:#1a1a2e;text-decoration:none;">{j['title']}</a>
                <div style="margin-top:4px;font-size:13px;color:#666;">📍 {loc}</div>
                <div style="margin-top:8px;">
                  <a href="{j['url']}" style="display:inline-block;padding:6px 14px;background:#4f46e5;color:#fff;border-radius:6px;font-size:12px;font-weight:600;text-decoration:none;">Apply Now →</a>
                </div>
              </td>
            </tr>"""
        company_blocks += f"""
        <div style="margin-bottom:28px;">
          <div style="background:#4f46e5;color:#fff;padding:10px 16px;border-radius:8px 8px 0 0;font-size:14px;font-weight:700;letter-spacing:0.5px;">{company}</div>
          <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e8e8e8;border-top:none;border-radius:0 0 8px 8px;background:#fff;">
            {job_rows}
          </table>
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <div style="max-width:600px;margin:32px auto;padding:0 16px;">
    <div style="background:#1a1a2e;border-radius:12px 12px 0 0;padding:24px 28px;">
      <div style="font-size:22px;font-weight:700;color:#fff;">🎯 Job Alert</div>
      <div style="margin-top:6px;font-size:14px;color:#a0a0c0;">{total} new matching posting{"s" if total != 1 else ""} · New Grad &amp; Intern 2027</div>
    </div>
    <div style="background:#f9f9fb;border:1px solid #e8e8e8;border-top:none;border-radius:0 0 12px 12px;padding:24px 20px;">
      {company_blocks}
      <div style="text-align:center;font-size:12px;color:#aaa;margin-top:8px;">
        Sent by job-alert-watcher · Checks every 30 min
      </div>
    </div>
  </div>
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
    total = sum(len(v) for v in new_jobs.values())
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🎯 {total} new job posting{'s' if total != 1 else ''} matched"
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
