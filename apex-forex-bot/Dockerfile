# APEX FOREX BOT — production image
# Build:  docker build -t apex-forex-bot .
# Run:    docker run -e LICENSE_KEY=FORX-XXXX-XXXX-XXXX -p 3000:3000 apex-forex-bot
FROM python:3.12-slim

# Faster, cleaner Python in containers
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install deps first so Docker layer-caches them across code changes
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Dashboard port (Railway overrides via $PORT at runtime)
EXPOSE 3000

CMD ["python", "main.py"]
