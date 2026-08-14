import re
import urllib.parse

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def fetch_greenhouse(company):
    url = f"https://boards-api.greenhouse.io/v1/boards/{company['token']}/jobs"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    jobs = []
    for j in resp.json().get("jobs", []):
        jobs.append({
            "id": f"greenhouse:{company['token']}:{j['id']}",
            "title": j["title"],
            "location": (j.get("location") or {}).get("name", ""),
            "url": j["absolute_url"],
        })
    return jobs


def fetch_lever(company):
    url = f"https://api.lever.co/v0/postings/{company['token']}?mode=json"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    jobs = []
    for j in resp.json():
        jobs.append({
            "id": f"lever:{company['token']}:{j['id']}",
            "title": j["text"],
            "location": (j.get("categories") or {}).get("location", ""),
            "url": j["hostedUrl"],
        })
    return jobs


def fetch_ashby(company):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company['token']}"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    jobs = []
    for j in resp.json().get("jobs", []):
        jobs.append({
            "id": f"ashby:{company['token']}:{j['id']}",
            "title": j["title"],
            "location": j.get("location", ""),
            "url": j.get("jobUrl") or j.get("applyUrl", ""),
        })
    return jobs


def fetch_workday(company):
    base = f"https://{company['host']}/wday/cxs/{company['tenant']}/{company['site']}"
    url = f"{base}/jobs"
    jobs = []
    offset = 0
    while True:
        payload = {
            "appliedFacets": {},
            "limit": 20,
            "offset": offset,
            "searchText": company.get("search", ""),
        }
        resp = requests.post(url, json=payload, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        postings = data.get("jobPostings", [])
        if not postings:
            break
        for j in postings:
            path = j.get("externalPath", "")
            jobs.append({
                "id": f"workday:{company['tenant']}:{path}",
                "title": j.get("title", ""),
                "location": j.get("locationsText", ""),
                "url": (
                    f"https://{company['host']}/en-US/{company['site']}{path}"
                    if path.startswith("/") else f"https://{company['host']}{path}"
                ),
            })
        offset += 20
        if offset >= data.get("total", 0) or offset > 400:
            break
    return jobs


def fetch_google(company):
    """
    Scrapes careers.google.com HTML (server-side rendered).
    Each job listing is a <li class="lLd3Je" ssk='17:{id}'> with the title
    in <h3 class="QJPWVe"> and location in <span class="r0wTof">.
    Paginates via ?pg=N.
    """
    search = urllib.parse.quote_plus(company.get("search", "software engineer"))
    base = f"https://careers.google.com/jobs/results/?q={search}&hl=en&jlo=en-US&location=United+States"
    jobs = []
    seen_ids: set = set()

    for page in range(1, 6):
        url = f"{base}&pg={page}" if page > 1 else base
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        html = resp.text

        # Each job block: ssk='17:<id>'  ...  <h3 class="QJPWVe">Title</h3>
        blocks = re.findall(
            r"ssk='17:(\d+)'.*?<h3 class=\"QJPWVe\">(.*?)</h3>",
            html,
            re.DOTALL,
        )
        if not blocks:
            break

        new_on_page = 0
        for job_id, raw_title in blocks:
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            new_on_page += 1

            title = re.sub(r"<[^>]+>", "", raw_title).strip()
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            url_job = f"https://careers.google.com/jobs/results/{job_id}-{slug}/"

            # Location is in the nearest <span class="r0wTof"> after the title
            idx = html.find(f"ssk='17:{job_id}'")
            block_html = html[idx: idx + 2000]
            loc_match = re.search(r'class="r0wTof">(.*?)</span>', block_html)
            location = re.sub(r"<[^>]+>", "", loc_match.group(1)).strip() if loc_match else ""

            jobs.append({
                "id": f"google:{job_id}",
                "title": title,
                "location": location,
                "url": url_job,
            })

        if new_on_page == 0:
            break

    return jobs


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "workday": fetch_workday,
    "google": fetch_google,
}


def fetch_company(company):
    fetcher = FETCHERS.get(company["type"])
    if not fetcher:
        raise ValueError(f"unknown source type: {company['type']}")
    return fetcher(company)
