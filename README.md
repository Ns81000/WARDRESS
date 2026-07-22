<p align="center">
  <img src="assets/brand/wardress-logo.svg" alt="Wardress" width="128">
</p>

<h1 align="center">Wardress</h1>

<p align="center">
  <strong>Self-hosted website defacement detection and automated response orchestration.</strong><br>
  Nine distinct detection layers, dynamic risk fusion, multi-channel alerting, and guarded remediation — fully localized on your own infrastructure.
</p>

<p align="center">
  <img src="https://img.shields.io/github/license/Ns81000/WARDRESS?style=for-the-badge&color=2e7d32" alt="License">
  <img src="https://img.shields.io/badge/python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/react-19-61DAFB?style=for-the-badge&logo=react&logoColor=black" alt="React 19">
  <img src="https://img.shields.io/badge/tailwind-v4-38B2AC?style=for-the-badge&logo=tailwind-css&logoColor=white" alt="Tailwind v4">
  <img src="https://img.shields.io/badge/FastAPI-0.139-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/docker-%3E%3D24-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker">
</p>

<p align="center">
  <a href="https://wardress.mintlify.site/introduction">
    <img src="https://img.shields.io/badge/Read%20The%20Docs-View%20Documentation-blue?style=for-the-badge&logo=mintlify&logoColor=white" alt="Read the documentation">
  </a>
</p>

---

## Overview

**Wardress** is a production-grade, self-hosted security tool built to protect website integrity. It captures and freezes a trusted **baseline** of your target website (DOM structure, network references, visual layout, and textual semantics) and continuously monitors the site for malicious defacements, script injections, metadata tampering, and domain hijacking. 

Unlike simple page monitors, Wardress uses a **fused risk model** that aggregates results from 9 independent detection layers to calculate a single, highly accurate risk score. This filters out false positives caused by minor dynamic elements while raising immediate alarms when a site has been compromised.

---

## Installation Guide (`install.ps1`)

Wardress provides automated PowerShell installation scripts for Windows hosts running Docker Desktop. You can run the setup in a single command without cloning the repository manually first.

### Prerequisites
*   **Operating System**: Windows 10 or 11 (64-bit).
*   **Virtualization**: [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed with the **WSL 2 backend** activated and running.
*   **Hardware**: At least 6 GB of free disk space (to store backend, database, and Chromium browser containers).

> [!IMPORTANT]
> Ensure Docker Desktop is running before launching the installation command. The installer will query the Docker daemon and fail if it cannot connect.

### One-Command Quick Start

Choose one of the following commands, paste it into PowerShell, and hit Enter. The commands automatically handle cloning/downloading, directory navigation, and script execution:

*   **Option A: No-Git Installation (ZIP Download)**
    *Use this if you do not have Git installed. It downloads the repository ZIP archive, extracts it, and executes the installer:*
    ```powershell
    Invoke-WebRequest -Uri "https://github.com/Ns81000/WARDRESS/archive/refs/heads/main.zip" -OutFile "wardress.zip"; Expand-Archive "wardress.zip" -DestinationPath "."; cd WARDRESS-main; powershell -ExecutionPolicy Bypass -File scripts\install.ps1
    ```

*   **Option B: Git-Based Installation**
    *Use this if you have Git installed. It clones the repository and starts the installer:*
    ```powershell
    git clone https://github.com/Ns81000/WARDRESS.git; cd WARDRESS; powershell -ExecutionPolicy Bypass -File scripts\install.ps1
    ```

*Optional Parameter*: You can override the default administrator email during installation by running the script manually with the `-AdminEmail` flag:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -AdminEmail security@yourdomain.com
```

### What the Installer Does (Behind the Scenes)

```mermaid
sequenceDiagram
    participant OS as PowerShell Script
    participant Docker as Docker Engine
    participant DB as Postgres & Redis
    participant App as FastAPI App
    
    OS->>Docker: 1. Confirm Docker engine & Compose plugin are running
    OS->>OS: 2. Parse .env.example & generate .env with cryptographically random secrets
    OS->>Docker: 3. Rebuild app, worker, and beat images serially in the foreground
    OS->>Docker: 4. Spin up PostgreSQL and Redis containers
    OS->>App: 5. Execute database migrations (Alembic upgrade head)
    OS->>Docker: 6. Spin up API, worker, and beat containers
    OS->>App: 7. Wait for live endpoint, then seed the first admin user
    OS->>OS: 8. Create a Desktop shortcut using WScript.Shell and assets/brand/wardress.ico
    OS->>OS: 9. Display the generated admin email and password (exactly once)
```

1.  **Environment Setup**: Creates your `.env` configuration file from `.env.example`. It automatically swaps placeholder tags with cryptographically secure random strings for the PostgreSQL database password, JWT secret, Fernet credentials key, and the admin password.
2.  **Serial Container Builds**: Builds the primary services (`app`, `worker`, `beat`) sequentially to prevent high CPU or RAM spikes on standard workstations.
3.  **Database Migration**: Starts Postgres and Redis and executes Alembic database upgrades to build the relational schemas.
4.  **Admin Seeding**: Seeds the database with your admin account (`admin@example.com` or your custom address).
5.  **Desktop Integration**: Hooks into Windows Script Host to create a desktop shortcut named **Wardress.lnk** that opens `http://localhost:8321` and references the official application icon.
6.  **Admin Summary**: Displays the generated administrator password.

> [!WARNING]
> **The generated admin credentials are shown exactly once** during first installation. They are stored locally in your `.env` file (`ADMIN_PASSWORD`) and are not saved or transmitted anywhere else. Keep your `.env` file secure.

Once completed, log into **[http://localhost:8321](http://localhost:8321)** using the printed credentials.

---

## Update Guide (`update.ps1`)

To update Wardress to the latest release while maintaining all database records, baselines, and configuration parameters, use the update script.

### How to Update

*   **For Git Checkouts**:
    Open PowerShell in the `WARDRESS` folder and run the updater. It will pull new code and rebuild the stack:
    ```powershell
    powershell -ExecutionPolicy Bypass -File scripts\update.ps1
    ```
*   **For Non-Git Checkouts (ZIP Downloads)**:
    If you downloaded the code as a ZIP archive (meaning no `.git` folder exists), you can update Wardress by simply downloading the new ZIP, extracting it, replacing the old files (your databases, configurations, and baselines are safely preserved in Docker volumes and your local `.env`), and running the script with the `-NoGitPull` switch:
    ```powershell
    powershell -ExecutionPolicy Bypass -File scripts\update.ps1 -NoGitPull
    ```

### What the Updater Does (Behind the Scenes)
1.  **Code Check**: Performs a fast-forward Git pull (`git pull --ff-only`) if a git remote is active.
2.  **Changelog**: Reads and prints the first 40 lines of `CHANGELOG.md` to inform you of recent changes.
3.  **Container Upgrades**: Rebuilds the application and worker images using the `--pull` parameter to grab base updates, sharing local cache layers where possible.
4.  **Database Migrations**: Runs Alembic migrations to apply any structural changes to the database.
5.  **Force Re-Creation**: Restarts the services. It specifically passes the `--force-recreate` flag to the Celery Beat and Telegram-bot containers.

> [!NOTE]
> Re-creating the Celery Beat scheduler container is mandatory. Since it shares images with the worker container, Docker Compose would otherwise ignore image updates and keep running the old code in Celery Beat.

6.  **Liveness Verification**: Monitors `/api/health/live` for 120 seconds to confirm services are online and responding.

---

## Table of Contents
- [Overview](#overview)
- [Installation Guide (`install.ps1`)](#installation-guide-installps1)
- [Update Guide (`update.ps1`)](#update-guide-updateps1)
- [System Features & Heuristics](#system-features--heuristics)
- [System Architecture](#system-architecture)
- [The 9-Layer Detection Pipeline](#the-9-layer-detection-pipeline)
  - [Gating and Optimizations](#gating-and-optimizations)
  - [Pipeline Breakdown](#pipeline-breakdown)
- [Visual Walkthrough](#visual-walkthrough)
- [Uninstall Guide](#uninstall-guide)
- [Configuration Reference (`.env`)](#configuration-reference-env)
- [Role-Based Access Control (RBAC)](#role-based-access-control-rbac)
- [API Reference](#api-reference)
- [Security Features](#security-features)
- [Development and Testing](#development-and-testing)
- [License](#license)

---

## System Features & Heuristics

*   **Adaptive Cadence Scanning**: To conserve bandwidth and computational power, Wardress dynamically scales its monitoring frequencies. If a scan crosses the material change threshold (`fused_risk >= 0.15`), the scan interval tightens to **1/4th** of the site's configured base interval (clamped at a minimum of 5 minutes). As long as subsequent scans remain stable, the interval relaxes by **1.5x** per clean run until it settles back at the base interval (up to 24 hours).
*   **Guarded Remediation Hooks**: Flagged scans can trigger outbound webhooks (e.g. rollback endpoints or maintenance pages). By default, all hooks require manual confirmation (`requires_manual_confirm=true`). Executions park in the confirmation queue and will not fire until explicitly approved by an operator. A webhook endpoint timeout of 20 seconds is enforced, and execution tasks are isolated in a separate Celery queue so that slow/broken endpoints never block the scan engine.
*   **AI Incident Assistant Cache**: The plain-English analysis of an incident is generated via a structured prompt built from active layer evidence (such as DOM tag additions, visual similarity scores, and metadata differences) and requested from Gemini or a local Ollama model. The final description is cached directly in the `scans` table column to eliminate duplicate API requests.

---

## System Architecture

Wardress is modularly designed as a set of containerized services coordinated via **Docker Compose**:

```mermaid
graph TD
    User([Security Operator]) <--> |HTTPS / Port 8321| SPA[React 19 Frontend SPA]
    TelegramUser([Telegram Bot Interface]) <--> |Polling / Direct Chat| TelegramBot[Telegram Bot Worker]
    
    SPA <--> |REST API / JWT Auth| API[FastAPI Web Server]
    TelegramBot <--> |Internal API Calls| API
    
    API <--> |Transactions / States| DB[(PostgreSQL 16)]
    API <--> |Task Queuing / Cache| Redis[(Redis Key-Value Cache)]
    
    Beat[Celery Beat Dispatcher] --> |Schedule Scans| Redis
    Worker[Celery Task Worker] <--> |Poll Tasks| Redis
    
    Worker <--> |Read / Write| DB
    Worker --> |Playwright Headless Chrome| TargetSite([Monitored Websites])
    Worker --> |Apprise / SMTP| AlertService([Alerting Integrations])
    Worker --> |Webhooks| Remediation([Remediation Endpoints])
```

- **Frontend SPA**: React 19 single-page application built with Vite and styled using Tailwind CSS v4. Includes visual diffing elements, full audit logs, and interactive controls.
- **FastAPI Web Server**: High-performance asynchronous REST API that implements JWT session management, RBAC, and cryptographically hashed API keys.
- **Celery & Redis**: An asynchronous task execution engine. **Celery Beat** schedules periodic probes, while **Celery Workers** perform parallel scans, alert dispatches, and webhooks.
- **Playwright / Chromium Worker**: A headless browser instance running within the Celery worker that executes full DOM compilation, resource tracking, and screenshot captures.

---

## The 9-Layer Detection Pipeline

Each scan drives the target page through 9 specialized analysis layers designed to catch different defacement styles.

### Gating and Optimizations
To preserve system resources and prevent false alarms from dynamic rendering variations, the pipeline implements **intelligent gating rules**:
*   **Layer 1 (Content Hash) Gating**: If the byte-level hash of the page is identical to the baseline, the engine skips Layers 2, 3, 4, 5, and 8. If nothing changed at the byte level, DOM trees, text semantics, visual pixels, and signatures are guaranteed to be identical.
*   **Persistent Probes**: Layers 6 (Security Metadata) and 7 (Cloaking) run on *every* scan. TLS cert details, response headers, and UA-rotated fetches are invisible to the primary DOM content hash and could indicate high-impact MITM attacks or crawler-specific cloaking.
*   **Crash Isolation**: Each layer is isolated inside try/except enclosures. A parser failure in one layer records the error as evidence, assigns a `None` score, and allows the remaining eight layers to continue functioning.

### Pipeline Breakdown

| Layer | Stable Key | Input Scope | Core Detection Heuristics |
| :--- | :--- | :--- | :--- |
| **1. Content Hash** | `layer1_hash` | Original HTML | SHA-256 over conservatively normalized HTML. Binary `0.0`/`1.0` result. |
| **2. DOM Structure** | `layer2_dom_structure` | Suppressed HTML | Inspects structural tree depth, element counts, script tags, iframe insertions, and style attributes that force element hiding. |
| **3. Link Audit** | `layer3_link_audit` | Suppressed HTML | Audits newly introduced external hyperlinks, stylesheets, script references, and HTML form target domains. |
| **4. Visual Diff** | `layer4_visual_diff` | Screenshot | SSIM (`scikit-image`, weighted 0.7) plus pHash + dHash (`imagehash`, weighted 0.3) on downscaled, bbox-masked grayscale captures. |
| **5. Signatures** | `layer5_signatures` | New visible text | Scans newly added visible text for defacement keywords ("hacked by", "owned by"), profanity frequency, and dominant Unicode script changes (e.g. Latin to Cyrillic/Arabic). |
| **6. Security Metadata** | `layer6_security_metadata` | Network headers | Audits TLS certificate validity, fingerprints (distinguishes CA reissues from subject shifts), security header policies (HSTS, CSP, CORS), and `robots.txt` changes. |
| **7. Cloaking** | `layer7_cloaking` | HTTP variant fetches | Rotates the User-Agent (Googlebot, Mobile Safari, Desktop Chrome) and compares raw HTML content similarities to identify content cloaked specifically for search engines. |
| **8. Text Semantics** | `layer8_semantics` | Suppressed text | Computes the sentence embeddings of visible text using a local **MiniLM-L6-v2** neural network, measuring semantic cosine distance from the baseline. |
| **9. Risk Fusion** | `layer9_fusion` | Fused inputs | A deterministic seed-fitted **logistic regression** (`scikit-learn`) fuses the eight sub-scores into one calibrated **0.0–1.0 risk score**. |

---

## Visual Walkthrough

### 1. Secure Access Portal
An authentication interface enforcing session durations and strict server-side rate limits.
![Authentication Screen](docs/screenshots/login.png)

### 2. Main Site Directory
The central operations deck showing configured sites, active alerts, current status, and quick-action run keys.
![Sites Dashboard](docs/screenshots/sites.png)

### 3. Site Detail Panel
Per-site configuration dashboard where operators manage baselines, schedule scanning intervals, and define flag thresholds.
![Site Detail](docs/screenshots/site-detail.png)

### 4. Primary Scan Report & Visual Diff
Shows side-by-side screenshot comparisons with pixel-level highlights marking changed visual regions.
![Scan Report Visual Diff](docs/screenshots/scan-report-visual-diff.png)

### 5. DOM Structural Comparison
Highlights tag alterations, script inclusions, and iframe injections directly within the HTML tree.
![Scan Report DOM Structure](docs/screenshots/scan-report-dom.png)

### 6. Semantic and Header Analytics
Shows the exact differences in HTTP response headers, SSL certificates, outgoing link profiles, and semantic embeddings.
![Scan Report Analytics](docs/screenshots/scan-report-analytics.png)

### 7. AI Incident Assistant
Leverages Gemini or local Ollama models to translate deep cryptographic and technical diff signatures into plain-English incident summaries.
![Incident Assistant](docs/screenshots/assitant.png)

### 8. Alerts Registry
A historical timeline of all triggered alerts, displaying delivery logs, channel pathways, and dispatcher statuses.
![Alerts Logs](docs/screenshots/alerts.png)

### 9. System Audit Logs
A immutable ledger tracking every system change, user access, settings update, and remediation action. Sensitive credentials and secrets are automatically redacted.
![Audit Logs](docs/screenshots/audit.png)

### 10. Integrations & System Settings
Consolidated interface to configure SMTP channels, Telegram bot credentials, AI keys, and role-based API tokens.
![Settings Configuration](docs/screenshots/settings.png)

### 11. Diagnostic System Health
Real-time health statistics charting Celery queue depth, worker heartbeats, and average scan execution throughput.
![Health Indicators](docs/screenshots/health.png)

---

## Uninstall Guide

### Automated removal with backup (`uninstall.ps1`)

The simplest way to remove Wardress is the uninstall script. It **backs up everything
recoverable first** — your `.env`, a logical PostgreSQL dump (`pg_dump`), and the scan-artifacts
volume — to a timestamped folder next to the repository, and only then removes all Wardress
containers, the network, the data volumes, and the locally-built images. Each backup folder also
gets a `RESTORE.txt` with exact restore commands.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1
```

The script prompts for confirmation and prints the backup location when it finishes. Useful flags:

*   `-SkipBackup` — remove everything without taking a backup (permanent data loss).
*   `-Force` — skip the confirmation prompt (for unattended teardown).
*   `-KeepImages` — remove containers and volumes but keep the built images (faster reinstall).
*   `-PruneBaseImages` — also remove the pulled upstream base images (Postgres, Redis, and the
    build bases). By default these shared, reusable images are kept so a reinstall is fast; pass
    this for a full-footprint wipe.
*   `-BackupPath <dir>` — write the backup to a specific folder instead of the default.

> [!NOTE]
> `docker compose down --rmi local` (used internally) only removes the images Wardress **built**
> locally. The base images pulled from registries (e.g. `postgres`, `redis`, the Playwright and
> `uv` build bases) are intentionally left behind for reuse — use `-PruneBaseImages` to remove
> those as well.

> [!CAUTION]
> The uninstall script removes the data volumes. With the default backup you can restore later
> via the generated `RESTORE.txt`; with `-SkipBackup` the deletion is permanent.

The repository files on disk are left in place — delete the folder yourself if you also want the
source gone.

### Manual removal

To stop and remove Wardress by hand with Docker Compose directly:

1. Stop the active container stack (this preserves the database volume and your scan history):
   ```bash
   docker compose down
   ```
2. **OR** stop the stack and completely delete all stored data volumes:
   ```bash
   docker compose down -v
   ```

> [!CAUTION]
> Running `docker compose down -v` permanently deletes all database records and screenshot baselines. Back up your `.env` configuration file if you plan to reinstall later.

3. Delete the repository folder and the desktop shortcut. No extra system files are created outside this path.

---

## Configuration Reference (`.env`)

These environment variables are written to `.env` during installation.

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `WARDRESS_HTTP_PORT` | `8321` | The local port the FastAPI server and React dashboard bind to. |
| `PUBLIC_BASE_URL` | `http://localhost:8321` | The root URL used in email and Telegram alert linkages. |
| `POSTGRES_USER` | `wardress` | Database username. |
| `POSTGRES_PASSWORD` | *generated* | Cryptographically random database password. |
| `DATABASE_URL` | *generated* | Database connection string containing the generated password. |
| `JWT_SECRET` | *generated* | HS256 signing key for JWT bearer access tokens (validated at startup to be >= 32 bytes). |
| `CREDENTIALS_ENCRYPTION_KEY` | *generated* | A Fernet key used to encrypt SMTP and API integration credentials at rest. |
| `ADMIN_EMAIL` | `admin@example.com` | Default email for the first administrator. |
| `ADMIN_PASSWORD` | *generated* | The seeded administrator password. |
| `GEMINI_API_KEY` | *empty* | Optional. API key for Gemini models to generate incident explanations. |
| `GEMINI_MODEL` | `gemini-flash-latest` | The model variation used for explaining incidents. |
| `ENABLE_OLLAMA` | `false` | Set to `true` to start the local-LLM container for offline AI explanations. |
| `TELEGRAM_BOT_TOKEN` | *empty* | Optional. Telegram bot token for interactive system queries. |
| `RATE_LIMIT_PER_IP` | `300` | Pre-auth API rate limits per client IP per window. Set to `0` to disable. |
| `RATE_LIMIT_PER_USER` | `240` | Post-auth rate limits per authenticated user account. |
| `RATE_LIMIT_WINDOW_SECONDS`| `60` | Time window length for rate-limit evaluations. |
| `TRUST_PROXY_HEADERS` | `false` | Enable this *only* if Wardress is fronted by a reverse proxy. |
| `COOKIE_SECURE` | `false` | Forces session cookies to be transmitted via HTTPS only. |

---

## Role-Based Access Control (RBAC)

Wardress implements strict role enforcement across all endpoints.

| Access Permission | Admin | Analyst | Viewer |
| :--- | :---: | :---: | :---: |
| Read sites, scan records, alerts, system health, and PDF reports | ✓ | ✓ | ✓ |
| Add/modify sites, execute manual scans, rebaseline pages, and add suppression rules | ✓ | ✓ | — |
| Acknowledge alerts, handle manual remediation confirmation queues | ✓ | ✓ | — |
| Manage personal API keys | ✓ | ✓ | ✓ |
| Configure system settings, SMTP properties, and AI API integrations | ✓ | — | — |
| Create or modify remediation webhooks | ✓ | — | — |
| Perform user management operations and inspect system audit logs | ✓ | — | — |

---

## API Reference

Interactive OpenAPI documentation is available locally at **`http://localhost:8321/docs`**.

### Authenticating API Requests
1.  Navigate to **Settings → API Keys** in the dashboard.
2.  Generate a new API Token (tokens follow the `wk_...` prefix format and are displayed only once).
3.  Include this token in the `Authorization` header of your HTTP requests:
    ```bash
    curl -H "Authorization: Bearer wk_your_api_key_here" http://localhost:8321/api/sites
    ```

---

## Security Features

*   **SSRF Protection & Redirect Validation**: Monitored scan targets must resolve to public IP addresses by default. Probing internal, loopback, or link-local targets (`127.0.0.1`, `192.168.x.x`) is blocked unless explicitly enabled via the per-site configuration flag `allow_private_networks`. To prevent SSRF bypasses via open redirects or DNS rebinding, redirect locations are checked hop-by-hop before fetching.
*   **ReDoS Protection in Suppression Engine**: When filtering dynamic parts of pages using Regex-based suppression rules, the regex parser enforces a strict **2.0 second timeout limit** (`_REGEX_TIMEOUT_SECONDS`) on match evaluations to safeguard worker nodes against Catastrophic Backtracking Denial of Service attacks.
*   **Fernet Encryption at Rest**: Integration secrets (like SMTP passwords, Telegram bot tokens, API keys, and Apprise Webhook URLs) are encrypted in the PostgreSQL database using a Fernet key (`CREDENTIALS_ENCRYPTION_KEY`). They are never exposed via the API.
*   **Hashed API Keys**: API keys are stored in the database as SHA-256 hashes. If the database is compromised, the actual API tokens cannot be decrypted.
*   **Audit Logging**: The system records every administrative change, settings edit, user creation, and manual remediation step. Sensitive variables and secrets are automatically redacted from the audit history.

---

## Development and Testing

The backend is built with **FastAPI** and managed via **uv**. The frontend is built with **React 19** and managed via **pnpm**.

### Backend Development
Run migrations and execute the unit-test suite (uses an in-memory SQLite database via `aiosqlite` so no Postgres instance is required):
```bash
cd backend
uv sync
uv run pytest
```

### Frontend Development
Install dependencies, run component-level tests, check types, and run the linter:
```bash
cd frontend
pnpm install
pnpm test
pnpm exec tsc --noEmit
pnpm exec oxlint src
```

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for the full text.
