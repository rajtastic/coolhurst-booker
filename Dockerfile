FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

ENV COOLHURST_DB_PATH=/data/courts.db
ENV PLAYWRIGHT_HEADLESS=true
ENV SCRAPE_INTERVAL_SECONDS=60

VOLUME ["/data"]

EXPOSE 8080

CMD ["uvicorn", "coolhurst_booker.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
