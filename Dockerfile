FROM python:3.11-slim

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install curl, gpg, gzip, lsb-release, and certificates
RUN apt-get update && apt-get install -y curl gnupg gzip ca-certificates lsb-release apt-transport-https

# --- Install MongoDB Database Tools (force bookworm repo since trixie not supported yet)
RUN curl -fsSL https://pgp.mongodb.com/server-7.0.asc | gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg] https://repo.mongodb.org/apt/debian bookworm/mongodb-org/7.0 main" \
      | tee /etc/apt/sources.list.d/mongodb-org-7.0.list

# --- Install Google Cloud SDK (gsutil)
RUN echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
      | tee -a /etc/apt/sources.list.d/google-cloud-sdk.list && \
    curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg

# --- Install tools
RUN apt-get update && apt-get install -y mongodb-database-tools google-cloud-sdk && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# --- Setup workdir and copy app
WORKDIR /app
COPY . .

# --- Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# --- Expose Cloud Run port and add gsutil to PATH
ENV PORT=8080 PATH="/root/google-cloud-sdk/bin:${PATH}"

CMD ["python", "main.py"]
