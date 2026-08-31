# job-alert-watcher

Polls company job boards every 30 minutes, filters titles for 2027 new grad /
winter / spring roles, and emails you the apply link for anything new.

No server, no scraping headaches — it hits the public JSON APIs behind
Greenhouse, Lever, Ashby, and Workday boards, and runs on a free GitHub
Actions cron.

## Setup (~10 min)

1. **Create a private GitHub repo** and push these files.

2. **Gmail app password** (needed because Gmail blocks plain password SMTP):
   - Google Account → Security → 2-Step Verification (must be on)
   - Security → App passwords → create one for "Mail"
   - In the repo: Settings → Secrets and variables → Actions →
     New repository secret → name `EMAIL_APP_PASSWORD`, paste the 16-char password

3. **Edit `config.yaml`**:
   - Set `email.from` / `email.to` to your Gmail
   - Add/remove companies (see below)
   - Tune the include/exclude regexes

4. **First run**: Actions tab → job-watch → Run workflow. The first run
   baselines every posting currently live and sends nothing — after that,
   only genuinely new matches trigger an email.

## Adding a company

Find which platform hosts their jobs — open their careers page and check the
URL of an actual posting:

| Posting URL looks like            | type       | token/config                          |
|-----------------------------------|------------|---------------------------------------|
| `boards.greenhouse.io/acme/...`   | greenhouse | `token: acme`                          |
| `job-boards.greenhouse.io/acme`   | greenhouse | `token: acme`                          |
| `jobs.lever.co/acme/...`          | lever      | `token: acme`                          |
| `jobs.ashbyhq.com/acme/...`       | ashby      | `token: acme`                          |
| `acme.wd5.myworkdayjobs.com/...`  | workday    | `host`, `tenant`, `site` from the URL |
| `explore.jobs.acme.net/...`       | eightfold  | `host`, `domain`                       |
| `*.fa.ocs.oraclecloud.com/...`    | oracle     | `host`, `site` (CandidateExperience site name) |
| `acme.avature.net/careers/...`    | avature    | `host`                                 |

Workday URL anatomy: `https://<host>/en-US/<site>/job/...` and the tenant is
usually the subdomain (e.g. `nvidia.wd5.myworkdayjobs.com` → tenant `nvidia`).

Companies with fully custom career sites (Google, Meta, Apple, Amazon) need
their own adapters — add a fetcher to `sources.py` returning
`{id, title, location, url}` dicts and register it in `FETCHERS`.

## Local test

```bash
pip install -r requirements.txt
EMAIL_APP_PASSWORD=xxxx python watch.py
```

Delete `seen.json` to reset the baseline.

## Scan latency

GitHub throttles *scheduled* workflows heavily — a `*/10` cron in practice
fires every 2-8 hours, so the cron alone cannot deliver 10-minute alerts.
Each run therefore stays alive and scans on its own timer: `LOOP_SCANS`
(default 6) scans, 10 minutes apart, committing after each one. The cron
just restarts the loop, and the `job-watch` concurrency group keeps at most
one run active with one queued behind it.

To go tighter, trigger `workflow_dispatch` from an external cron
(cron-job.org, or any box you control) with a PAT — GitHub does not throttle
dispatched runs the way it throttles `schedule`.
