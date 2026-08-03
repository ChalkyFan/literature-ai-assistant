#!/usr/bin/env python3
"""Database backup script - creates timestamped backups of literature.db"""
import shutil, os, datetime, glob

DB_PATH = r'D:\literature_AI_assistant\data\literature.db'
BACKUP_DIR = r'D:\literature_AI_assistant\data\backups'

os.makedirs(BACKUP_DIR, exist_ok=True)

ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
backup_path = os.path.join(BACKUP_DIR, f'literature_{ts}.db')

shutil.copy2(DB_PATH, backup_path)
print(f'Backup saved: {backup_path}')

# Auto-clean: keep only last 30 backups
all_backups = sorted(glob.glob(os.path.join(BACKUP_DIR, 'literature_*.db')))
while len(all_backups) > 30:
    old = all_backups.pop(0)
    os.remove(old)
    print(f'Removed old backup: {old}')

print(f'Total backups: {len(all_backups)}')
