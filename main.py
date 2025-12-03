#!/usr/bin/env python3
"""
Cloud Run entry point for MongoDB Backup with HTTP handler
"""

import os
import sys
from flask import Flask, jsonify
from backup import MongoDBBackup
import logging
import threading
import time

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_backup_job():
    """Run backup job in background thread"""
    try:
        backup = MongoDBBackup()
        success = backup.run_backup()
        
        if success:
            logger.info("✅ Backup job completed successfully")
            return {"status": "success", "message": "Backup completed"}
        else:
            logger.error("❌ Backup job failed")
            return {"status": "error", "message": "Backup failed"}
    except Exception as e:
        logger.error(f"❌ Backup failed with exception: {e}")
        return {"status": "error", "message": str(e)}

@app.route('/', methods=['GET', 'POST'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "service": "MongoDB Backup",
        "timestamp": time.time()
    }), 200

@app.route('/backup', methods=['POST'])
def trigger_backup():
    """Trigger backup job"""
    try:
        # Start backup in background thread (Cloud Run timeout is 60min max)
        backup_thread = threading.Thread(target=lambda: run_backup_job())
        backup_thread.daemon = True
        backup_thread.start()
        
        logger.info("🚀 Backup job started (async)")
        return jsonify({
            "status": "accepted",
            "message": "Backup job started asynchronously",
            "timestamp": time.time()
        }), 202
        
    except Exception as e:
        logger.error(f"❌ Failed to start backup: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/backup/sync', methods=['POST'])
def trigger_backup_sync():
    """Trigger synchronous backup (for testing, max 5-10min jobs)"""
    try:
        result = run_backup_job()
        return jsonify(result), 200 if result["status"] == "success" else 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"status": "error", "message": "Internal server error"}), 500

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
