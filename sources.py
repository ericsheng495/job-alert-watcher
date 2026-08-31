import re
import time
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


def fetch_eightfold(company):
    """Eightfold-hosted boards (Netflix). Public JSON, paginated by `start`.

    The server caps a page at 10 regardless of `num`, so a full board is ~50
    requests; without pacing that trips its rate limit and costs the whole
    company for that cycle.
    """
    host=company["host"]; domain=company["domain"]
    jobs=[]; start=0
    while True:
        url=(f"https://{host}/api/apply/v2/jobs?domain={domain}"
             f"&start={start}&num=50&query={requests.utils.quote(company.get('search',''))}")
        # Eightfold rate-limits paginated scans; back off rather than losing
        # the whole company for this cycle.
        for attempt in range(4):
            r=requests.get(url,headers={**HEADERS,"Accept":"application/json"},timeout=30)
            if r.status_code!=429:
                break
            time.sleep(2*(attempt+1))
        r.raise_for_status(); d=r.json()
        pos=d.get("positions") or []
        if not pos: break
        for p in pos:
            pid=p.get("id")
            jobs.append({"id":f"eightfold:{domain}:{pid}",
                         "title":p.get("name",""),
                         "location":p.get("location") or "; ".join(p.get("locations") or []),
                         "url":p.get("canonicalPositionUrl") or f"https://{host}/careers/job/{pid}"})
        start+=len(pos)
        if start>=int(d.get("count") or 0) or start>600: break
        time.sleep(0.4)          # stay under the rate limit
    return jobs

def fetch_oracle(company):
    """Oracle Recruiting Cloud (Uber). Public hcmRestApi, paginated by offset."""
    host=company["host"]; site=company.get("site_number","CX_1"); path=company["site"]
    jobs=[]; offset=0
    while True:
        url=(f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
             f"?onlyData=true&expand=requisitionList.secondaryLocations"
             f"&finder=findReqs;siteNumber={site},facetsList=LOCATIONS;TITLES;CATEGORIES,"
             f"limit=100,offset={offset},sortBy=POSTING_DATES_DESC")
        r=requests.get(url,headers={**HEADERS,"Accept":"application/json"},timeout=30)
        r.raise_for_status()
        items=r.json().get("items") or []
        rl=items[0].get("requisitionList",[]) if items else []
        total=int(items[0].get("TotalJobsCount") or 0) if items else 0
        if not rl: break
        for j in rl:
            jid=j.get("Id")
            locs=[j.get("PrimaryLocation") or ""]+[s.get("Name","") for s in (j.get("secondaryLocations") or [])]
            jobs.append({"id":f"oracle:{host}:{jid}","title":j.get("Title",""),
                         "location":"; ".join([x for x in locs if x]),
                         "url":f"https://{host}/hcmUI/CandidateExperience/en/sites/{path}/job/{jid}"})
        offset+=len(rl)
        if offset>=total or offset>700: break
    return jobs

JOB_RE=re.compile(
    r'<h3 class="article__header__text__title[^"]*">\s*<a class="link" href="([^"]+/JobDetail/[^"]+)">\s*(.*?)\s*</a>\s*</h3>'
    r'(.*?)</article>', re.S)
TAG=re.compile(r'<[^>]+>')

def fetch_avature(company):
    """Avature-hosted boards (Bloomberg). Server-rendered HTML, paginated by jobOffset."""
    base=company["host"]; jobs=[]; offset=0; seen=set()
    while True:
        url=f"https://{base}/careers/SearchJobs/?jobRecordsPerPage=20&jobOffset={offset}"
        r=requests.get(url,headers=HEADERS,timeout=30); r.raise_for_status()
        found=0
        for m in JOB_RE.finditer(r.text):
            href,title,rest=m.group(1),m.group(2),m.group(3)
            jid=href.rstrip("/").split("/")[-1]
            if jid in seen: continue
            seen.add(jid); found+=1
            sub=re.search(r'article__header__text__subtitle.*?>(.*?)</div>',rest,re.S)
            loc=TAG.sub(" ",sub.group(1)) if sub else ""
            jobs.append({"id":f"avature:{base}:{jid}",
                         "title":TAG.sub("",title).strip(),
                         "location":" ".join(loc.split())[:200],
                         "url":href})
        if found==0 or offset>400: break
        offset+=20
    return jobs


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "workday": fetch_workday,
    "google": fetch_google,
    "eightfold": fetch_eightfold,
    "oracle": fetch_oracle,
    "avature": fetch_avature,
}


def fetch_company(company):
    fetcher = FETCHERS.get(company["type"])
    if not fetcher:
        raise ValueError(f"unknown source type: {company['type']}")
    return fetcher(company)
