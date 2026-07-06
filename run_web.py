import socket as _sock
_lock_sock = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
try:
    _lock_sock.bind(("127.0.0.1", 18080))
except _sock.error:
    import sys
    print("Server already running (port 18080 locked). Exiting.")
    sys.exit(0)
"""Start web server"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from web.app import app
from arxiv_assistant import db

if __name__ == "__main__":
    db.init_db()
    print("Web server starting at http://localhost:8080")
    app.run(host="0.0.0.0", port=8080, debug=False)
