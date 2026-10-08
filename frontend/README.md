# Return ACH Test Engine - Frontend Dashboard

The interactive web dashboard for the **Return ACH Test Engine**. It allows QA engineers, developers, and operators to interactively configure test suites, inspect OpenAPI contracts, execute automated test workflows, and analyze live diagnostics.

---

## Features

- **Target & Endpoint Configuration**:
  - Configure base backend URL (e.g. `http://localhost:8000`) or specific endpoints (e.g. `http://localhost:8000/api/v1/triggers/returned-ach`).
  - Toggle between `Mock` (in-memory fixtures) and `Real` (live external systems) connector modes.
  - Multi-select test suites: `health`, `schema`, `ach_domain`, `security`, `connectors`.
  - Configurable concurrency (1–20) and timeout thresholds (1–60s).

- **Autonomous API Contract Discovery**:
  - Probes reachability and health status.
  - Parses and dereferences OpenAPI specifications into an interactive route table.
  - Displays methods, parameter constraints, authentication requirements (`X-User-Id`), and JSON request schema rules.

- **Real-Time Test Execution & Visual Diagnostics**:
  - Live execution progress indicator.
  - Metric KPI Cards (Total Tests, Passed, Failed, Pass Rate %, Total Latency).
  - Searchable and filterable test results table (filter by status or category).
  - Test Inspector drawer showing:
    - Request method, URL, headers, and formatted JSON body
    - Response status code, latency (ms), and response body
    - Granular assertion outcomes (Status match, Error envelope, Latency SLA)
    - Detailed diff summaries on failures
    - Scoped millisecond wire log traces

- **Multi-Format Report Downloads & History**:
  - **Direct Downloads in Test Results**: One-click download buttons (`⬇ JSON`, `⬇ Markdown (.md)`, `⬇ HTML`) with full test summaries, category breakdown tables, and failure diffs.
  - **Saved Report History**: Browse past test runs, download any historical run directly as JSON (`⬇ JSON`) or Markdown (`⬇ MD`), or click `👁 Load` to inspect past results in the interactive viewer.
  - **Dynamic Markdown Generation**: If only a JSON report is available, the backend automatically compiles the full Markdown report on-the-fly upon download.

---

## Running the Dashboard

### 1. From the Python CLI (Recommended)
You can launch the dashboard directly with zero additional setup:

```bash
cd returned-ach-test-engine
.venv/bin/ach-test ui --port 8080
```
Open **[http://localhost:8080](http://localhost:8080)** in your browser.

### 2. Using npm / pnpm
```bash
cd returned-ach-test-engine/frontend
pnpm start   # or npm start
```

---

## Backend API Endpoints

The frontend communicates with the embedded FastAPI server:

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | `GET` | Health check and engine version |
| `/api/discover` | `POST` | Probes target URL and extracts OpenAPI contracts |
| `/api/run` | `POST` | Executes LangGraph test workflow and exports reports |
| `/api/reports` | `GET` | Lists previous saved reports with JSON and Markdown links |
| `/api/reports/{filename}` | `GET` | Retrieves or downloads report file (`.json`, `.md`, `.html`), with `?download=true` for browser file save |
| `/` | `GET` | Serves the single-page dashboard HTML application |
