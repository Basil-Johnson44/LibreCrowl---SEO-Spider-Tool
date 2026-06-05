import os
import sys
import threading
import socket
import time
import shutil

# Force Playwright browser path to prevent PyInstaller search error
if 'LOCALAPPDATA' in os.environ:
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(os.environ['LOCALAPPDATA'], 'ms-playwright')
else:
    user_home = os.path.expanduser('~')
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(user_home, 'AppData', 'Local', 'ms-playwright')

# 1. Force local mode argument for argparse in main.py
# This enables the auto-login flow to log us directly into the local administrator account
if '-l' not in sys.argv and '--local' not in sys.argv:
    sys.argv.append('-l')

# 2. Add AppData directory configuration and database copying
from src.utils.paths import get_data_dir, get_db_path

def copy_initial_db_if_needed():
    """Copy users.db from bundle/source to AppData if not already present."""
    db_dest = get_db_path()
    if os.path.exists(db_dest):
        print(f"Database already exists in writeable location: {db_dest}")
        return

    # Find the source db
    if getattr(sys, 'frozen', False):
        # We are running as a PyInstaller bundle
        db_src = os.path.join(sys._MEIPASS, 'data', 'users.db')
    else:
        # Development mode
        db_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'users.db')

    if os.path.exists(db_src):
        print(f"Copying initial database from {db_src} to {db_dest}...")
        try:
            os.makedirs(os.path.dirname(db_dest), exist_ok=True)
            shutil.copy2(db_src, db_dest)
            print("Database copied successfully!")
        except Exception as e:
            print(f"Error copying initial database: {e}")
    else:
        print(f"Initial database source not found at {db_src}. Creating empty directory.")
        os.makedirs(os.path.dirname(db_dest), exist_ok=True)

# Copy the database before starting the backend
copy_initial_db_if_needed()

# 3. Find a free port dynamically to prevent port collision
def find_free_port():
    """Find a free port on localhost."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port

PORT = find_free_port()
print(f"Dynamic localhost port selected for desktop app: {PORT}")

# Set the port environment variable (waitress can pick this up, and our crawler uses it)
os.environ['LIBRECRAWL_PORT'] = str(PORT)

# 4. Import the Flask application from main.py
# Note: we import after setting sys.argv and copying database
from main import app

def start_flask_server():
    """Start Waitress production server in a background thread."""
    from waitress import serve
    print(f"Starting waitress WSGI backend server on http://127.0.0.1:{PORT}...")
    serve(app, host='127.0.0.1', port=PORT, threads=8)

# Start server in a background daemon thread
server_thread = threading.Thread(target=start_flask_server, daemon=True)
server_thread.start()

# 5. Playwright Browser Provisioning Checker
def ensure_playwright_browsers():
    """Verify that Playwright has Chromium browser installed, downloading if missing."""
    print("Checking Playwright crawler environment...")
    try:
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as p:
                # Try to launch Chromium headless to verify installation
                browser = p.chromium.launch(headless=True)
                browser.close()
                print("Playwright Chromium browser is verified and ready!")
                return
        except Exception as launch_err:
            print(f"Playwright Chromium browser not found or not launched: {launch_err}")
            print("Starting automated programmatic download of Playwright Chromium (this occurs once)...")
            
            import subprocess
            from playwright._impl._driver import compute_driver_executable, get_driver_env
            
            try:
                driver_executable, driver_cli_path = compute_driver_executable()
                env = get_driver_env()
                
                # Configure subprocess to run hidden and without inheriting None streams
                startupinfo = None
                if sys.platform == 'win32':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = subprocess.SW_HIDE
                
                print(f"Executing Playwright installer driver subprocess: {driver_executable} {driver_cli_path} install chromium")
                result = subprocess.run(
                    [driver_executable, driver_cli_path, "install", "chromium"],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                    startupinfo=startupinfo,
                    text=True
                )
                
                # Log driver output to a log file for user debugging
                log_path = os.path.join(get_data_dir(), "playwright_install.log")
                try:
                    with open(log_path, "w", encoding="utf-8") as log_file:
                        log_file.write(f"Playwright Installer Return Code: {result.returncode}\n\n")
                        log_file.write(f"--- STDOUT ---\n{result.stdout}\n\n")
                        log_file.write(f"--- STDERR ---\n{result.stderr}\n")
                except Exception as log_err:
                    print(f"Failed to write playwright install log: {log_err}")
                
                if result.returncode == 0:
                    print("Playwright Chromium browser downloaded and registered successfully!")
                else:
                    print(f"Playwright browser installation failed with code {result.returncode}. See log: {log_path}")
                    if sys.platform == 'win32':
                        import ctypes
                        ctypes.windll.user32.MessageBoxW(
                            0,
                            f"Failed to automatically install Playwright browser dependencies (Exit Code {result.returncode}).\n\n"
                            f"Please check the log file for details:\n{log_path}",
                            "LibreCrawl - Browser Dependency Error",
                            0x10  # MB_ICONERROR
                        )
            except Exception as sub_err:
                print(f"Failed to execute Playwright driver installer: {sub_err}")
                if sys.platform == 'win32':
                    import ctypes
                    ctypes.windll.user32.MessageBoxW(
                        0,
                        f"Failed to execute Playwright driver installer: {sub_err}",
                        "LibreCrawl - Error",
                        0x10  # MB_ICONERROR
                    )
    except Exception as e:
        print(f"Error provisioning Playwright crawler environment: {e}")

# Run playwright browser checker in a separate thread so it doesn't block GUI startup
playwright_thread = threading.Thread(target=ensure_playwright_browsers, daemon=True)
playwright_thread.start()

class DesktopAPI:
    def __init__(self):
        self.window = None

    def save_file(self, filename, content):
        """Open a native Windows Save File Dialog and write text content directly to disk."""
        if not self.window:
            return {'success': False, 'error': 'Window not initialized'}
        
        import webview
        
        # Default to standard Windows Downloads folder
        downloads_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
        if not os.path.exists(downloads_dir):
            downloads_dir = os.path.expanduser('~')
            
        file_path = self.window.create_file_dialog(
            webview.SAVE_DIALOG,
            directory=downloads_dir,
            save_filename=filename
        )
        
        # Resolve PyWebView tuple return value (e.g. ('C:\\path\\file.csv',))
        if isinstance(file_path, (tuple, list)):
            file_path = file_path[0] if len(file_path) > 0 else None
            
        if not file_path:
            print("Save file cancelled by user.")
            return {'success': False, 'error': 'Cancelled'}
            
        print(f"Attempting to save file to: {file_path}")
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"File saved successfully to: {file_path}")
            return {'success': True, 'path': file_path}
        except Exception as e:
            print(f"Error saving file: {e}")
            return {'success': False, 'error': str(e)}

# 6. Spawns modern Edge WebView2 desktop browser window
def run_gui():
    import webview
    
    # Wait for the backend server to be responsive
    server_ready = False
    for _ in range(50):  # Wait up to 5 seconds
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.1)
            s.connect(('127.0.0.1', PORT))
            s.close()
            server_ready = True
            break
        except Exception:
            time.sleep(0.1)
            
    if not server_ready:
        print("Error: Background server failed to start in time. Launching window anyway...")

    print("Launching Edge WebView2 window...")
    
    # Configure the window properties with dynamic Javascript-Python API
    api = DesktopAPI()
    window = webview.create_window(
        title='LibreCrawl - SEO Spider Tool',
        url=f'http://127.0.0.1:{PORT}',
        width=1366,
        height=850,
        min_size=(960, 640),
        maximized=True,
        background_color='#0f172a',  # Sleek slate/dark theme background color matches site
        js_api=api
    )
    api.window = window
    
    # Start the PyWebView event loop
    webview.start()

if __name__ == '__main__':
    run_gui()
