#!/usr/bin/env python3
"""
MongoDB to GCS Backup Script with Email Notifications
Backs up MongoDB collections as JSON to Google Cloud Storage
Designed to run on Cloud Run triggered by Cloud Scheduler
Sends email notifications via Microsoft Graph API
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
        self.db_name = os.getenv('MONGO_DB_NAME', 'default_db')
        self.collections = os.getenv('MONGO_COLLECTIONS', '').split(',')
        self.collections = [c.strip() for c in self.collections if c.strip()]
        
        # Email config
        self.email_from = os.getenv('EMAIL_FROM')
        self.email_to = os.getenv('EMAIL_TO')
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
            return {'collection': collection_name, 'count': len(documents), 'data': documents}
        except PyMongoError as e:
            logger.error(f'❌ Failed to export collection {collection_name}: {e}')
            return None
    
    def upload_to_gcs(self, filename: str, data: Dict[str, Any]) -> bool:
        """Upload JSON data to GCS"""
        try:
            bucket = self.gcs_client.bucket(self.gcs_bucket)
            blob = bucket.blob(filename)
            
            json_data = json.dumps(data, default=str, indent=2)
            blob.upload_from_string(json_data, content_type='application/json')
            
            logger.info(f'⬆️  Uploaded {filename} to GCS')
            return True
        except Exception as e:
            logger.error(f'❌ Failed to upload {filename} to GCS: {e}')
            return False
    
    def backup_metadata(self) -> bool:
        """Upload backup metadata"""
        try:
            timestamp = datetime.utcnow().isoformat()
            metadata = {
                'timestamp': timestamp,
                'database': self.db_name,
                'collections': self.backup_info,
                'status': 'completed'
            }
            
            filename = f'backups/metadata/{datetime.utcnow().strftime("%Y-%m-%d")}/backup-{datetime.utcnow().strftime("%H-%M-%S")}.json'
            return self.upload_to_gcs(filename, metadata)
        except Exception as e:
            logger.error(f'❌ Failed to upload backup metadata: {e}')
            return False
    
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
        """Send success email notification"""
        try:
            if not self.email_from or not self.email_to:
                logger.warning('⚠️  Email not configured, skipping notification')
                return False
            
            access_token = self.get_graph_token()
            recipients = [r.strip() for r in self.email_to.split(',') if r.strip()]
            
            # Build collection summary table
            collection_rows = "".join(
                f"<tr><td style='padding:8px;border:1px solid #ddd;'>{item['collection']}</td>"
                f"<td style='padding:8px;border:1px solid #ddd;text-align:right;'>{item['documents']}</td>"
                f"<td style='padding:8px;border:1px solid #ddd;font-size:12px;'>{item['file']}</td></tr>"
                for item in self.backup_info
            )
            
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head><meta charset="UTF-8"></head>
            <body style="font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background-color:#f9fafb;">
                <div style="max-width:700px;margin:20px auto;border:1px solid #e5e7eb;border-radius:8px;padding:30px;background-color:white;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
                    <h2 style="color:#4f46e5;margin-top:0;margin-bottom:10px;">✅ MongoDB Backup Completed</h2>
                    <hr style="border:none;border-top:2px solid #e5e7eb;margin:15px 0;">
                    
                    <p style="font-size:16px;color:#1f2937;margin:15px 0;">
                        Your MongoDB backup has been completed successfully.
                    </p>
                    
                    <div style="background-color:#f0fdf4;border-left:4px solid #22c55e;padding:15px;margin:15px 0;border-radius:4px;">
                        <strong style="color:#166534;">Status:</strong> <span style="color:#15803d;">SUCCESS</span>
                    </div>
                    
                    <h3 style="color:#1f2937;margin-top:20px;">Backup Details</h3>
                    <table style="border-collapse:collapse;width:100%;margin:10px 0;">
                        <tr style="background-color:#f3f4f6;">
                            <th style="border:1px solid #ddd;padding:10px;text-align:left;">Collection</th>
                            <th style="border:1px solid #ddd;padding:10px;text-align:right;">Documents</th>
                            <th style="border:1px solid #ddd;padding:10px;text-align:left;">File Location</th>
                        </tr>
                        {collection_rows}
                    </table>
                    
                    <p style="margin:20px 0;font-size:14px;color:#4b5563;">
                        <strong>Backup Timestamp:</strong> {self.backup_timestamp}<br>
                        <strong>Database:</strong> {self.db_name}<br>
                        <strong>Storage Bucket:</strong> gs://{self.gcs_bucket}<br>
                        <strong>Total Collections:</strong> {len(self.backup_info)}
                    </p>
                    
                    <hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0;">
                    <p style="margin:10px 0;font-size:12px;color:#9ca3af;">
                        Generated at: {datetime.utcnow().isoformat()}Z
                    </p>
                </div>
            </body>
            </html>
            """
            
            message = {
                "message": {
                    "subject": f"✅ MongoDB Backup Completed - {self.backup_timestamp}",
                    "body": {"contentType": "HTML", "content": html_content},
                    "toRecipients": [{"emailAddress": {"address": addr}} for addr in recipients],
                }
            }
            
            url = f"https://graph.microsoft.com/v1.0/users/{self.email_from}/sendMail"
            headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
            
            resp = requests.post(url, headers=headers, json=message, timeout=10)
            
            if resp.status_code < 300:
                logger.info(f'📧 Success email sent to {recipients}')
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
                logger.warning('⚠️  Email not configured, skipping notification')
                return False
            
            access_token = self.get_graph_token()
            recipients = [r.strip() for r in self.email_to.split(',') if r.strip()]
            
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head><meta charset="UTF-8"></head>
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
                    
                    <p style="margin:20px 0;font-size:13px;color:#d97706;background-color:#fffbeb;padding:10px;border-radius:4px;border-left:3px solid #fbbf24;">
                        ⚠️ Please investigate the error and ensure your MongoDB connection and GCS permissions are properly configured.
                    </p>
                    
                    <hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0;">
                    <p style="margin:10px 0;font-size:12px;color:#9ca3af;">
                        Generated at: {datetime.utcnow().isoformat()}Z
                    </p>
                </div>
            </body>
            </html>
            """
            
            message = {
                "message": {
                    "subject": f"❌ MongoDB Backup Failed - {self.backup_timestamp}",
                    "body": {"contentType": "HTML", "content": html_content},
                    "toRecipients": [{"emailAddress": {"address": addr}} for addr in recipients],
                }
            }
            
            url = f"https://graph.microsoft.com/v1.0/users/{self.email_from}/sendMail"
            headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
            
            resp = requests.post(url, headers=headers, json=message, timeout=10)
            
            if resp.status_code < 300:
                logger.info(f'📧 Error email sent to {recipients}')
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
                logger.info(f'🗑️  Cleaned up {deleted_count} old backup files')
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
            
            for collection_name in collections:
                logger.info(f'Processing collection: {collection_name}')
                
                data = self.export_collection_to_json(collection_name)
                if data:
                    filename = f'backups/{self.db_name}/{self.backup_timestamp}/{collection_name}.json'
                    if self.upload_to_gcs(filename, data):
                        self.backup_info.append({
                            'collection': collection_name,
                            'documents': data['count'],
                            'file': filename
                        })
                    else:
                        logger.error(f'❌ Failed to backup {collection_name}')
                        continue
                else:
                    logger.error(f'❌ Failed to export {collection_name}')
                    continue
            
            # Upload metadata
            if self.backup_info:
                self.backup_metadata()
                logger.info(f'✅ Backup completed: {len(self.backup_info)} collections backed up')
                
                # Send success email
                self.send_success_email()
                
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

def main(request=None):
    """Cloud Run entry point"""
    try:
        backup = MongoDBBackup()
        success = backup.run_backup()
        
        # Cleanup old backups
        retention_days = int(os.getenv('BACKUP_RETENTION_DAYS', 30))
        backup.cleanup_old_backups(retention_days)
        
        return {
            'status': 'success' if success else 'failed',
            'message': 'Backup completed successfully' if success else 'Backup failed'
        }, 200 if success else 500
    except Exception as e:
        logger.error(f'❌ Error in main: {e}')
        return {'status': 'error', 'message': str(e)}, 500

if __name__ == '__main__':
    main()
