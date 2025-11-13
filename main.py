import os
import subprocess
import requests
import json
import gzip
import logging
from datetime import datetime
from pathlib import Path
from google.cloud import storage
import functions_framework

# Setup logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configuration
COUNTER_FILE = "/tmp/backup_counter.txt"
TEMP_DIR = "/tmp/mongo_backups"
Path(TEMP_DIR).mkdir(parents=True, exist_ok=True)

# Initialize GCS client
gcs_client = storage.Client()


@functions_framework.http
def mongodb_backup(request):
    """
    HTTP Cloud Function triggered by Cloud Scheduler.
    Performs MongoDB backup and sends email notification.
    """
    try:
        logger.info("🚀 Starting MongoDB backup job...")
        
        # Validate environment variables
        required_vars = ["MONGO_URI", "BUCKET", "EMAIL_FROM", "EMAIL_TO"]
        missing_vars = [var for var in required_vars if not os.environ.get(var)]
        
        if missing_vars:
            error_msg = f"Missing environment variables: {', '.join(missing_vars)}"
            logger.error(error_msg)
            return {"status": "failed", "error": error_msg}, 400
        
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
        mongo_uri = os.environ["MONGO_URI"]
        bucket = os.environ["BUCKET"]
        
        count = get_backup_count()
        backup_files = []
        record_counts = {}
        
        logger.info(f"📦 Backup #{count} starting at {timestamp}")
        
        collections = ["users", "equipment", "equipment_history", "equipment_status_periods"]
        
        for col in collections:
            logger.info(f"Processing collection: {col}")
            
            # Count documents
            record_counts[col] = count_collection(mongo_uri, col)
            logger.info(f"Found {record_counts[col]} documents in '{col}'")
            
            # Export to local file
            local_json_file = os.path.join(TEMP_DIR, f"{col}_{timestamp}.json")
            if not export_collection(mongo_uri, col, local_json_file):
                logger.warning(f"Export failed for '{col}', skipping...")
                continue
            
            # Verify file has content
            file_size = os.path.getsize(local_json_file)
            if file_size == 0:
                logger.warning(f"Exported file for '{col}' is empty, skipping...")
                os.remove(local_json_file)
                continue
            
            logger.info(f"Exported file size: {file_size} bytes")
            
            # Compress file
            compressed_file = f"{local_json_file}.gz"
            if not compress_file(local_json_file, compressed_file):
                logger.error(f"Compression failed for '{col}'")
                continue
            
            # Upload to GCS
            gcs_path = f"gs://{bucket}/mongo_backup_{col}_{timestamp}.json.gz"
            if upload_to_gcs(compressed_file, gcs_path):
                logger.info(f"Uploaded: {gcs_path}")
                backup_files.append(gcs_path)
            else:
                logger.error(f"Failed to upload {gcs_path}")
            
            # Cleanup local files
            cleanup_files([local_json_file, compressed_file])
        
        # Send email notification
        if backup_files:
            try:
                send_email_notification(
                    success=True,
                    files=backup_files,
                    count=count,
                    record_counts=record_counts,
                    folder=timestamp
                )
            except Exception as e:
                logger.error(f"Email notification failed: {e}", exc_info=True)
            
            increment_backup_count(count)
            logger.info(f"✅ Backup #{count} completed successfully!")
            return {
                "status": "success",
                "backup_number": count,
                "files": backup_files,
                "timestamp": timestamp
            }, 200
        else:
            error_msg = "No files were successfully backed up"
            logger.error(error_msg)
            
            try:
                send_email_notification(success=False, error=error_msg, count=count)
            except Exception as e:
                logger.error(f"Failed to send error email: {e}")
            
            return {"status": "failed", "error": error_msg}, 500
    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Backup failed: {error_msg}", exc_info=True)
        
        try:
            send_email_notification(success=False, error=error_msg, count=get_backup_count())
        except Exception as email_error:
            logger.error(f"Failed to send error email: {email_error}")
        
        return {"status": "failed", "error": error_msg}, 500


# ======================== Helper Functions ========================

def get_backup_count():
    """Get current backup count from counter file."""
    try:
        if os.path.exists(COUNTER_FILE):
            with open(COUNTER_FILE, "r") as f:
                return int(f.read().strip())
        return 1
    except Exception as e:
        logger.error(f"Error reading backup count: {e}")
        return 1


def increment_backup_count(count):
    """Increment and save backup counter."""
    try:
        with open(COUNTER_FILE, "w") as f:
            f.write(str(count + 1))
    except Exception as e:
        logger.error(f"Error incrementing backup count: {e}")


def count_collection(mongo_uri, collection):
    """Count documents in a collection using PyMongo."""
    try:
        from pymongo import MongoClient
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        db = client.get_default_database()
        count = db[collection].count_documents({})
        client.close()
        logger.info(f"PyMongo count for {collection}: {count}")
        return str(count)
    except Exception as e:
        logger.warning(f"Exception counting {collection}: {e}")
        return "0"


def export_collection(mongo_uri, collection, output_file):
    """Export collection to JSON file using mongoexport."""
    try:
        cmd = [
            "mongoexport",
            f"--uri={mongo_uri}",
            f"--collection={collection}",
            "--jsonArray",
            f"--out={output_file}"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode != 0:
            logger.error(f"mongoexport error: {result.stderr}")
            return False
        
        if not os.path.exists(output_file):
            logger.error(f"Output file not created: {output_file}")
            return False
        
        file_size = os.path.getsize(output_file)
        logger.info(f"File created: {output_file}, Size: {file_size} bytes")
        
        return True
    
    except Exception as e:
        logger.error(f"Exception during export: {e}", exc_info=True)
        return False


def compress_file(input_file, output_file):
    """Compress file using gzip."""
    try:
        with open(input_file, 'rb') as f_in:
            with gzip.open(output_file, 'wb') as f_out:
                f_out.write(f_in.read())
        logger.info(f"File compressed successfully: {output_file}")
        return True
    except Exception as e:
        logger.error(f"Compression error: {e}")
        return False


def upload_to_gcs(local_file, gcs_path):
    """Upload file to Google Cloud Storage."""
    try:
        gcs_path_clean = gcs_path.replace("gs://", "")
        bucket_name, blob_path = gcs_path_clean.split("/", 1)
        
        bucket = gcs_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        
        blob.upload_from_filename(local_file)
        logger.info(f"Upload succeeded: {gcs_path}")
        return True
    
    except Exception as e:
        logger.error(f"Exception during upload: {e}", exc_info=True)
        return False


def cleanup_files(files):
    """Remove local temporary files."""
    for file_path in files:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleaned up: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup {file_path}: {e}")


# ======================== Email Notification ========================

def get_graph_token():
    """Get Microsoft Graph API access token."""
    tenant = os.environ.get("AZURE_TENANT_ID")
    client = os.environ.get("AZURE_CLIENT_ID")
    secret = os.environ.get("AZURE_CLIENT_SECRET")
    
    if not all([tenant, client, secret]):
        raise ValueError("Azure credentials not configured")
    
    if any(x in ["none", "skip", "your_"] for x in [tenant, client, secret]):
        raise ValueError("Azure credentials contain placeholder values")
    
    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": client,
        "client_secret": secret,
        "scope": "https://graph.microsoft.com/.default"
    }
    
    resp = requests.post(token_url, data=data, timeout=10)
    resp.raise_for_status()
    return resp.json()["access_token"]


def send_email_notification(success=True, files=None, error=None,
                           count=1, record_counts=None, folder=None):
    """Send email notification via Microsoft Graph API."""
    try:
        access_token = get_graph_token()
        sender = os.environ.get("EMAIL_FROM")
        recipients = [r.strip() for r in os.environ.get("EMAIL_TO", "").split(",") if r.strip()]
        
        if not sender or not recipients:
            logger.warning("Email credentials not configured, skipping email")
            return
        
        if success:
            subject = f"✅ MongoDB Backup Completed #{count}"
            status_text = f"Backup #{count} completed successfully. Folder: {folder}"
            
            count_rows = "".join(
                f"<tr><td style='padding:8px;border:1px solid #ddd;'>{col}</td>"
                f"<td style='padding:8px;border:1px solid #ddd;text-align:right;'>{record_counts.get(col, '0')}</td></tr>"
                for col in sorted(record_counts or [])
            )
            
            file_links = "".join(f"<li style='margin:5px 0;'>{f}</li>" for f in files or [])
            
            details = f"""
            <strong>Backup Folder:</strong> <code>{folder}</code><br><br>
            <strong>Record Counts:</strong><br>
            <table style="border-collapse:collapse;margin-top:10px;width:100%;">
                <tr style="background-color:#f3f4f6;">
                    <th style="border:1px solid #ddd;padding:8px;text-align:left;">Collection</th>
                    <th style="border:1px solid #ddd;padding:8px;text-align:right;">Documents</th>
                </tr>
                {count_rows}
            </table>
            <br><strong>Files:</strong><ul>{file_links}</ul>
            """
        else:
            subject = f"❌ MongoDB Backup Failed #{count}"
            status_text = f"MongoDB backup #{count} failed."
            details = f"<strong>Error:</strong><br><code style='background-color:#fee;padding:10px;border-radius:4px;'>{error}</code>"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="UTF-8"></head>
        <body style="font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background-color:#f9fafb;">
            <div style="max-width:650px;margin:20px auto;border:1px solid #e5e7eb;border-radius:8px;padding:30px;background-color:white;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
                <h2 style="color:#4f46e5;margin-top:0;margin-bottom:10px;">IT Asset Management - Backup Notification</h2>
                <hr style="border:none;border-top:2px solid #e5e7eb;margin:15px 0;">
                <p style="font-size:16px;color:#1f2937;margin:15px 0;">{status_text}</p>
                <div style="font-size:14px;color:#4b5563;margin:20px 0;line-height:1.6;">{details}</div>
                <hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0;">
                <p style="margin:10px 0;font-size:12px;color:#9ca3af;">
                    <strong>Timestamp:</strong> {datetime.utcnow().isoformat()}Z
                </p>
            </div>
        </body>
        </html>
        """
        
        message = {
            "message": {
                "subject": subject,
                "body": {"contentType": "HTML", "content": html_content},
                "toRecipients": [{"emailAddress": {"address": addr}} for addr in recipients],
            }
        }
        
        url = f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        
        resp = requests.post(url, headers=headers, json=message, timeout=10)
        
        if resp.status_code < 300:
            logger.info(f"Email sent successfully for backup #{count}")
        else:
            logger.error(f"Email failed for backup #{count}: {resp.text}")
    
    except Exception as e:
        logger.error(f"Email notification failed: {e}", exc_info=True)
