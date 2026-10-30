FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CHROME_BINARY_PATH=/usr/bin/chromium \
    CHROMEDRIVER_PATH=/usr/bin/chromedriver \
    SEARCH_DIAGNOSTICS=1 \
    CHROME_NO_SANDBOX=1

# Debian's driver depends on the exact matching chromium package. Apt installs
# the Linux shared-library dependencies too; nothing is downloaded at request time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium chromium-driver ca-certificates \
    && test "$(dpkg-query -W -f='${Version}' chromium)" = "$(dpkg-query -W -f='${Version}' chromium-driver)" \
    && chromium --version \
    && chromedriver --version \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code explicitly so local snapshots and credential files do
# not enter the image, even if the build context contains unrelated local work.
COPY main.py ./
COPY check_database.py ./
COPY config/ ./config/
COPY core/ ./core/
COPY models/ ./models/
COPY retailers/ ./retailers/
COPY services/ ./services/
COPY static/ ./static/
COPY templates/ ./templates/
COPY scripts/start_render.sh ./scripts/start_render.sh
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

# Runs one real browser launch before Gunicorn accepts website requests.
CMD ["sh", "scripts/start_render.sh"]
