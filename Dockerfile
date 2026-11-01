# Civic Agent API + test portal + headless Chromium, for Hugging Face Spaces (Docker).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    HEADLESS=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PORT=7860

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

COPY agent agent
COPY testbed testbed
COPY start.sh .

# Spaces run the container as user 1000; data/ must be writable (checkpoints, receipts, uploads).
RUN useradd -m -u 1000 user && mkdir -p /app/data && chown -R user:user /app /ms-playwright
USER user

EXPOSE 7860
CMD ["bash", "start.sh"]
