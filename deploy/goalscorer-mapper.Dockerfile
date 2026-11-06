# goalscorer-mapper — one image for the Slack bot Deployment and the three CronJobs.
# Entrypoint is the goalscorer CLI; each workload passes its subcommand as args.
FROM python:3.13-slim
WORKDIR /app
ARG GIT_SHA=dev
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    GOALSCORER_BUILD=$GIT_SHA
COPY goalscorer/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY BigQuery/client.py ./BigQuery/client.py
COPY goalscorer/ ./goalscorer/
RUN python -c "import goalscorer.__main__, goalscorer.bot, goalscorer.pnl" \
    && useradd --uid 10001 --no-create-home goalscorer
USER 10001
ENTRYPOINT ["python", "-m", "goalscorer"]
CMD ["--help"]
