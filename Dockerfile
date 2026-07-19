FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

# Pin Playwright to the browser revision shipped in this base image.
RUN pip install --no-cache-dir . "playwright==1.61.0"

ENV COOLHURST_DB_PATH=/data/courts.db
ENV PLAYWRIGHT_HEADLESS=true
ENV SCRAPE_INTERVAL_SECONDS=60

VOLUME ["/data"]

EXPOSE 8080

CMD ["uvicorn", "coolhurst_booker.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
