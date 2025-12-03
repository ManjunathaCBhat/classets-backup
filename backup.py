#!/usr/bin/env python3
"""
MongoDB to GCS Backup Script with Professional Email Notifications
Backs up MongoDB collections as JSON to Google Cloud Storage
Designed to run on Cloud Run triggered by Cloud Scheduler
Sends themed email notifications via Microsoft Graph API
"""

import json
import os
import requests
from datetime import datetime
from typing import List, Dict, Any
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from google.cloud import storage
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MongoDBBackup:
    def __init__(self):
        self.mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017')
        self.gcs_bucket = os.getenv('GCS_BUCKET')
        self.gcs_project = os.getenv('GCP_PROJECT_ID')
        self.db_name = os.getenv('MONGO_DB_NAME', 'asset')
        self.collections = os.getenv('MONGO_COLLECTIONS', '').split(',')
        self.collections = [c.strip() for c in self.collections if c.strip()]
        
        # Email config
        self.email_from = os.getenv('EMAIL_FROM')
        self.email_to = os.getenv('EMAIL_TO')
        self.email_cc = os.getenv('EMAIL_CC', '')
        self.azure_tenant = os.getenv('AZURE_TENANT_ID')
        self.azure_client = os.getenv('AZURE_CLIENT_ID')
        self.azure_secret = os.getenv('AZURE_CLIENT_SECRET')
        
        if not self.gcs_bucket:
            raise ValueError('GCS_BUCKET environment variable is required')
        
        self.mongo_client = None
        self.gcs_client = None
        self.backup_info = []
        self.backup_timestamp = datetime.utcnow().strftime('%Y-%m-%d_%H-%M-%S')

    def connect_mongo(self) -> bool:
        """Connect to MongoDB"""
        try:
            self.mongo_client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=5000)
            self.mongo_client.admin.command('ping')
            logger.info('✅ Successfully connected to MongoDB')
            return True
        except PyMongoError as e:
            logger.error(f'❌ Failed to connect to MongoDB: {e}')
            return False

    def connect_gcs(self) -> bool:
        """Connect to Google Cloud Storage"""
        try:
            self.gcs_client = storage.Client(project=self.gcs_project)
            bucket = self.gcs_client.bucket(self.gcs_bucket)
            bucket.reload()
            logger.info(f'✅ Successfully connected to GCS bucket: {self.gcs_bucket}')
            return True
        except Exception as e:
            logger.error(f'❌ Failed to connect to GCS: {e}')
            return False

    def get_collections_to_backup(self) -> List[str]:
        """Get list of collections to backup"""
        try:
            db = self.mongo_client[self.db_name]
            available_collections = db.list_collection_names()
            
            if self.collections:
                to_backup = [c for c in self.collections if c in available_collections]
                logger.info(f'📦 Backing up specified collections: {to_backup}')
                return to_backup
            else:
                logger.info(f'📦 Backing up all collections: {available_collections}')
                return available_collections
        except PyMongoError as e:
            logger.error(f'❌ Failed to list collections: {e}')
            return []

    def export_collection_to_json(self, collection_name: str) -> Dict[str, Any]:
        """Export a collection as JSON"""
        try:
            db = self.mongo_client[self.db_name]
            collection = db[collection_name]
            documents = list(collection.find({}))
            
            # Convert ObjectId to string for JSON serialization
            for doc in documents:
                if '_id' in doc:
                    doc['_id'] = str(doc['_id'])
            
            logger.info(f'📄 Exported {len(documents)} documents from {collection_name}')
            return {
                'collection': collection_name, 
                'documents': len(documents), 
                'file': f'backups/{self.db_name}/{self.backup_timestamp}/{collection_name}.json'
            }
        except PyMongoError as e:
            logger.error(f'❌ Failed to export collection {collection_name}: {e}')
            return None

    def upload_to_gcs(self, filename: str, data: Dict[str, Any]) -> bool:
        """Upload JSON data to GCS"""
        try:
            bucket = self.gcs_client.bucket(self.gcs_bucket)
            blob = bucket.blob(filename)
            
            json_data = json.dumps(data['data'], default=str, indent=2)
            blob.upload_from_string(json_data, content_type='application/json')
            
            logger.info(f'⬆️ Uploaded {filename} to GCS')
            return True
        except Exception as e:
            logger.error(f'❌ Failed to upload {filename} to GCS: {e}')
            return False

    def backup_success_email_html(self) -> str:
        """Generate professional HTML email for backup success matching IT Asset theme"""
        now = datetime.now()
        date_str = now.strftime("%B %d, %Y")
        time_str = now.strftime("%I:%M %p")
        
        # Build collection table rows
        collection_rows = ""
        for item in self.backup_info:
            collection_rows += f"""
            <tr>
                <td style="font-size:15px;color:#6b7280;font-weight:600;padding:12px 0;width:140px;">{item['collection']}</td>
                <td style="font-size:15px;color:#111827;font-weight:500;padding:12px 0;text-align:right;">{item['documents']}</td>
                <td style="font-size:15px;color:#111827;font-weight:500;padding:12px 0;font-size:13px;">{item['file']}</td>
            </tr>
            """
        
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background-color:#ffffff;">
    <table width="100%%" cellpadding="0" cellspacing="0" style="background-color:#ffffff;padding:40px 20px;">
        <tr>
            <td align="center">
                <table width="650" cellpadding="0" cellspacing="0" style="background-color:#ffffff;border:2px solid #e5e7eb;border-radius:12px;overflow:hidden;">
                    <!-- Header -->
                    <tr>
                        <td style="background-color:#4f46e5;padding:50px 40px;text-align:center;">
                            <h1 style="color:#ffffff;margin:0 0 10px 0;font-size:32px;font-weight:700;letter-spacing:-0.5px;">
                                🗄️ Asset Backup Completed - {self.backup_timestamp}
                            </h1>
                            <p style="color:#c7d2fe;margin:0;font-size:16px;font-weight:400;">
                                MongoDB data successfully backed up to Google Cloud Storage
                            </p>
                        </td>
                    </tr>
                    <!-- Main Content -->
                    <tr>
                        <td style="padding:50px 40px;background-color:#ffffff;">
                            <p style="margin:0 0 10px 0;font-size:18px;color:#1f2937;font-weight:600;">
                                Backup Summary
                            </p>
                            <p style="margin:0 0 30px 0;font-size:16px;line-height:1.7;color:#4b5563;">
                                Your scheduled MongoDB backup has completed successfully. Review the details below.
                            </p>
                            
                            <!-- Backup Details Card -->
                            <table width="100%%" cellpadding="0" cellspacing="0" style="background-color:#f9fafb;border:2px solid #e5e7eb;border-radius:10px;margin:0 0 30px 0;overflow:hidden;">
                                <tr>
                                    <td style="padding:30px;">
                                        <p style="margin:0 0 20px 0;font-size:18px;font-weight:700;color:#1f2937;text-align:center;">📊 Backup Details</p>
                                        <table width="100%%" cellpadding="0" cellspacing="0" style="background-color:#ffffff;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
                                            <tr>
                                                <td style="padding:20px;">
                                                    <table width="100%%" cellpadding="8" cellspacing="0">
                                                        <tr style="background-color:#f3f4f6;">
                                                            <td style="font-size:15px;color:#111827;font-weight:700;padding:12px 0;width:140px;">Collection</td>
                                                            <td style="font-size:15px;color:#111827;font-weight:700;padding:12px 0;text-align:right;">Documents</td>
                                                            <td style="font-size:15px;color:#111827;font-weight:700;padding:12px 0;">File Location</td>
                                                        </tr>
                                                        {collection_rows}
                                                    </table>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                            
                            <!-- Success Alert -->
                            <table width="100%%" cellpadding="0" cellspacing="0" style="background-color:#d1fae5;border:2px solid #10b981;border-radius:6px;margin:0 0 35px 0;">
                                <tr>
                                    <td style="padding:20px 25px;">
                                        <table cellpadding="0" cellspacing="0">
                                            <tr>
                                                <td style="padding-right:15px;vertical-align:top;">
                                                    <span style="font-size:24px;">✅</span>
                                                </td>
                                                <td>
                                                    <p style="margin:0 0 8px 0;font-size:15px;color:#065f46;font-weight:700;">Backup Successful</p>
                                                    <p style="margin:0;font-size:14px;color:#065f46;line-height:1.6;">
                                                        All {len(self.backup_info)} collections backed up to gs://{self.gcs_bucket}
                                                    </p>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                            
                            <!-- Summary Info -->
                            <table width="100%%" cellpadding="0" cellspacing="0" style="background-color:#f9fafb;border:2px solid #e5e7eb;border-radius:8px;margin:0 0 20px 0;">
                                <tr>
                                    <td style="padding:25px;">
                                        <p style="margin:0 0 10px 0;font-size:15px;color:#1f2937;font-weight:600;">Summary</p>
                                        <p style="margin:0;font-size:14px;color:#4b5563;line-height:1.6;">
                                            <strong>Timestamp:</strong> {self.backup_timestamp}<br>
                                            <strong>Database:</strong> {self.db_name}<br>
                                            <strong>Bucket:</strong> gs://{self.gcs_bucket}<br>
                                            <strong>Total Collections:</strong> {len(self.backup_info)}
                                        </p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <!-- Footer -->
                    <tr>
                        <td style="padding:30px 40px;background-color:#111827;text-align:center;border-top:3px solid #4f46e5;">
                            <p style="margin:0 0 8px 0;font-size:16px;font-weight:600;color:#ffffff;">IT Asset Management System</p>
                            <p style="margin:15px 0 0 0;font-size:12px;color:#9ca3af;line-height:1.6;">
                                This is an automated backup notification. Generated on {date_str} at {time_str}.
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""
        return html_content

    def get_graph_token(self) -> str:
        """Get Microsoft Graph API access token"""
        try:
            if not all([self.azure_tenant, self.azure_client, self.azure_secret]):
                raise ValueError('Azure credentials not configured')
            
            token_url = f"https://login.microsoftonline.com/{self.azure_tenant}/oauth2/v2.0/token"
            data = {
                "grant_type": "client_credentials",
                "client_id": self.azure_client,
                "client_secret": self.azure_secret,
                "scope": "https://graph.microsoft.com/.default"
            }
            
            resp = requests.post(token_url, data=data, timeout=10)
            resp.raise_for_status()
            return resp.json()["access_token"]
        except Exception as e:
            logger.error(f'❌ Failed to get Graph token: {e}')
            raise

    def send_success_email(self) -> bool:
        """Send success email notification with CC support"""
        try:
            if not self.email_from or not self.email_to:
                logger.warning('⚠️ Email not configured, skipping notification')
                return False
            
            access_token = self.get_graph_token()
            to_recipients = [r.strip() for r in self.email_to.split(',') if r.strip()]
            cc_recipients = [r.strip() for r in self.email_cc.split(',') if r.strip()]
            
            html_content = self.backup_success_email_html()
            
            message = {
                "message": {
                    "subject": f"🗄️ Asset Backup Completed - {self.backup_timestamp}",
                    "body": {"contentType": "HTML", "content": html_content},
                    "toRecipients": [{"emailAddress": {"address": addr}} for addr in to_recipients],
                }
            }
            
            if cc_recipients:
                message["message"]["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc_recipients]
                logger.info(f'📧 Sending to {len(to_recipient}s} + CC {len(cc_recipients)}')
            
            url = f"https://graph.microsoft.com/v1.0/users/{self.email_from}/sendMail"
            headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
            
            resp = requests.post(url, headers=headers, json=message, timeout=30)
            
            if resp.status_code < 300:
                logger.info('📧 Success email sent successfully')
                return True
            else:
                logger.error(f'❌ Email failed: {resp.text}')
                return False
        except Exception as e:
            logger.error(f'❌ Failed to send success email: {e}')
            return False

    def send_error_email(self, error_msg: str) -> bool:
        """Send error notification email"""
        try:
            if not self.email_from or not self.email_to:
                logger.warning('⚠️ Email not configured, skipping notification')
                return False
            
            access_token = self.get_graph_token()
            to_recipients = [r.strip() for r in self.email_to.split(',') if r.strip()]
            cc_recipients = [r.strip() for r in self.email_cc.split(',') if r.strip()]
            
            html_content = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background-color:#f9fafb;">
    <div style="max-width:700px;margin:20px auto;border:1px solid #e5e7eb;border-radius:8px;padding:30px;background-color:white;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
        <h2 style="color:#dc2626;margin-top:0;margin-bottom:10px;">❌ MongoDB Backup Failed</h2>
        <hr style="border:none;border-top:2px solid #e5e7eb;margin:15px 0;">
        <div style="background-color:#fef2f2;border-left:4px solid #ef4444;padding:15px;margin:15px 0;border-radius:4px;">
            <strong style="color:#7f1d1d;">Status:</strong> <span style="color:#991b1b;">FAILED</span>
        </div>
        <h3 style="color:#1f2937;margin-top:20px;">Error Details</h3>
        <div style="background-color:#fef2f2;padding:15px;border-radius:4px;font-family:monospace;font-size:13px;color:#7f1d1d;overflow-x:auto;">
            {error_msg}
        </div>
        <p style="margin:20px 0;font-size:14px;color:#4b5563;">
            <strong>Database:</strong> {self.db_name}<br>
            <strong>Storage Bucket:</strong> gs://{self.gcs_bucket}<br>
            <strong>Attempted Backup Time:</strong> {self.backup_timestamp}
        </p>
        <hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0;">
        <p style="margin:10px 0;font-size:12px;color:#9ca3af;">
            Generated at: {datetime.utcnow().isoformat()}Z
        </p>
    </div>
</body></html>"""
            
            message = {
                "message": {
                    "subject": f"❌ MongoDB Backup Failed - {self.backup_timestamp}",
                    "body": {"contentType": "HTML", "content": html_content},
                    "toRecipients": [{"emailAddress": {"address": addr}} for addr in to_recipients],
                }
            }
            
            if cc_recipients:
                message["message"]["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc_recipients]
            
            url = f"https://graph.microsoft.com/v1.0/users/{self.email_from}/sendMail"
            headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
            
            resp = requests.post(url, headers=headers, json=message, timeout=30)
            
            if resp.status_code < 300:
                logger.info('📧 Error email sent successfully')
                return True
            else:
                logger.error(f'❌ Error email failed: {resp.text}')
                return False
        except Exception as e:
            logger.error(f'❌ Failed to send error email: {e}')
            return False

    def cleanup_old_backups(self, days: int = 30) -> None:
        """Delete backups older than specified days"""
        try:
            from datetime import timedelta
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            bucket = self.gcs_client.bucket(self.gcs_bucket)
            blobs = bucket.list_blobs(prefix='backups/')
            deleted_count = 0
            
            for blob in blobs:
                if blob.time_created and blob.time_created.replace(tzinfo=None) < cutoff_date:
                    blob.delete()
                    deleted_count += 1
            
            if deleted_count > 0:
                logger.info(f'🧹 Cleaned up {deleted_count} old backup files')
        except Exception as e:
            logger.error(f'❌ Failed to cleanup old backups: {e}')

    def run_backup(self) -> bool:
        """Execute full backup process"""
        if not self.connect_mongo() or not self.connect_gcs():
            error_msg = "Failed to connect to MongoDB or GCS"
            self.send_error_email(error_msg)
            return False
        
        try:
            collections = self.get_collections_to_backup()
            if not collections:
                error_msg = "No collections to backup"
                logger.warning(error_msg)
                self.send_error_email(error_msg)
                return False
            
            successful_backups = 0
            for collection_name in collections:
                logger.info(f'🔄 Processing collection: {collection_name}')
                data = self.export_collection_to_json(collection_name)
                
                if data and self.upload_to_gcs(data['file'], data):
                    self.backup_info.append(data)
                    successful_backups += 1
                else:
                    logger.error(f'❌ Failed to backup collection: {collection_name}')
                    continue
            
            if successful_backups > 0:
                logger.info(f'✅ Backup completed: {successful_backups} collections backed up')
                self.send_success_email()
                self.cleanup_old_backups()
                return True
            else:
                error_msg = "No collections were successfully backed up"
                logger.warning(error_msg)
                self.send_error_email(error_msg)
                return False
                
        except Exception as e:
            error_msg = f"Backup process failed: {str(e)}"
            logger.error(f'❌ {error_msg}')
            self.send_error_email(error_msg)
            return False
        finally:
            if self.mongo_client:
                self.mongo_client.close()
