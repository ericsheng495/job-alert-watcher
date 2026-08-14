import json
import os
import re
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
import yaml

from sources import fetch_company

ROOT = Path(__file__).parent
SEEN_FILE = ROOT / "seen.json"
JOBS_FILE = ROOT / "jobs.json"
DASHBOARD_FILE = ROOT / "index.html"
LOGO_HEADERS = {"User-Agent": "Mozilla/5.0 (job-alert-watcher)"}


def load_config():
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def load_seen():
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=0))


def load_jobs():
    if JOBS_FILE.exists():
        return json.loads(JOBS_FILE.read_text())
    return []


def save_jobs(jobs):
    JOBS_FILE.write_text(json.dumps(jobs, indent=2))


def matches(job, filters):
    text = job["title"].lower()
    if not any(re.search(p, text) for p in filters["include"]):
        return False
    if any(re.search(p, text) for p in filters.get("exclude", [])):
        return False
    loc_includes = filters.get("location_include", [])
    if loc_includes:
        loc = (job.get("location") or "").lower()
        if loc and not any(re.search(p, loc) for p in loc_includes):
            return False
    return True


def short_title(title):
    return re.sub(r"^Software Engineer,?\s*", "", title, flags=re.IGNORECASE).strip()


def fetch_logos(companies, domains):
    logos = {}
    for company in companies:
        domain = domains.get(company, "")
        if not domain:
            continue
        try:
            r = requests.get(f"https://logo.clearbit.com/{domain}", headers=LOGO_HEADERS, timeout=5)
            if r.ok and r.content:
                cid = re.sub(r"[^a-z0-9]", "", company.lower())
                logos[company] = (cid, r.content)
        except Exception:
            pass
    return logos


# ── Dashboard ──────────────────────────────────────────────────────────────────

def build_dashboard(all_jobs, domains, watched_companies):
    updated = datetime.now(timezone.utc).strftime("%b %d, %Y at %H:%M UTC")
    total = len(all_jobs)

    counts = {}
    for j in all_jobs:
        counts[j["company"]] = counts.get(j["company"], 0) + 1

    company_tiles = ""
    for c in watched_companies:
        domain = domains.get(c["name"], "")
        logo_url = f"https://logo.clearbit.com/{domain}" if domain else ""
        n = counts.get(c["name"], 0)
        cid = re.sub(r"[^a-z0-9]", "", c["name"].lower())
        count_label = f"{n} job{'s' if n != 1 else ''}"
        count_style = "color:#111827;font-weight:700;" if n > 0 else "color:#9ca3af;font-weight:500;"
        company_tiles += (
            f'<div class="co-card" onclick="filter(\'{cid}\')" id="co-{cid}">'
            f'<img src="{logo_url}" onerror="this.style.display=\'none\'" alt="{c["name"]}" class="co-logo">'
            f'<div class="co-name">{c["name"]}</div>'
            f'<div class="co-count" style="{count_style}">{count_label}</div>'
            f'</div>'
        )

    matched_companies = sorted(counts.keys())
    filter_btns = '<button onclick="filter(\'\')" class="chip active" id="chip-all">All</button> '
    for c in matched_companies:
        cid = re.sub(r"[^a-z0-9]", "", c.lower())
        filter_btns += f'<button onclick="filter(\'{cid}\')" class="chip" id="chip-{cid}">{c}</button> '

    cards = ""
    for j in all_jobs:
        company = j["company"]
        domain = domains.get(company, "")
        logo_url = f"https://logo.clearbit.com/{domain}" if domain else ""
        cid = re.sub(r"[^a-z0-9]", "", company.lower())
        loc = j.get("location") or ""
        date = j.get("seen_at", "")[:10]
        loc_html = f'<div class="location">{loc}</div>' if loc else ""
        cards += (
            f'<div class="card" data-company="{cid}">'
            f'<div class="card-header">'
            f'<img src="{logo_url}" onerror="this.style.display=\'none\'" alt="{company}" class="logo">'
            f'<span class="company-name">{company}</span>'
            f'<span class="date">{date}</span>'
            f'</div>'
            f'<div class="title">{j["title"]}</div>'
            f'{loc_html}'
            f'<a href="{j["url"]}" target="_blank" class="apply-btn">View Posting</a>'
            f'</div>'
        )

    n_watched = len(watched_companies)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>2027 Job Tracker</title>
  <style>
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;background:#f5f5f5;color:#111827}}

    header{{background:#fff;border-bottom:1px solid #e5e7eb;padding:18px 32px;display:flex;align-items:center;gap:12px}}
    header h1{{font-size:16px;font-weight:700}}
    .sub{{font-size:13px;color:#6b7280}}
    .updated{{margin-left:auto;font-size:12px;color:#9ca3af}}

    .co-strip{{background:#fff;border-bottom:1px solid #e5e7eb;padding:20px 32px 24px}}
    .co-label{{font-size:11px;font-weight:600;color:#9ca3af;letter-spacing:.07em;text-transform:uppercase;margin-bottom:16px}}
    .co-grid{{display:flex;gap:10px;flex-wrap:wrap}}
    .co-card{{display:flex;flex-direction:column;align-items:center;gap:8px;padding:16px 12px;width:110px;background:#fff;border:1px solid #e5e7eb;border-radius:8px;cursor:pointer;transition:border-color .15s,box-shadow .15s;user-select:none}}
    .co-card:hover{{border-color:#d1d5db;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
    .co-card.active{{border-color:#111827;box-shadow:0 0 0 2px #111827}}
    .co-logo{{width:40px;height:40px;border-radius:8px;object-fit:contain;background:#f9fafb;padding:4px}}
    .co-name{{font-size:12px;font-weight:600;color:#374151;text-align:center;line-height:1.3}}
    .co-count{{font-size:12px;text-align:center}}

    .toolbar{{padding:12px 32px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;border-bottom:1px solid #e5e7eb;background:#fff}}
    .chip{{padding:5px 12px;border-radius:999px;border:1px solid #d1d5db;background:#fff;font-size:12px;color:#374151;cursor:pointer;transition:all .12s}}
    .chip:hover{{border-color:#111827}}
    .chip.active{{background:#111827;color:#fff;border-color:#111827}}
    input[type=search]{{margin-left:auto;padding:6px 12px;border:1px solid #d1d5db;border-radius:6px;font-size:13px;outline:none;width:200px}}
    input[type=search]:focus{{border-color:#111827}}

    .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px;padding:20px 32px 48px}}
    .card{{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:18px;display:flex;flex-direction:column;gap:8px;transition:box-shadow .15s}}
    .card:hover{{box-shadow:0 4px 14px rgba(0,0,0,.07)}}
    .card.hidden{{display:none}}
    .card-header{{display:flex;align-items:center;gap:8px}}
    .logo{{width:18px;height:18px;border-radius:3px;object-fit:contain}}
    .company-name{{font-size:11px;font-weight:600;color:#6b7280;letter-spacing:.06em;text-transform:uppercase;flex:1}}
    .date{{font-size:11px;color:#d1d5db}}
    .title{{font-size:14px;font-weight:600;color:#111827;line-height:1.4}}
    .location{{font-size:12px;color:#9ca3af}}
    .apply-btn{{margin-top:4px;display:inline-block;padding:6px 14px;background:#111827;color:#fff;border-radius:5px;font-size:12px;font-weight:500;text-decoration:none;align-self:flex-start}}
    .apply-btn:hover{{background:#1f2937}}
    #empty{{display:none;padding:48px 32px;text-align:center;color:#9ca3af;font-size:14px}}
  </style>
</head>
<body>
  <header>
    <h1>2027 Job Tracker</h1>
    <span class="sub">New Grad &amp; Intern &nbsp;·&nbsp; <span id="count">{total} postings</span></span>
    <span class="updated">Updated {updated}</span>
  </header>

  <div class="co-strip">
    <div class="co-label">Watching {n_watched} companies</div>
    <div class="co-grid" id="co-grid">{company_tiles}</div>
  </div>

  <div class="toolbar">
    {filter_btns}
    <input type="search" id="search" placeholder="Search roles..." oninput="applyFilters()">
  </div>

  <div class="grid" id="grid">{cards}</div>
  <div id="empty">No matching postings found.</div>

  <script>
    let active = '';
    function filter(c) {{
      if (active === c) c = '';  // click active card to deselect
      active = c;
      document.querySelectorAll('.chip').forEach(el => el.classList.remove('active'));
      document.getElementById('chip-' + (c || 'all')).classList.add('active');
      document.querySelectorAll('.co-card').forEach(el => el.classList.remove('active'));
      if (c) {{ const co = document.getElementById('co-' + c); if (co) co.classList.add('active'); }}
      applyFilters();
    }}
    function applyFilters() {{
      const q = document.getElementById('search').value.toLowerCase();
      let n = 0;
      document.querySelectorAll('.card').forEach(card => {{
        const ok = (!active || card.dataset.company === active) && (!q || card.textContent.toLowerCase().includes(q));
        card.classList.toggle('hidden', !ok);
        if (ok) n++;
      }});
      document.getElementById('count').textContent = n + ' postings';
      document.getElementById('empty').style.display = n ? 'none' : 'block';
    }}
  </script>
</body>
</html>"""


# ── Email ──────────────────────────────────────────────────────────────────────

def build_html(new_jobs, logos, dashboard_url):
    all_jobs = [(company, j) for company, jobs in new_jobs.items() for j in jobs]
    total = len(all_jobs)

    if total == 1:
        company, j = all_jobs[0]
        header_title = f"{short_title(j['title'])} at {company}"
    elif total <= 3:
        header_title = " &nbsp;·&nbsp; ".join(f"{short_title(j['title'])} at {company}" for company, j in all_jobs)
    else:
        companies = list(new_jobs.keys())
        header_title = f"{total} new roles at {', '.join(companies[:3])}{'&hellip;' if len(companies) > 3 else ''}"

    job_cards = ""
    for company, jobs in new_jobs.items():
        cid = logos[company][0] if company in logos else None
        logo_html = (
            f'<img src="cid:{cid}" width="24" height="24" alt="" '
            f'style="border-radius:4px;vertical-align:middle;margin-right:8px;display:inline-block;">'
            if cid else ""
        )
        for j in jobs:
            loc = j["location"] or ""
            loc_row = f'<tr><td style="padding:0 0 12px;font-size:13px;color:#6b7280;">{loc}</td></tr>' if loc else ""
            job_cards += f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:12px;background:#ffffff;border:1px solid #e5e7eb;border-radius:6px;">
      <tr><td style="padding:20px 24px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr><td style="padding:0 0 10px;">
            {logo_html}<span style="font-size:11px;font-weight:600;color:#6b7280;letter-spacing:0.08em;text-transform:uppercase;vertical-align:middle;">{company}</span>
          </td></tr>
          <tr><td style="padding:0 0 8px;font-size:16px;font-weight:600;color:#111827;line-height:1.4;">{j['title']}</td></tr>
          {loc_row}
          <tr><td>
            <a href="{j['url']}" style="display:inline-block;padding:8px 18px;background:#111827;color:#ffffff;border-radius:4px;font-size:13px;font-weight:500;text-decoration:none;letter-spacing:0.01em;">View Posting</a>
          </td></tr>
        </table>
      </td></tr>
    </table>"""

    dashboard_row = f"""
        <tr><td style="padding:20px 0 0;border-top:1px solid #e5e7eb;">
          <a href="{dashboard_url}" style="font-size:13px;color:#6b7280;text-decoration:none;">
            View all tracked postings on the dashboard &rarr;
          </a>
        </td></tr>""" if dashboard_url else ""

    return f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 16px;">
    <tr><td align="center">
      <table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;">
        <tr><td style="padding:0 0 20px;">
          <p style="margin:0 0 4px;font-size:11px;font-weight:600;color:#6b7280;letter-spacing:0.08em;text-transform:uppercase;">Job Alert</p>
          <p style="margin:0;font-size:20px;font-weight:700;color:#111827;line-height:1.3;">{header_title}</p>
        </td></tr>
        <tr><td style="padding:0 0 20px;"><div style="height:1px;background:#e5e7eb;"></div></td></tr>
        <tr><td>{job_cards}</td></tr>
        {dashboard_row}
        <tr><td style="padding:24px 0 0;">
          <p style="margin:0;font-size:12px;color:#9ca3af;">Checks every 30 minutes &nbsp;·&nbsp; Watching for 2027 New Grad &amp; Intern roles</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def build_plain(new_jobs, dashboard_url):
    lines = []
    for company, jobs in new_jobs.items():
        lines.append(f"== {company} ==")
        for j in jobs:
            loc = f" | {j['location']}" if j["location"] else ""
            lines.append(f"  {j['title']}{loc}")
            lines.append(f"  {j['url']}")
        lines.append("")
    if dashboard_url:
        lines.append(f"All postings: {dashboard_url}")
    return "\n".join(lines)


def send_email(cfg, new_jobs, domains=None):
    domains = domains or {}
    all_jobs = [(company, j) for company, jobs in new_jobs.items() for j in jobs]
    total = len(all_jobs)
    if total == 1:
        company, j = all_jobs[0]
        subject = f"{short_title(j['title'])} at {company}"
    elif total <= 3:
        subject = "  ·  ".join(f"{short_title(j['title'])} at {company}" for company, j in all_jobs)
    else:
        first_company, first_job = all_jobs[0]
        subject = f"{short_title(first_job['title'])} at {first_company} + {total - 1} more"

    dashboard_url = cfg.get("dashboard_url", "")
    logos = fetch_logos(list(new_jobs.keys()), domains)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Job Alert Bot <{cfg['email']['from']}>"
    msg["To"] = cfg["email"]["to"]
    msg.attach(MIMEText(build_plain(new_jobs, dashboard_url), "plain"))

    related = MIMEMultipart("related")
    related.attach(MIMEText(build_html(new_jobs, logos, dashboard_url), "html"))
    for company, (cid, img_bytes) in logos.items():
        img = MIMEImage(img_bytes)
        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline")
        related.attach(img)
    msg.attach(related)

    password = os.environ["EMAIL_APP_PASSWORD"]
    with smtplib.SMTP_SSL(cfg["email"]["smtp_host"], cfg["email"]["smtp_port"]) as s:
        s.login(cfg["email"]["from"], password)
        s.send_message(msg)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    test_mode = "--test" in sys.argv
    backfill_mode = "--backfill" in sys.argv
    cfg = load_config()
    domains = {c["name"]: c.get("domain", "") for c in cfg["companies"]}

    if backfill_mode:
        # Re-scan all companies and add any matching jobs to jobs.json/dashboard
        # without touching seen.json or sending email.
        all_matched = load_jobs()
        tracked_ids = {j["id"] for j in all_matched}
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        added = 0
        for company in cfg["companies"]:
            try:
                jobs = fetch_company(company)
            except Exception as e:
                print(f"[warn] {company['name']}: {e}", file=sys.stderr)
                continue
            for job in jobs:
                if job["id"] not in tracked_ids and matches(job, cfg["filters"]):
                    all_matched.insert(0, {
                        "id": job["id"],
                        "company": company["name"],
                        "title": job["title"],
                        "location": job.get("location", ""),
                        "url": job["url"],
                        "seen_at": now,
                    })
                    tracked_ids.add(job["id"])
                    added += 1
        save_jobs(all_matched)
        DASHBOARD_FILE.write_text(build_dashboard(all_matched, domains, cfg["companies"]))
        print(f"Backfill complete — added {added} jobs, dashboard has {len(all_matched)} total.")
        return

    if test_mode:
        fake_jobs = {
            "Stripe": [{"title": "Software Engineer, New Grad 2027", "location": "San Francisco, CA", "url": "https://stripe.com/jobs/example"}],
            "Google": [{"title": "Software Engineer, Early Career 2027", "location": "Mountain View, CA", "url": "https://careers.google.com/jobs/example"}],
        }
        send_email(cfg, fake_jobs, domains)
        print("Test email sent.")
        return

    seen = load_seen()
    all_matched = load_jobs()
    tracked_ids = {j["id"] for j in all_matched}
    first_run = not SEEN_FILE.exists()
    new_jobs = {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

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
                if job["id"] not in tracked_ids:
                    all_matched.insert(0, {
                        "id": job["id"],
                        "company": company["name"],
                        "title": job["title"],
                        "location": job.get("location", ""),
                        "url": job["url"],
                        "seen_at": now,
                    })

    save_seen(seen)
    save_jobs(all_matched)
    DASHBOARD_FILE.write_text(build_dashboard(all_matched, domains, cfg["companies"]))

    if first_run:
        total = sum(len(v) for v in new_jobs.values())
        print(f"First run — baselined {len(seen)} postings ({total} matched). Dashboard generated.")
        return

    if new_jobs:
        send_email(cfg, new_jobs, domains)
        for company, jobs in new_jobs.items():
            for j in jobs:
                print(f"[new] {company}: {j['title']} -> {j['url']}")
    else:
        print("No new matching postings.")


if __name__ == "__main__":
    main()
