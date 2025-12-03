from flask import Flask, request, jsonify
from main import MongoDBBackup
import logging
import os

app = Flask(__name__)
logger = logging.getLogger(__name__)

@app.route('/backup', methods=['POST'])
def trigger_backup():
    """Trigger MongoDB backup via HTTP POST"""
    try:
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
        logger.error(f'Error during backup: {e}')
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for Cloud Run"""
    return jsonify({'status': 'healthy'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
