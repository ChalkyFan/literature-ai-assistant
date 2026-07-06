import sys, os, socket, time

# Single-instance lock
lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    lock_socket.bind(("127.0.0.1", 18080))
except socket.error:
    print("Server already running (port 18080 locked)")
    sys.exit(1)

sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from web.app import app
from arxiv_assistant import db

db.init_db()
print("Web server starting at http://0.0.0.0:8080")
app.run(host="0.0.0.0", port=8080, debug=False, use_reloader=False)
