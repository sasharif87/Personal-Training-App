# Security & Reliability Hardening Plan

This document outlines the strategy for closing existing gaps in the Personal Training App's architecture, preparing the application for a stable, secure, production-ready state on TrueNAS or any Docker environment.

## 1. Identified Gaps & Immediate Fixes

### 1.1 Database Connection Thrashing
- **Problem**: `postgres_client.py` opens and closes a raw TCP connection for every single query via `psycopg2.connect()`. Under load, this causes connection starvation, high latency, and intermittent failures.
- **Solution**: Implement `psycopg2.pool.ThreadedConnectionPool` (or `SimpleConnectionPool`) inside the `PostgresClient` constructor to reuse active connections and drastically improve database resilience.

### 1.2 Weak Credential Fallbacks
- **Problem**: If `POSTGRES_PASSWORD` is entirely omitted, `postgres_client.py` gracefully falls back to an empty string (`""`). 
- **Solution**: Remove the empty string fallback. If the backend is started without database credentials, the application should crash immediately during startup rather than attempting a silent auth failure.

### 1.3 LLM Orchestration Misalignment
- **Problem**: The infrastructure tier (`docker-compose.yml`) defines `OLLAMA_PRIMARY_URL`, `OLLAMA_HEAVY_MODEL`, and `OLLAMA_FAST_MODEL`. However, `llm_client.py` hard-coded its own logic using `OLLAMA_BASE_URL` and `OLLAMA_MODEL`, ignoring the dual-tier design.
- **Solution**: Update `llm_client.py` to correctly map environment variables and utilize the fast model string for daily decisions, saving the 72B parameter heavy model for the monthly planner.

### 1.4 Silent Ingestion Failures
- **Problem**: `ingestion_router.py` wraps the Garmin extraction logic in a blanket `except Exception:`, swallowing potentially critical errors like `ImportError` (if `garth` is missing) or network timeouts, leaving users blind to the root cause.
- **Solution**: Catch explicitly scoped exceptions (`requests.exceptions.RequestException`, `garth.exc.GarthException`) and intentionally alert/log library failures instead of suppressing them.

---

## 2. Additional Recommendations for Review

To elevate the app from merely "working" to "production-grade", the following additions should be implemented:

### 2.1 API Rate Limiting
- **Gap**: The FastAPI instance (`app.py`) is exposed to the local network (or web, if port forwarded) but has no protection against brute-force payload drops.
- **Addition**: Integrate `slowapi` or standard async rate-limiting on endpoints like `/save` and `/api/health-data` to prevent resource exhaustion attacks.

### 2.2 Docker Log Rotation
- **Gap**: `docker-compose.yml` does not specify logging constraints. By default, Docker writes to a boundless JSON file, which can gradually consume the TrueNAS operating drive.
- **Addition**: Add `logging` blocks to all services in `docker-compose.yml` to cap logs at `max-size: "10m"` and `max-file: "3"`.

### 2.3 Daemon Health Checks
- **Gap**: While the `postgres` and `influxdb` containers have internal `healthcheck` testing, the `coaching-app` container (running `main.py --daemon`) does not. If the apscheduler thread dies, Docker won't restart it.
- **Addition**: Implement a tiny health-check file or script for the `coaching-app` container to regularly prove the scheduler thread is still ticking.

### 2.4 DB Backup Strategy
- **Gap**: Postgres and Influx are writing to local volumes, but there's no automated internal backup.
- **Addition**: Create a weekly `pg_dump` job that pushes a backup into the `/data/garmin` or `/data/logs` folder, so that TrueNAS snapshots capture a portable `.sql` dump of the entire structured dataset.

---

## 3. API & Frontend Gaps

### 3.1 SPA Authentication Lockout
- **Gap**: The backend strictly requires the `X-API-Key` header on all `/api/*` routes. However, `frontend/src/api/client.js` **never attaches this header**. This means the frontend Single Page Application is completely broken out of the box because every data fetch will result in a `401 Unauthorized`.
- **Addition**: Add a lightweight login/bootstrap component to the Vite Frontend that prompts the user for the API key, stores it securely in `localStorage`, and injects it into all subsequent `fetch` calls.

### 3.2 Unminified Raw Frontend Serving
- **Gap**: The `Dockerfile` and `docker-compose.yml` do not compile the frontend. FastAPI manually mounts the raw `/src` directory to serve the frontend as raw unbundled ES modules. This is a severe anti-pattern in production—it requires the browser to make dozens/hundreds of independent HTTP requests to load the app and exposes the raw source code.
- **Addition**: Update the `Dockerfile` to use a multi-stage build. Run `npm run build` using a Node container, then copy the strictly compiled `/dist` footprint into the final Python container, updating FastAPI to serve `/dist` as static assets.
- **Status (partial)**: `vite.config.js` added; frontend restructured into proper ES modules with `npm run build` support. Dockerfile multi-stage step still needed: add a `FROM node:20-slim AS frontend` stage that runs `npm ci && npm run build`, then COPY `frontend/dist` into the Python image and update `app.py` to mount `/dist` instead of `/src`.

### 3.3 Missing Security Headers
- **Gap**: The FastAPI gateway does not enforce any security headers. The app is vulnerable to clickjacking (missing `X-Frame-Options`) and lacks a Content Security Policy (CSP), meaning a hijacked dependency or XSS flaw could silently connect to external servers.
- **Addition**: Implement a global middleware in `app.py` (e.g., using Starlette's `BaseHTTPMiddleware` or `secure` library) to inject strict HTTP security headers: `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options: DENY`, and a fundamental `Content-Security-Policy`.
