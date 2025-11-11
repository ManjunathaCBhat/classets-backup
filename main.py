import os
import subprocess
import requests
import json
import gzip
from datetime import datetime
from pathlib import Path
from flask import Flask
from google.cloud import storage

app = Flask(__name__)
COUNTER_FILE = "/tmp/backup_counter.txt"
TEMP_DIR = "/tmp/mongo_backups"

# Ensure temp directory exists
Path(TEMP_DIR).mkdir(exist_ok=True)

# Initialize GCS client
gcs_client = storage.Client()


@app.route("/", methods=["POST"])
def run_backup():
    """Triggered by Cloud Scheduler every 30 minutes."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
    mongo_uri = os.environ["MONGO_URI"]
    bucket = os.environ["BUCKET"]

    folder_name = f"classet-backup-{timestamp}"
    count = get_backup_count()
    backup_files = []
    record_counts = {}

    try:
        print(f"🚀 Starting MongoDB backup #{count} ...")
        collections = ["users", "equipment"]

        for col in collections:
            print(f"\n📦 Exporting collection '{col}' ...")

            # Step 1: Count records
            count_result = count_collection(mongo_uri, col)
            record_counts[col] = count_result
            print(f"📊 Found {record_counts[col]} documents in '{col}'")

            # Step 2: Export to local file
            local_json_file = os.path.join(TEMP_DIR, f"{col}_{timestamp}.json")
            export_success = export_collection(mongo_uri, col, local_json_file)
            
            if not export_success:
                raise Exception(f"Failed to export collection '{col}'")

            # Verify file has content
            file_size = os.path.getsize(local_json_file)
            print(f"📄 Exported file size: {file_size} bytes")
            
            if file_size == 0:
                raise Exception(f"Exported file for '{col}' is empty!")

            # Step 3: Compress
            compressed_file = f"{local_json_file}.gz"
            compress_file(local_json_file, compressed_file)
            print(f"🗜️ Compressed to: {compressed_file}")

            # Step 4: Upload to GCS
            gcs_path = f"gs://{bucket}/{folder_name}/mongo_backup_{col}.json.gz"
            upload_success = upload_to_gcs(compressed_file, gcs_path)
            
            if not upload_success:
                raise Exception(f"Failed to upload {gcs_path}")

            print(f"☁️ Uploaded: {gcs_path}")
            backup_files.append(gcs_path)

            # Cleanup local files
            os.remove(local_json_file)
            os.remove(compressed_file)

        send_graph_email(success=True, files=backup_files, count=count,
                         record_counts=record_counts, folder=folder_name)
        increment_backup_count(count)
        print(f"🎉 Backup #{count} completed successfully!")
        return f"Backup #{count} completed successfully\n", 200

    except Exception as e:
        error_msg = str(e)
        print(f"❌ Backup failed: {error_msg}")
        send_graph_email(success=False, error=error_msg, count=count)
        return f"Backup #{count} failed: {error_msg}\n", 500


# ----------------------------- Helper functions -----------------------------

def get_backup_count():
    if os.path.exists(COUNTER_FILE):
        with open(COUNTER_FILE, "r") as f:
            return int(f.read().strip()) + 1
    return 1


def increment_backup_count(count):
    with open(COUNTER_FILE, "w") as f:
        f.write(str(count))


def count_collection(mongo_uri, collection):
    """Count documents in a collection using PyMongo."""
    try:
        from pymongo import MongoClient
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        db = client.get_default_database()
        count = db[collection].count_documents({})
        client.close()
        print(f"✅ PyMongo count for {collection}: {count}")
        return str(count)
    except Exception as e:
        print(f"⚠️ Exception counting {collection}: {e}")
        # Fallback to mongosh
        try:
            cmd = [
                "mongosh",
                mongo_uri,
                "--quiet",
                "--eval",
                f"db.{collection}.countDocuments()"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                print(f"⚠️ mongosh error: {result.stderr}")
                return "0"
            
            count = result.stdout.strip()
            return count if count else "0"
        except Exception as e2:
            print(f"⚠️ mongosh also failed: {e2}")
            return "0"


def export_collection(mongo_uri, collection, output_file):
    """Export collection to JSON file."""
    try:
        cmd = [
            "mongoexport",
            f"--uri={mongo_uri}",
            f"--collection={collection}",
            "--jsonArray",
            f"--out={output_file}"
        ]
        
        print(f"🔧 Running: mongoexport --uri=*** --collection={collection} --jsonArray --out={output_file}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        print(f"Return code: {result.returncode}")
        if result.stdout:
            print(f"STDOUT: {result.stdout}")
        if result.stderr:
            print(f"STDERR: {result.stderr}")
        
        if result.returncode != 0:
            print(f"❌ mongoexport error: {result.stderr}")
            return False
        
        # Check if file was created and has content
        if not os.path.exists(output_file):
            print(f"❌ Output file not created: {output_file}")
            return False
        
        file_size = os.path.getsize(output_file)
        print(f"📊 File created: {output_file}, Size: {file_size} bytes")
        
        if file_size == 0:
            print(f"⚠️ Warning: File is empty for collection '{collection}'")
            # Still return True to continue, but log the warning
        
        # Show first 200 chars of file content
        try:
            with open(output_file, 'r') as f:
                preview = f.read(200)
                print(f"📄 File preview: {preview}")
        except:
            pass
        
        print(f"✅ mongoexport succeeded for {collection}")
        return True
    
    except Exception as e:
        print(f"❌ Exception during export: {e}")
        import traceback
        traceback.print_exc()
        return False


def compress_file(input_file, output_file):
    """Compress file using gzip."""
    try:
        with open(input_file, 'rb') as f_in:
            with gzip.open(output_file, 'wb') as f_out:
                f_out.write(f_in.read())
        print(f"✅ File compressed successfully")
        return True
    except Exception as e:
        print(f"❌ Compression error: {e}")
        return False


def upload_to_gcs(local_file, gcs_path):
    """Upload file to Google Cloud Storage using Python client."""
    try:
        # Parse GCS path: gs://bucket/path/to/file
        gcs_path_clean = gcs_path.replace("gs://", "")
        bucket_name, blob_path = gcs_path_clean.split("/", 1)
        
        bucket = gcs_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        
        blob.upload_from_filename(local_file)
        print(f"✅ Upload succeeded: {gcs_path}")
        return True
    
    except Exception as e:
        print(f"❌ Exception during upload: {e}")
        return False


# ----------------------------- Microsoft Graph Email -----------------------------

def get_graph_token():
    tenant = os.environ["AZURE_TENANT_ID"]
    client = os.environ["AZURE_CLIENT_ID"]
    secret = os.environ["AZURE_CLIENT_SECRET"]
    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": client,
        "client_secret": secret,
        "scope": "https://graph.microsoft.com/.default"
    }
    resp = requests.post(token_url, data=data)
    resp.raise_for_status()
    return resp.json()["access_token"]


def send_graph_email(success=True, files=None, error=None,
                     count=1, record_counts=None, folder=None):
    try:
        access_token = get_graph_token()
        sender = os.environ["EMAIL_FROM"]
        recipients = os.environ["EMAIL_TO"].split(",")

        if success:
            subject = f"✅ MongoDB Backup Completed #{count}"
            status_text = f"Backup #{count} completed successfully. Folder: {folder}"

            count_rows = "".join(
                f"<tr><td style='padding:5px 10px;border:1px solid #ccc;'>{col}</td>"
                f"<td style='padding:5px 10px;border:1px solid #ccc;'>{record_counts.get(col, '0')}</td></tr>"
                for col in record_counts or []
            )

            file_links = "".join(f"<li><a href='{f}'>{f}</a></li>" for f in files or [])
            details = f"""
            <b>Backup Folder:</b> {folder}<br><br>
            <b>Record Counts:</b><br>
            <table style="border-collapse:collapse;margin-top:10px;">
                <tr><th style='border:1px solid #ccc;padding:5px 10px;'>Collection</th>
                    <th style='border:1px solid #ccc;padding:5px 10px;'>Documents</th></tr>
                {count_rows}
            </table>
            <br><b>Files:</b><ul>{file_links}</ul>
            """
        else:
            subject = f"❌ MongoDB Backup Failed #{count}"
            status_text = f"MongoDB backup #{count} failed."
            details = f"<b>Error:</b><br><code>{error}</code>"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="UTF-8"></head>
        <body style="font-family:Segoe UI,Tahoma,Geneva,Verdana,sans-serif;">
            <div style="max-width:650px;margin:auto;border:1px solid #e5e7eb;border-radius:8px;padding:25px;">
                <h2 style="color:#4f46e5;">IT Asset Management - Backup Notification</h2>
                <p style="font-size:16px;color:#1f2937;">{status_text}</p>
                <div style="font-size:15px;color:#4b5563;">{details}</div>
                <p style="margin-top:20px;font-size:14px;color:#6b7280;">
                    Timestamp: {datetime.utcnow().isoformat()}Z
                </p>
            </div>
        </body>
        </html>
        """

        message = {
            "message": {
                "subject": subject,
                "body": {"contentType": "HTML", "content": html_content},
                "toRecipients": [{"emailAddress": {"address": addr.strip()}}
                                 for addr in recipients],
            }
        }

        url = f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
        headers = {"Authorization": f"Bearer {access_token}",
                   "Content-Type": "application/json"}
        r = requests.post(url, headers=headers, json=message)
        if r.status_code < 300:
            print(f"📧 Email sent for backup #{count}")
        else:
            print(f"⚠️ Email failed for backup #{count}: {r.text}")
    except Exception as e:
        print(f"⚠️ Email notification failed: {e}")


# ----------------------------- Debug route -----------------------------

@app.route("/check-tools", methods=["GET"])
def check_tools():
    mongo = subprocess.getoutput("mongoexport --version")
    gsutil = subprocess.getoutput("gsutil version")
    return f"<pre>{mongo}\n\n{gsutil}</pre>"


@app.route("/test-backup", methods=["GET", "POST"])
def test_backup():
    """Manual test endpoint for debugging."""
    return run_backup()


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "temp_dir": TEMP_DIR,
        "counter_file": COUNTER_FILE
    }, 200


@app.route("/debug", methods=["GET"])
def debug():
    """Debug endpoint to check environment and tools."""
    try:
        mongo_uri = os.environ.get("MONGO_URI", "NOT SET")
        bucket = os.environ.get("BUCKET", "NOT SET")
        
        # Mask sensitive data
        mongo_uri_masked = mongo_uri[:50] + "***" if mongo_uri != "NOT SET" else "NOT SET"
        
        # Check tools
        mongoexport_version = subprocess.getoutput("mongoexport --version")
        mongosh_version = subprocess.getoutput("mongosh --version")
        
        # Check GCS access
        try:
            buckets = list(gcs_client.list_buckets(max_results=5))
            bucket_names = [b.name for b in buckets]
        except Exception as e:
            bucket_names = f"Error: {str(e)}"
        
        # Check temp directory
        temp_files = os.listdir(TEMP_DIR) if os.path.exists(TEMP_DIR) else "DIR NOT EXISTS"
        
        return {
            "status": "debug info",
            "mongo_uri": mongo_uri_masked,
            "bucket": bucket,
            "mongoexport_version": mongoexport_version,
            "mongosh_version": mongosh_version,
            "gcs_buckets": bucket_names,
            "temp_dir_contents": temp_files,
            "backup_counter": get_backup_count(),
            "timestamp": datetime.utcnow().isoformat()
        }, 200
    except Exception as e:
        return {"error": str(e)}, 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
