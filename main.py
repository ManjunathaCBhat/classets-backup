#!/usr/bin/env python3
import os
import sys
import logging
from flask import Flask, jsonify
from backup import MongoDBBackup

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    return "MongoDB Backup Service - Healthy", 200

@app.route('/backup', methods=['POST'])
def trigger_backup():
    """Trigger MongoDB backup via HTTP POST"""
    try:
        logger.info("🚀 Backup triggered")
        
        backup = MongoDBBackup()
        success = backup.run_backup()
        
        return jsonify({
            'status': 'success' if success else 'error',
            'message': 'Backup completed' if success else 'Backup failed',
            'backup_info': backup.backup_info
        }), 200 if success else 500
    except Exception as e:
        logger.error(f'❌ Error during backup: {str(e)}', exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
