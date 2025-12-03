#!/usr/bin/env python3
"""
Minimal Cloud Run entry point - WORKS with your existing backup.py
"""

import os
from flask import Flask
from backup import MongoDBBackup
import logging
import threading

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route('/', methods=['GET', 'POST'])
def health():
    return "MongoDB Backup Service - Healthy", 200

@app.route('/backup', methods=['POST'])
def backup():
    """Trigger backup"""
    def run_backup():
        try:
            backup = MongoDBBackup()
            backup.run_backup()
            logger.info("✅ Backup completed")
        except Exception as e:
            logger.error(f"❌ Backup failed: {e}")
    
    # Run backup in background thread
    thread = threading.Thread(target=run_backup)
    thread.daemon = True
    thread.start()
    
    return "Backup started", 202

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
