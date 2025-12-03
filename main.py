#!/usr/bin/env python3
"""
Cloud Run entry point for MongoDB Backup
"""

import os
import sys
from backup import MongoDBBackup
import logging

def main():
    """Main entry point for Cloud Run"""
    try:
        backup = MongoDBBackup()
        success = backup.run_backup()
        
        if success:
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as e:
        logging.error(f"Backup failed with exception: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
