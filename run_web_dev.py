"""Start web dev server (local only, for development testing)"""
import socket as _sock
_lock_sock = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
try:
    _lock_sock.bind(("127.0.0.1", 18081))
except _sock.error:
    import sys as _sys
    print("Dev server already running (port 18081 locked). Exiting.")
    _sys.exit(0)

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web_dev.app import app
from arxiv_assistant import db

if __name__ == "__main__":
    db.init_db()
    print("Dev server starting at http://127.0.0.1:8081")
    print("(Only accessible from this machine - safe for development)")
    app.run(host="127.0.0.1", port=8081, debug=True)
