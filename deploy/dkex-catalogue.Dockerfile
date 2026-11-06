# dkex-catalogue — fetch.dkex + BigQuery.load_dkex_raw, nothing else.
# fetch.dkex imports mappers.exchanges.dkex (combo test, settlement lag), so
# mappers/ ships too; the import check below fails the build if that grows.
FROM python:3.13-slim
WORKDIR /app
ARG GIT_SHA=dev
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DKEX_CATALOGUE_BUILD=$GIT_SHA
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY mappers/ ./mappers/
COPY BigQuery/ ./BigQuery/
COPY fetch/ ./fetch/
RUN python -c "import fetch.dkex, BigQuery.load_dkex_raw" \
    && useradd --uid 10001 --no-create-home dkex
USER 10001
