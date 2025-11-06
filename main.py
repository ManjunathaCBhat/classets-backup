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
    """
    Triggered by Cloud Scheduler or manual POST.
    Exports 'users' and 'equipment' collections from MongoDB,
    prints data, saves JSON files, optionally uploads to GCS, and sends email.
    """
    date = datetime.now().astimezone().strftime("%Y-%m-%dT%H-%M-%SZ")
    mongo_uri = os.environ["MONGO_URI"]
    bucket = os.environ["BUCKET"]

    count = get_backup_count()
    backup_files = []
    record_counts = {}

    try:
        print(f"🚀 Starting MongoDB backup #{count} ...")

        # Collections to back up
        collections = ["users", "equipment"]

        for col in collections:
            print(f"\n📦 Exporting collection '{col}' ...")

            # Count documents
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

            # Print sample data
            print(f"🧾 Sample data from '{col}':")
            sample_cmd = [
                "mongoexport",
                "--uri", mongo_uri,
                "--collection", col,
                "--jsonArray",
                "--limit", "5"
            ]
            subprocess.run(sample_cmd)

            # Export full collection
            filename = f"mongo_backup_{col}_{date}.json"
            cmd = (
                f"mongoexport --uri='{mongo_uri}' "
                f"--collection={col} --jsonArray | gzip | "
                f"gsutil cp - gs://{bucket}/{filename}.gz"
            )
            subprocess.run(cmd, shell=True, check=True)
            print(f"🧠 Running: {' '.join(export_cmd)}")
            subprocess.run(export_cmd, check=True)
            print(f"✅ Local backup saved: {filename}")

            # Upload to GCS only if not on Windows
            if platform.system() != "Windows":
                upload_cmd = ["gsutil", "cp", filename, f"gs://{bucket}/{filename}"]
                subprocess.run(upload_cmd, check=True)
                print(f"☁️ Uploaded to gs://{bucket}/{filename}")
                backup_files.append(f"gs://{bucket}/{filename}")
            else:
                print(f"💾 Skipping GCS upload (Windows local run). File saved locally: {filename}")
                backup_files.append(filename)

        send_graph_email(success=True, files=backup_files, count=count, record_counts=record_counts)
        increment_backup_count(count)
        print(f"🎉 Backup #{count} completed successfully!")
        return f"Backup #{count} completed successfully\n", 200

    except subprocess.CalledProcessError as e:
        error_msg = str(e)
        print(f"❌ Backup failed: {error_msg}")
        send_graph_email(success=False, error=error_msg, count=count)
        return f"Backup #{count} failed\n", 500


# -----------------------------
# Backup Counter Management
# -----------------------------
def get_backup_count():
    """Return current backup count, starting at 1."""
    if os.path.exists(COUNTER_FILE):
        with open(COUNTER_FILE, "r") as f:
            return int(f.read().strip()) + 1
    return 1


def increment_backup_count(count):
    """Store the new backup count."""
    with open(COUNTER_FILE, "w") as f:
        f.write(str(count))


# -----------------------------
# Microsoft Graph Email Section
# -----------------------------
def get_graph_token():
    """Fetch OAuth2 token for Microsoft Graph API."""
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


def send_graph_email(success=True, files=None, error=None, count=1, record_counts=None):
    """Send HTML email via Microsoft Graph."""
    access_token = get_graph_token()
    sender = os.environ["EMAIL_FROM"]
    recipients = os.environ["EMAIL_TO"].split(",")

    if success:
        subject = f"✅ MongoDB Backup Completed #{count}"
        status_text = f"MongoDB backup #{count} completed successfully."

        count_rows = "".join(
            f"<tr><td style='padding:5px 10px;border:1px solid #ccc;'>{col}</td>"
            f"<td style='padding:5px 10px;border:1px solid #ccc;'>{record_counts.get(col, '0')}</td></tr>"
            for col in record_counts or []
        )

        file_links = "".join(
            f"<li><a href='{f}'>{f}</a></li>" for f in files or []
        )

        details = f"""
        <b>Record Counts:</b><br>
        <table style="border-collapse:collapse;margin-top:10px;">
            <tr><th style='border:1px solid #ccc;padding:5px 10px;'>Collection</th>
                <th style='border:1px solid #ccc;padding:5px 10px;'>Documents</th></tr>
            {count_rows}
        </table>
        <br><b>Backup Files:</b><ul>{file_links}</ul>
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
                Timestamp: {datetime.now().astimezone().isoformat()}
            </p>
            <hr style="margin:25px 0;border-color:#e5e7eb;">
            <p style="text-align:center;font-size:13px;color:#9ca3af;">
                This is an automated message. Please do not reply.
            </p>
        </div>
    </body>
    </html>
    """

    message = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": html_content,
            },
            "toRecipients": [{"emailAddress": {"address": addr.strip()}} for addr in recipients],
        }
    }

    url = f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, json=message)

    if r.status_code < 300:
        print(f"📧 Email sent for backup #{count}")
    else:
        print(f"⚠️ Email failed for backup #{count}: {r.text}")


# -----------------------------
# Debug Route
# -----------------------------
@app.route("/check-tools", methods=["GET"])
def check_tools():
    """Check installed tool versions."""
    mongo = subprocess.getoutput("mongoexport --version")
    gsutil = subprocess.getoutput("gsutil version")
    return f"<pre>{mongo}\n\n{gsutil}</pre>"


# -----------------------------
# Main
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
