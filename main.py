import os
import subprocess
import requests
import platform
from datetime import datetime
from flask import Flask
import schedule
import time
import threading

app = Flask(__name__)

COUNTER_FILE = "/tmp/backup_counter.txt"  # persists on Cloud Run
BACKUP_TIME = "02:00"  # Time of day to run backup (24hr format)


def perform_backup():
    """Main backup logic, used by both API trigger and scheduler."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
    mongo_uri = os.environ["MONGO_URI"]
    bucket = os.environ["BUCKET"]

    folder_name = f"classet-backup-{timestamp}"
    count = get_backup_count()
    backup_files = []
    record_counts = {}

    os.makedirs(folder_name, exist_ok=True)
    print(f"\n🚀 Starting MongoDB backup #{count} at {timestamp}...\n")

    try:
        collections = ["users", "equipment"]

        for col in collections:
            print(f"📦 Exporting collection '{col}' ...")

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
            print(f"📊 Found {record_counts[col]} records in '{col}'")

            # Print sample data
            print(f"🧾 Sample from '{col}':")
            sample_cmd = [
                "mongoexport",
                "--uri", mongo_uri,
                "--collection", col,
                "--jsonArray",
                "--limit", "2"
            ]
            subprocess.run(sample_cmd)

            # Backup file paths
            local_file = os.path.join(folder_name, f"mongo_backup_{col}.json.gz")
            gcs_path = f"gs://{bucket}/{folder_name}/mongo_backup_{col}.json.gz"

            # Export command
            if platform.system() == "Windows":
                export_json = local_file.replace(".gz", "")
                export_cmd = [
                    "mongoexport",
                    "--uri", mongo_uri,
                    "--collection", col,
                    "--jsonArray",
                    "--out", export_json
                ]
                subprocess.run(export_cmd, check=True)
                subprocess.run(["powershell", "Compress-Archive", export_json, local_file])
                print(f"✅ Local backup created: {local_file}")
                backup_files.append(local_file)
            else:
                # Cloud Run (Linux)
                cmd = (
                    f"mongoexport --uri='{mongo_uri}' "
                    f"--collection={col} --jsonArray | gzip | "
                    f"gsutil cp - {gcs_path}"
                )
                subprocess.run(cmd, shell=True, check=True)
                print(f"☁️ Uploaded: {gcs_path}")
                backup_files.append(gcs_path)

        send_graph_email(success=True, files=backup_files, count=count,
                         record_counts=record_counts, folder=folder_name)
        increment_backup_count(count)
        print(f"\n🎉 Backup #{count} completed successfully!\n")

    except subprocess.CalledProcessError as e:
        print(f"❌ Backup failed: {e}")
        send_graph_email(success=False, error=str(e), count=count)


@app.route("/", methods=["POST"])
def manual_trigger():
    """Manual trigger endpoint for Cloud Run."""
    threading.Thread(target=perform_backup).start()
    return "Backup started in background!\n", 200


def get_backup_count():
    if os.path.exists(COUNTER_FILE):
        with open(COUNTER_FILE, "r") as f:
            return int(f.read().strip()) + 1
    return 1


def increment_backup_count(count):
    with open(COUNTER_FILE, "w") as f:
        f.write(str(count))


# -----------------------------
# Email via Microsoft Graph
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


def send_graph_email(success=True, files=None, error=None, count=1,
                     record_counts=None, folder=None):
    access_token = get_graph_token()
    sender = os.environ["EMAIL_FROM"]
    recipients = os.environ["EMAIL_TO"].split(",")

    if success:
        subject = f"✅ MongoDB Backup Completed #{count}"
        status_text = f"Backup #{count} completed successfully."
        count_rows = "".join(
            f"<tr><td style='padding:5px 10px;border:1px solid #ccc;'>{col}</td>"
            f"<td style='padding:5px 10px;border:1px solid #ccc;'>{record_counts.get(col, '0')}</td></tr>"
            for col in record_counts or []
        )
        file_links = "".join(f"<li><a href='{f}'>{f}</a></li>" for f in files or [])
        details = f"""
        <b>Backup Folder:</b> {folder}<br><br>
        <b>Record Counts:</b>
        <table style="border-collapse:collapse;">
            <tr><th>Collection</th><th>Documents</th></tr>{count_rows}
        </table><br>
        <b>Files:</b><ul>{file_links}</ul>
        """
    else:
        subject = f"❌ MongoDB Backup Failed #{count}"
        status_text = f"Backup #{count} failed."
        details = f"<b>Error:</b><pre>{error}</pre>"

    html_content = f"""
    <html><body>
    <h2>IT Asset Management - Backup Notification</h2>
    <p>{status_text}</p>{details}
    <p><small>Timestamp: {datetime.utcnow().isoformat()}Z</small></p>
    </body></html>
    """

    message = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html_content},
            "toRecipients": [{"emailAddress": {"address": addr.strip()}} for addr in recipients],
        }
    }

    url = f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, json=message)

    if r.status_code < 300:
        print(f"📧 Email sent for backup #{count}")
    else:
        print(f"⚠️ Email failed: {r.text}")


# -----------------------------
# Utility: Check tools
# -----------------------------
@app.route("/check-tools", methods=["GET"])
def check_tools():
    mongo = subprocess.getoutput("mongoexport --version")
    gsutil = subprocess.getoutput("gsutil version")
    return f"<pre>{mongo}\n\n{gsutil}</pre>"


# -----------------------------
# Scheduler for local testing
# -----------------------------
def run_scheduler():
    """Runs the daily backup at set time (for local testing)."""
    schedule.every().day.at(BACKUP_TIME).do(perform_backup)
    print(f"🕒 Daily backup scheduled for {BACKUP_TIME} UTC")

    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    import threading

    if platform.system() == "Windows":
        # Local dev: run scheduler + Flask
        threading.Thread(target=run_scheduler, daemon=True).start()
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
    else:
        # Cloud Run: only triggered by Cloud Scheduler
        print("🌩️ Running in Cloud Run mode — waiting for Cloud Scheduler trigger...")
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

