# Swimplex

A decision support tool for optimized swim and dive lineups at SCIAC championships using integer programming.

Developed by the **MuddOR Lab** (PI: Professor Susan Martonosi) with student researchers **Tyler Headley** and **Edward Donson**, in collaboration with the **Claremont-Mudd-Scripps Swim and Dive** team.

---

## Overview

Swimplex scrapes Hy-Tek meet result PDFs from each SCIAC school's schedule page, parses them into structured data, and exposes everything through a coach-facing web UI. The goal is to give coaches a data-driven tool to construct optimal lineups for SCIAC championships — maximizing expected team points subject to SCIAC entry constraints, while accounting for how rival teams are likely to respond.

## How it works

1. **Scrape** — downloads Hy-Tek PDF result files from each school's Sidearm Sports page
2. **Parse** — extracts structured swim results (athlete, event, time, school) from PDFs using coordinate-based column detection
3. **Process** — builds event rankings, athlete profiles, and season-best performances per athlete
4. **Optimize** — integer programming model finds the point-maximizing lineup for a given team, with iterative best-response against selected rivals
5. **Web UI** — Flask app ties all four steps together; coaches can review data, run the model, and explore the recommended lineup in-browser

## Quick start

```bash
pip install -r requirements.txt
```

### Run the web app (recommended)
```bash
python3 web/app.py
# open http://localhost:5001
```

### CLI pipeline
```bash
# Scrape PDFs from all SCIAC school pages
python3 main.py --scrape [--season 2025-26]

# Parse PDFs into results.json
python3 main.py --parse [--season 2025-26]

# Build rankings and best performances
python3 pipeline/process_results.py --season 2025-26 --gender Men
python3 pipeline/process_results.py --season 2025-26 --gender Women
python3 pipeline/best_performances.py --season 2025-26 --gender Men
python3 pipeline/best_performances.py --season 2025-26 --gender Women

# Run data quality checks
python3 pipeline/data_quality.py --season 2025-26
```

## Project layout

```
pipeline/   # Scraping, parsing, and data processing
web/        # Flask backend + single-page coach UI
model/      # Integer programming model + iterative best-response solver
data/       # Output data by season (PDFs, JSON, CSV)
```

See [`pipeline/README.md`](pipeline/README.md) for details on the scraping, parsing, and data processing scripts; [`web/README.md`](web/README.md) for the Flask backend architecture, API reference, and technical caveats; and [`model/README.md`](model/README.md) for the integer programming model and iterative best-response algorithm.
