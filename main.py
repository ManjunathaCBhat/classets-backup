import os
import sys

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify
from backup import MongoDBBackup
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy'}), 200

@app.route('/backup', methods=['POST'])
def trigger_backup():
    """Trigger MongoDB backup via HTTP POST"""
    try:
        logger.info("Backup triggered")
        
        backup = MongoDBBackup()
        success = backup.run_backup()
        
        # Cleanup old backups
        retention_days = int(os.getenv('BACKUP_RETENTION_DAYS', 30))
        backup.cleanup_old_backups(retention_days)
        
        return jsonify({
            'status': 'success' if success else 'failed',
            'message': 'Backup completed successfully' if success else 'Backup failed',
            'backup_info': backup.backup_info
        }), 200 if success else 500
    except Exception as e:
        logger.error(f'Error during backup: {str(e)}', exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
