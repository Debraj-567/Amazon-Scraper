FROM python:3.11-slim

# Install system dependencies including curl and ca-certificates
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set up a new non-root user with UID 1000 for Hugging Face Spaces
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR $HOME/app

# Install Python requirements
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY --chown=user . .

# Ensure scraped_data directory exists and is writable
RUN mkdir -p scraped_data

# Hugging Face Spaces listens on port 7860
EXPOSE 7860

CMD ["gunicorn", "web_server:app", "--bind", "0.0.0.0:7860", "--workers", "1", "--threads", "8", "--timeout", "120"]
