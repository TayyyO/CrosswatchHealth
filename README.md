# CrossWatch Health

CrossWatch links FDA medical device safety data (MAUDE adverse events, recalls, enforcement reports) with supply data (the FDA Medical Device Shortages List and GUDID device identifiers) by product code. It scores each device category every month and flags the categories where safety and supply problems are building at the same time.

CrossWatch Health is an independent research and development project led by Qasim T. Arigbabu. It is not a company and does not sell products or services. It uses public data only.

> Report counts are not rates. MAUDE is a passive reporting system. A CrossWatch score is a prompt for expert review, not a finding that a device is unsafe, a shortage forecast, or purchasing advice.

## What is in this repository

| Path | What it is |
|---|---|
| `index.html` | Project landing page |
| `prototype/index.html` | Interactive prototype: ranked categories, category detail, retrospective test, method and run log |
| `data/runs/YYYY-MM.json` | Each published scoring run, with its scores, notes and warnings |
| `data/latest.json` | A copy of the newest run. The landing page reads this file |
| `data/runs.json` | One entry per scoring month, for the month selector and run history |
| `data/snapshot-YYYY-MM.json` | The raw data pulled for each scoring month |
| `data/shortage_list.json` | Shortage list status per product code, captured by hand from the FDA page |
| `pipeline/fetch_openfda.py` | Pulls a new snapshot from openFDA |
| `pipeline/score.py` | Reference implementation of the Risk Scoring Specification v0.1 |
| `pipeline/build_latest.py` | Checks a snapshot, scores it and publishes it to `data/latest.json` |
| `pipeline/check_shortage_page.py` | Checks whether FDA has updated the shortage list page |
| `.github/workflows/monthly-refresh.yml` | The monthly automated refresh |
| `LICENSE`, `NOTICE` | Apache License 2.0 and attribution |

The site is plain HTML with no build step. Fonts load from Google Fonts.

## Deploy

The site is static, so any static host works.

### GitHub Pages

1. Push this folder to a GitHub repository.
2. In the repository, open **Settings > Pages**, choose **Deploy from a branch**, select `main` and `/ (root)`, and save.
3. The landing page is served at `https://<user>.github.io/<repo>/` and the prototype at `/prototype/`.

### Netlify or Vercel

Import the repository with no build command and the repository root as the output directory.

## Review note generator

Each category page can generate a short review note. The generator runs in the browser from fixed rules, with no external API:

- It restates why the category scored as it did, from the computed signals.
- It sorts recall reasons into themes (sterility and contamination, air in the blood path, leaks and connections, labeling and materials, component or manufacturing defects, performance, software and access, kit components recalled elsewhere) by keyword.
- It lists what to check next: a possible summary-report spike, Class I recall notices, death and injury narratives, or which labelers are still shipping.

It is deterministic, so the same data always gives the same note. The roadmap replaces the keyword rules with a trained text classifier for recall reasons and MAUDE narratives in Phase 2, evaluated against the rule-based version.

## Monthly data refresh

A GitHub Action refreshes the data automatically on the 5th of each month. It scores the month two months back (the December 5 run scores October), so late adverse event reports have time to arrive.

Each run:

1. Pulls adverse events, severity counts, recalls, recall classes and labeler counts from openFDA (`pipeline/fetch_openfda.py`).
2. Checks the pull and refuses to publish if any request failed, a month is missing, or past counts changed by more than 30% compared with the published run (`pipeline/build_latest.py`).
3. Scores every category and writes the month's run file (`data/runs/YYYY-MM.json`), updates `data/latest.json` and `data/runs.json`, and keeps the raw snapshot.
4. Commits the new data. Netlify redeploys automatically when the repository is linked to the Netlify site.
5. Checks FDA's shortage list page. If FDA has updated it since `data/shortage_list.json` was captured, it opens a GitHub issue with the steps to update the file.

### Viewing past months

The prototype opens on the newest run. The **Scoring month** menu in its header switches to any earlier run, and a banner shows when a past month is on screen. Each month has its own link, for example `prototype/?month=2026-10`, and it works with category pages too (`prototype/?month=2026-10#knw`). Past runs keep the scores, notes and warnings exactly as they were published, so earlier results can always be checked.

Rescoring an older month by hand replaces that month's run file and leaves the newest run as the default.

### One-time setup

1. **Allow the workflow to push.** In the repository, open **Settings > Actions > General > Workflow permissions** and select **Read and write permissions**.
2. **Add an openFDA API key (recommended).** Request a free key at https://open.fda.gov/apis/authentication/, then add it under **Settings > Secrets and variables > Actions** as `OPENFDA_API_KEY`. Without a key the run still works, but with lower rate limits.
3. **Confirm Netlify deploys from GitHub.** In Netlify, the site's **Site configuration > Build & deploy** should show the repository as the source. A site deployed by drag and drop does not update itself.
4. **Run it once by hand.** Open the **Actions** tab, choose **Monthly data refresh**, select **Run workflow**, and enter `2026-10`. Compare the result with the September run on the prototype's Method page.

### When something needs attention

- **The run fails.** GitHub emails the repository owner. The live site keeps the last good run, because nothing is published until the checks pass. The log in the Actions tab names the failed check.
- **An issue says the shortage list changed.** Update `data/shortage_list.json` from the FDA page (list dates, any new product codes and `capture_date`), commit, then run the workflow again for the latest scoring month.
- **To rescore a past month,** run the workflow by hand with that month.

### Run it locally

```bash
OPENFDA_API_KEY=... python pipeline/fetch_openfda.py 2026-10
python pipeline/build_latest.py data/snapshot-2026-10.json
python pipeline/score.py data/snapshot-2026-10.json
```

The prototype page also contains the September 2026 data, which it shows if `data/latest.json` cannot be loaded, for example when the file is opened directly from disk.

## Review note generator

Each category page can generate a short review note. The generator runs in the browser from fixed rules, with no external API:

- It restates why the category scored as it did, from the computed signals.
- It sorts recall reasons into themes (sterility and contamination, air in the blood path, leaks and connections, labeling and materials, component or manufacturing defects, performance, software and access, kit components recalled elsewhere) by keyword.
- It lists what to check next: a possible summary-report spike, Class I recall notices, death and injury narratives, or which labelers are still shipping.

It is deterministic, so the same data always gives the same note. The roadmap replaces the keyword rules with a trained text classifier for recall reasons and MAUDE narratives in Phase 2, evaluated against the rule-based version.

## Refresh the data

```bash
# 1. Update data/shortage_list.json from the live FDA Shortages List page
# 2. Pull a new snapshot (an openFDA key raises the daily limit)
OPENFDA_API_KEY=... python pipeline/fetch_openfda.py 2026-10
# 3. Check the scores
python pipeline/score.py data/snapshot-2026-10.json
```

The prototype currently embeds the September 2026 data in `prototype/index.html` (the `CATS` object). After a refresh, copy the new categories into that object, or change the page to load the JSON file.

`fetch_openfda.py` uses the same queries that produced the committed snapshot, but it has not yet been run end to end against the live API. On its first run, compare its output with `data/snapshot-2026-09.json`.

## Method in brief

Five signals, each compared with the category's own history and scored using only data available at the time:

| Signal | Family | Elevated when |
|---|---|---|
| S1 Adverse event trend | Safety | Last 3 months at least 2 standard deviations above the prior 24, and at least 5 reports a month |
| S2 Severity mix | Safety | Death and injury share up at least 10 points, with at least 5 such reports |
| S3 Recall activity | Safety | Any Class I recall in 12 months, or a weighted count of 4 or more |
| S4 List status | Supply | On the shortage list (1.0), discontinuance list (0.6), or removed in the last 12 months (0.4) |
| S5 Supply concentration | Supply | Few labelers in commercial distribution |

```
Safety = 0.5 x S1 + 0.2 x S2 + 0.3 x S3
Supply = 0.6 x S4 + 0.4 x S5
Score  = 100 x (0.5 x Safety + 0.5 x Supply)
```

Tiers: High (60 or more, or convergence), Elevated (35 to 59), Watch (15 to 34), Low (below 15). Convergence is raised when both subscores are at least 0.5 in the same month.

### Implementation choices to confirm

- S1 and S2 components are 0 below threshold, then the value divided by twice the threshold, capped at 1. An elevated signal therefore starts at 0.5.
- S1 switches to a Poisson test when the baseline mean is below 10 reports a month.
- Recall class comes from enforcement reports joined on the event number. Unresolved events use the "unknown" weight of 2.
- S5 uses current GUDID labeler counts. The 12-month drop adjustment needs archived GUDID releases.

### Known gaps

- With S4 excluded in the retrospective test, the supply subscore can reach at most 0.4, so convergence cannot be raised in a prediction test. The specification needs a no-S4 rule or a time-varying S5.
- S2 is not yet part of the monthly back-test.
- The control comparison against never-listed product codes has not been run.
- MDB covers all blood culturing systems, not only BD BACTEC bottles, and its removal date from the shortage list is unconfirmed.
- The FJK listing date is known to the month only.

## Data sources

- openFDA device adverse events: https://open.fda.gov/apis/device/event/
- openFDA device recalls: https://open.fda.gov/apis/device/recall/
- openFDA device enforcement reports: https://open.fda.gov/apis/device/enforcement/
- openFDA device UDI (GUDID): https://open.fda.gov/apis/device/udi/
- FDA Medical Device Shortages List: https://www.fda.gov/medical-devices/medical-device-supply-chain-and-shortages/medical-device-shortages-list

openFDA data is provided by FDA without validation and is subject to the openFDA terms of service: https://open.fda.gov/terms/

## License

Code in this repository is licensed under the Apache License 2.0. See `LICENSE` and `NOTICE`. FDA data retrieved through openFDA is in the public domain.

## Contact

Qasim T. Arigbabu, crosswatchhealth@gmail.com, [LinkedIn](https://www.linkedin.com/in/qasim-arigbabu-580b69152/)

Practitioners in device quality, regulatory affairs and hospital supply chain are welcome to review the method and send written feedback.
