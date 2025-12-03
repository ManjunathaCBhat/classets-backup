import os
import sys
import logging

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify
from backup import MongoDBBackup
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
@@ -22,7 +22,7 @@
def trigger_backup():
    """Trigger MongoDB backup via HTTP POST"""
    try:
        logger.info("Backup triggered")
        logger.info("🚀 Backup triggered")

        backup = MongoDBBackup()
        success = backup.run_backup()
@@ -37,12 +37,12 @@
            'backup_info': backup.backup_info
        }), 200 if success else 500
    except Exception as e:
        logger.error(f'Error during backup: {str(e)}', exc_info=True)
        logger.error(f'❌ Error during backup: {str(e)}', exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
