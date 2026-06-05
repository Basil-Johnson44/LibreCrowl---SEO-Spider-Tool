import os
import sys
import subprocess
import shutil

def run_command(command, description):
    """Run a terminal command and handle exceptions."""
    print(f"\n[Build Pipeline] {description}...")
    try:
        result = subprocess.run(command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        print(f"Success: {description}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error: {description} failed.")
        print(f"Command returned non-zero exit code: {e.returncode}")
        print(f"Stdout:\n{e.stdout}")
        print(f"Stderr:\n{e.stderr}")
        return False

def install_dependencies():
    """Install all necessary packages for building and running the desktop app."""
    # Packages:
    # - pywebview: Native Edge WebView2 container
    # - pyinstaller: Compiler to bundle Python code to .exe
    # - waitress: Production WSGI server
    # - pillow: Image library to convert PNG logo to ICO icon file
    packages = ["pywebview", "pyinstaller", "waitress", "pillow", "playwright", "playwright-stealth"]
    print(f"\n[Build Pipeline] Checking and installing packaging dependencies: {', '.join(packages)}")
    
    # We use sys.executable to install in the active Python environment
    pip_cmd = [sys.executable, "-m", "pip", "install", "-U"] + packages
    cmd_str = " ".join(pip_cmd)
    
    return run_command(cmd_str, "Installing pip dependencies")

def convert_logo_to_ico():
    """Convert the PNG logo into a multi-resolution Windows .ico icon file."""
    print("\n[Build Pipeline] Generating multi-size Windows icon (.ico) from PNG logo...")
    png_path = os.path.join("web", "static", "logo.png")
    ico_path = "librecrawl.ico"
    
    if not os.path.exists(png_path):
        print(f"Error: Source PNG logo not found at {png_path}!")
        return False
        
    try:
        from PIL import Image
        img = Image.open(png_path)
        
        # Save as a multi-size Windows ICO
        # Windows uses different icon sizes (16, 32, 48, 64, 128, 256) for different views (desktop, detail list, taskbar, etc.)
        icon_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        img.save(ico_path, format='ICO', sizes=icon_sizes)
        print(f"Success: Created Windows multi-size icon at: {os.path.abspath(ico_path)}")
        return True
    except Exception as e:
        print(f"Error converting logo to ICO: {e}")
        return False

def run_pyinstaller():
    """Run PyInstaller to compile desktop_app.py to a single .exe."""
    print("\n[Build Pipeline] Running PyInstaller Compiler...")
    
    # Close any running instances of LibreCrawl.exe to prevent Windows file-lock PermissionError
    print("Closing any running instances of LibreCrawl.exe...")
    try:
        subprocess.run("taskkill /f /im LibreCrawl.exe", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import time
        time.sleep(1.0)
    except Exception as e:
        print(f"Warning: Could not terminate running instances: {e}")
        
    # Check if librecrawl.ico was created, fallback if not
    icon_arg = "--icon=librecrawl.ico" if os.path.exists("librecrawl.ico") else ""
    
    # Build the PyInstaller command
    # --noconsole: Hide the terminal window when running the app
    # --onefile: Package everything into a single standalone EXE
    # --add-data: Bundle web templates, static files, and initial database
    pyi_command = [
        f'"{sys.executable}" -m PyInstaller',
        "--noconsole",
        "--onefile",
        icon_arg,
        '--add-data "web/templates;web/templates"',
        '--add-data "web/static;web/static"',
        '--add-data "data/users.db;data"',
        "--collect-data playwright_stealth",
        "--name LibreCrawl",
        "desktop_app.py"
    ]
    
    # Filter empty elements
    pyi_command = [x for x in pyi_command if x]
    cmd_str = " ".join(pyi_command)
    
    success = run_command(cmd_str, "Running PyInstaller compiler")
    if success:
        print("\n" + "=" * 60)
        print("BUILD SUCCESSFUL!")
        print(f"Your standalone Windows App is ready at:")
        print(os.path.abspath(os.path.join("dist", "LibreCrawl.exe")))
        print("=" * 60 + "\n")
        return True
    return False

def main():
    # Make sure we are in the correct directory (LibreCrawl-Desktop)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    print(f"Running build pipeline in: {script_dir}")
    
    # 1. Install dependencies
    if not install_dependencies():
        print("Build failed at dependency installation.")
        sys.exit(1)
        
    # 2. Convert logo to ICO
    if not convert_logo_to_ico():
        print("Warning: Could not create custom icon, compiling with default system icon.")
        
    # 3. Compile executable
    if not run_pyinstaller():
        print("Build failed at PyInstaller compilation.")
        sys.exit(1)

if __name__ == '__main__':
    main()
