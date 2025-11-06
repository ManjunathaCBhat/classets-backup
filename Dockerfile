# ---------- Base Image ----------
FROM python:3.11-slim

# Avoid interactive prompts during install
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Kolkata

# ---------- System Dependencies ----------
RUN apt-get update && apt-get install -y \
    curl gnupg gzip ca-certificates apt-transport-https lsb-release build-essential && \
    \
    # ---- Install MongoDB Database Tools ----
    curl -fsSL https://pgp.mongodb.com/server-7.0.asc | gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg] https://repo.mongodb.org/apt/debian bookworm/mongodb-org/7.0 main" \
        | tee /etc/apt/sources.list.d/mongodb-org-7.0.list && \
    apt-get update && apt-get install -y mongodb-database-tools && \
    \
    # ---- Install Google Cloud SDK (includes gsutil) ----
    curl -sSL https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-486.0.0-linux-x86_64.tar.gz -o /tmp/gcloud.tar.gz && \
    tar -xzf /tmp/gcloud.tar.gz -C /opt && \
    /opt/google-cloud-sdk/install.sh --quiet --usage-reporting=false --bash-completion=false --path-update=false && \
    ln -s /opt/google-cloud-sdk/bin/gsutil /usr/local/bin/gsutil && \
    ln -s /opt/google-cloud-sdk/bin/gcloud /usr/local/bin/gcloud && \
    \
    # ---- Cleanup ----
    apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/gcloud.tar.gz

# Add gcloud to PATH
ENV PATH="/opt/google-cloud-sdk/bin:${PATH}"

# ---------- App Setup ----------
WORKDIR /app
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Optional: Health check (Cloud Run auto-heals unhealthy containers)
HEALTHCHECK CMD curl --fail http://localhost:8080/check-tools || exit 1

# Expose Cloud Run port
EXPOSE 8080

# ---------- Start Flask App ----------
CMD ["python", "main.py"]
