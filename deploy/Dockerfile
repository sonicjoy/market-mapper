# Multi-stage: build the mapping-console SPA, then serve it + the control-plane API
# from one uvicorn process (trading-dash pattern).

# --- stage 1: build the SPA ---
FROM node:22-bookworm-slim AS frontend
WORKDIR /fe
COPY console/package.json console/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY console/ ./
RUN npm run build

# --- stage 2: python runtime ---
FROM python:3.13-slim AS runtime
WORKDIR /app
ARG GIT_SHA=dev
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    MAPPING_CP_STATIC_DIR=/app/console/dist \
    MAPPING_CP_BUILD=$GIT_SHA
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY mappers/ ./mappers/
COPY docs/mapping-rules/optic_spine.csv ./docs/mapping-rules/optic_spine.csv
COPY docs/adding-underdog.md ./docs/adding-underdog.md
COPY docs/underdog/udx_markets_golden_2026-09-23.json ./docs/underdog/udx_markets_golden_2026-09-23.json
COPY BigQuery/ ./BigQuery/
# Chat crypto sweep imports fetch.crypto_com_aliases at module load.
COPY fetch/ ./fetch/
COPY synthetic/ ./synthetic/
COPY vendor/ ./vendor/
COPY --from=frontend /fe/dist /app/console/dist
RUN python -c "import mappers.control_plane.app"
EXPOSE 8000
CMD ["uvicorn", "mappers.control_plane.app:app", "--host", "0.0.0.0", "--port", "8000"]
