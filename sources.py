import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (job-alert-watcher)"}


def fetch_greenhouse(company):
    # board token is the slug in boards.greenhouse.io/<token>
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
    # company config needs: host (e.g. nvidia.wd5.myworkdayjobs.com),
    # tenant (e.g. nvidia), site (e.g. NVIDIAExternalCareerSite)
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
                "url": f"https://{company['host']}/en-US/{company['site']}{path.replace('/job', '/job', 1)}"
                       if path.startswith("/") else f"https://{company['host']}{path}",
            })
        offset += 20
        if offset >= data.get("total", 0) or offset > 400:
            break
    return jobs


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "workday": fetch_workday,
}


def fetch_company(company):
    fetcher = FETCHERS.get(company["type"])
    if not fetcher:
        raise ValueError(f"unknown source type: {company['type']}")
    return fetcher(company)
