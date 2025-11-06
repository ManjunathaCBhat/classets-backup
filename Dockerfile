# Use Python as base image
FROM python:3.11-slim

# Install dependencies: curl, MongoDB tools, and gsutil
RUN apt-get update && apt-get install -y curl gnupg gzip && \
    curl -fsSL https://pgp.mongodb.com/server-7.0.asc | gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg] https://repo.mongodb.org/apt/debian bookworm/mongodb-org/7.0 main" \
        | tee /etc/apt/sources.list.d/mongodb-org-7.0.list && \
    apt-get update && apt-get install -y mongodb-database-tools && \
    curl -sSL https://sdk.cloud.google.com | bash && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Add gsutil to PATH
ENV PATH="/root/google-cloud-sdk/bin:${PATH}"

# Set working directory
WORKDIR /app

# Copy project files
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose Cloud Run port
ENV PORT=8080

# Run Flask app
CMD ["python", "main.py"]
