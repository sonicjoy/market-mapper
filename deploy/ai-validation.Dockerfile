# ai-validation — BigQuery.ai_validation, nothing else.
# It imports BigQuery.load_mappings (KEY_COLUMNS), which pulls in mappers/, so
# those ship too; the import check below fails the build if the closure grows
# past what is copied.
FROM python:3.13-slim
WORKDIR /app
ARG GIT_SHA=dev
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    AI_VALIDATION_BUILD=$GIT_SHA
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY mappers/ ./mappers/
COPY BigQuery/ ./BigQuery/
COPY fetch/ ./fetch/
RUN python -c "import BigQuery.ai_validation" \
    && useradd --uid 10001 --no-create-home aival
USER 10001
