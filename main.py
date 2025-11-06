import os
import subprocess
import requests
from datetime import datetime
from flask import Flask

app = Flask(__name__)

COUNTER_FILE = "/tmp/backup_counter.txt"  # persists per Cloud Run container

@app.route("/", methods=["POST"])
def run_backup():
    """Triggered by Cloud Scheduler every 30 minutes"""
    date = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
    mongo_uri = os.environ["MONGO_URI"]
    bucket = os.environ["BUCKET"]

    # Read and update counter
    count = get_backup_count()

    try:
        print(f"🚀 Starting MongoDB backup #{count} ...")

        # Export both 'users' and 'equipment' collections
        for collection in ["users", "equipment"]:
            filename = f"mongo_backup_{collection}_{date}.json.gz"
            cmd = (
                f"mongoexport --uri='{mongo_uri}' "
                f"--collection={collection} --jsonArray | gzip | "
                f"gsutil cp - gs://{bucket}/{filename}"
            )
            subprocess.run(cmd, shell=True, check=True)
            print(f"✅ Collection '{collection}' backup uploaded to gs://{bucket}/{filename}")

        send_graph_email(success=True, filename=date, count=count)
        increment_backup_count(count)
        return f"Backup #{count} completed successfully\n", 200

    except subprocess.CalledProcessError as e:
        send_graph_email(success=False, error=str(e), count=count)
        return f"Backup #{count} failed\n", 500


# -----------------------------
# Backup Counter Management
# -----------------------------

def get_backup_count():
    """Return current backup count, starting at 1"""
    if os.path.exists(COUNTER_FILE):
        with open(COUNTER_FILE, "r") as f:
            return int(f.read().strip()) + 1
    return 1


def increment_backup_count(count):
    """Store the new backup count"""
    with open(COUNTER_FILE, "w") as f:
        f.write(str(count))


# -----------------------------
# Microsoft Graph Email Section
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


def send_graph_email(success=True, filename=None, error=None, count=1):
    """Send HTML email using Microsoft Graph API"""
    access_token = get_graph_token()
    sender = os.environ["EMAIL_FROM"]
    recipients = os.environ["EMAIL_TO"].split(",")
    bucket = os.environ["BUCKET"]

    if success:
        subject = f"✅ Backup Completed #{count}"
        status_text = f"MongoDB backup #{count} completed successfully."
        details = f"Files: gs://{bucket}/mongo_backup_users_{filename}.json.gz and mongo_backup_equipment_{filename}.json.gz"
    else:
        subject = f"❌ Backup Failed #{count}"
        status_text = f"MongoDB backup #{count} failed."
        details = f"Error: {error}"

    # HTML email
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"></head>
    <body style="font-family:Segoe UI,Tahoma,Geneva,Verdana,sans-serif;">
        <div style="max-width:600px;margin:auto;border:1px solid #e5e7eb;border-radius:8px;padding:30px;">
            <h2 style="color:#4f46e5;">IT Asset Management - Backup Notification</h2>
            <p style="font-size:16px;color:#1f2937;">{status_text}</p>
            <p style="font-size:15px;color:#4b5563;">{details}</p>
            <p style="margin-top:20px;font-size:14px;color:#6b7280;">
                Timestamp: {datetime.utcnow().isoformat()}Z
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
