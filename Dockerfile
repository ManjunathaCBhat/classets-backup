FROM python:3.11-slim

# Install MongoDB Database Tools + Google Cloud SDK (gsutil)
RUN apt-get update && apt-get install -y curl gnupg gzip ca-certificates lsb-release apt-transport-https \
 && curl -fsSL https://pgp.mongodb.com/server-7.0.asc | gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg] https://repo.mongodb.org/apt/debian $(lsb_release -cs)/mongodb-org/7.0 main" \
    | tee /etc/apt/sources.list.d/mongodb-org-7.0.list \
 && echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
    | tee -a /etc/apt/sources.list.d/google-cloud-sdk.list \
 && curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg \
 && apt-get update && apt-get install -y mongodb-database-tools google-cloud-sdk \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# Set workdir and copy app
WORKDIR /app
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose port and set PATH for gsutil
ENV PORT=8080 PATH="/root/google-cloud-sdk/bin:${PATH}"

CMD ["python", "main.py"]
