FROM python:3.11-slim

# Disable interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install MongoDB database tools and base utilities
RUN apt-get update && apt-get install -y curl gnupg gzip ca-certificates lsb-release apt-transport-https unzip && \
    # --- MongoDB tools (force bookworm repo) ---
    curl -fsSL https://pgp.mongodb.com/server-7.0.asc | gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg] https://repo.mongodb.org/apt/debian bookworm/mongodb-org/7.0 main" \
      | tee /etc/apt/sources.list.d/mongodb-org-7.0.list && \
    apt-get update && apt-get install -y mongodb-database-tools && \
    # --- Lightweight gsutil install (no apt repo needed) ---
    curl -sSL https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-486.0.0-linux-x86_64.tar.gz -o /tmp/gcloud.tar.gz && \
    tar -xzf /tmp/gcloud.tar.gz -C /opt && \
    /opt/google-cloud-sdk/install.sh -q && \
    ln -s /opt/google-cloud-sdk/bin/gsutil /usr/local/bin/gsutil && \
    rm -rf /var/lib/apt/lists/* /tmp/gcloud.tar.gz

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -r requirements.txt

ENV PORT=8080 PATH="/opt/google-cloud-sdk/bin:${PATH}"

CMD ["python", "main.py"]
