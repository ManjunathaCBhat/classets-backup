FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install required tools (MongoDB + gsutil)
RUN apt-get update && apt-get install -y \
    curl gnupg gzip ca-certificates apt-transport-https lsb-release unzip && \
    \
    # Install MongoDB Database Tools
    curl -fsSL https://pgp.mongodb.com/server-7.0.asc | gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg] https://repo.mongodb.org/apt/debian bookworm/mongodb-org/7.0 main" \
        | tee /etc/apt/sources.list.d/mongodb-org-7.0.list && \
    apt-get update && apt-get install -y mongodb-database-tools && \
    \
    # Install Google Cloud SDK (includes gsutil)
    curl -sSL https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-486.0.0-linux-x86_64.tar.gz -o /tmp/gcloud.tar.gz && \
    tar -xzf /tmp/gcloud.tar.gz -C /opt && \
    /opt/google-cloud-sdk/install.sh --quiet && \
    ln -s /opt/google-cloud-sdk/bin/gsutil /usr/local/bin/gsutil && \
    ln -s /opt/google-cloud-sdk/bin/gcloud /usr/local/bin/gcloud && \
    \
    # Cleanup
    apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/gcloud.tar.gz

ENV PATH="/opt/google-cloud-sdk/bin:${PATH}"

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8080
CMD ["python", "main.py"]
