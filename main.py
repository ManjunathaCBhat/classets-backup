import os
import subprocess
import requests
import platform
from datetime import datetime
from flask import Flask

app = Flask(__name__)

COUNTER_FILE = "/tmp/backup_counter.txt"  # persists per Cloud Run container


@app.route("/", methods=["POST"])
def run_backup():
    """Triggered by Cloud Scheduler every 30 minutes."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
    mongo_uri = os.environ["MONGO_URI"]
    bucket = os.environ["BUCKET"]

    # Create folder in GCS bucket with date
    folder_name = f"classet-backup-{timestamp}"
    count = get_backup_count()
    backup_files = []
    record_counts = {}

    try:
        print(f"🚀 Starting MongoDB backup #{count} ...")

        collections = ["users", "equipment"]

        for col in collections:
            print(f"\n📦 Exporting collection '{col}' ...")

            # Count records
            count_cmd = [
                "mongosh",
                mongo_uri,
                "--quiet",
                "--eval",
                f"db.{col}.countDocuments()"
            ]
            count_output = subprocess.getoutput(" ".join(count_cmd)).strip()
            record_counts[col] = count_output or "0"
            print(f"📊 Found {record_counts[col]} documents in '{col}' collection")

            # File paths
            gcs_path = f"gs://{bucket}/{folder_name}/mongo_backup_{col}.json.gz"

            # Export collection and upload to GCS folder
            cmd = (
                f"mongoexport --uri='{mongo_uri}' "
                f"--collection={col} --jsonArray | gzip | "
                f"gsutil cp - {gcs_path}"
            )
            subprocess.run(cmd, shell=True, check=True)
            print(f"☁️ Uploaded: {gcs_path}")
            backup_files.append(gcs_path)

        send_graph_email(success=True, files=backup_files, count=count, record_counts=record_counts, folder=folder_name)
        increment_backup_count(count)
        print(f"🎉 Backup #{count} completed successfully!")
        return f"Backup #{count} completed successfully\n", 200

    except subprocess.CalledProcessError as e:
        error_msg = str(e)
        print(f"❌ Backup failed: {error_msg}")
        send_graph_email(success=False, error=error_msg, count=count)
        return f"Backup #{count} failed\n", 500


# -----------------------------
# Counter Management
# -----------------------------
def get_backup_count():
    if os.path.exists(COUNTER_FILE):
        with open(COUNTER_FILE, "r") as f:
            return int(f.read().strip()) + 1
    return 1


def increment_backup_count(count):
    with open(COUNTER_FILE, "w") as f:
        f.write(str(count))


# -----------------------------
# Microsoft Graph Email
# -----------------------------
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


def send_graph_email(success=True, files=None, error=None, count=1, record_counts=None, folder=None):
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
    <html><body style="font-family:Segoe UI,Tahoma,Geneva,Verdana,sans-serif;">
        <div style="max-width:650px;margin:auto;border:1px solid #e5e7eb;border-radius:8px;padding:25px;">
            <h2 style="color:#4f46e5;">IT Asset Management - Backup Notification</h2>
            <p style="font-size:16px;color:#1f2937;">{status_text}</p>
            <div style="font-size:15px;color:#4b5563;">{details}</div>
            <p style="margin-top:20px;font-size:14px;color:#6b7280;">
                Timestamp: {datetime.utcnow().isoformat()}Z
            </p>
        </div>
    </body></html>
    """

    message = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html_content},
            "toRecipients": [{"emailAddress": {"address": addr.strip()}} for addr in recipients],
        }
    }

    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    requests.post(f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail", headers=headers, json=message)


# -----------------------------
# Debug Endpoint
# -----------------------------
@app.route("/check-tools", methods=["GET"])
def check_tools():
    mongo = subprocess.getoutput("mongoexport --version")
    gsutil = subprocess.getoutput("gsutil version")
    return f"<pre>{mongo}\n\n{gsutil}</pre>"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
