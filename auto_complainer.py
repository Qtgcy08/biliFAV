import os
import re
import sys
import subprocess
from pathlib import Path
import shutil
import platform
import io

# Force UTF-8 encoding environment
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def read_current_version():
    """Read current version from pyproject.toml (format: X.Y.Z)"""
    try:
        with open("pyproject.toml", "r", encoding="utf-8") as f:
            content = f.read()
            # Use regex to match version number
            match = re.search(r'version\s*=\s*"([^"]+)"', content)
            if match:
                version = match.group(1)
                if validate_version_format(version):
                    return version
    except FileNotFoundError:
        pass
    # Default version number
    return "7.12.1"

def increment_version(version):
    """Increment version number (format: X.Y.Z)"""
    parts = list(map(int, version.split('.')))
    parts[-1] += 1  # Increment last digit
    return ".".join(map(str, parts))

def validate_version_format(version):
    """Validate version format"""
    return bool(re.match(r"^\d+\.\d+\.\d+$", version))

def write_new_version(version):
    """Write new version to pyproject.toml"""
    try:
        with open("pyproject.toml", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Replace version number
        new_content = re.sub(
            r'version\s*=\s*"[^"]+"',
            f'version = "{version}"',
            content
        )
        
        with open("pyproject.toml", "w", encoding="utf-8") as f:
            f.write(new_content)
        
        print(f"[OK] Updated pyproject.toml version to: {version}")
    except Exception as e:
        print(f"[ERROR] Failed to update pyproject.toml version: {str(e)}")
        raise

def find_nuitka():
    """Try to find nuitka executable path"""
    try:
        subprocess.check_call(["nuitka", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "nuitka"
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    
    try:
        subprocess.check_call([sys.executable, "-m", "nuitka", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return [sys.executable, "-m", "nuitka"]
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    
    python_dir = os.path.dirname(sys.executable)
    nuitka_path = os.path.join(python_dir, "nuitka")
    if platform.system() == "Windows":
        nuitka_path += ".exe"
    
    if os.path.exists(nuitka_path):
        return nuitka_path
    
    raise FileNotFoundError("Cannot find nuitka executable. Please ensure Nuitka is installed (pip install nuitka)")

def run_nuitka(current_version, new_version):
    """Execute Nuitka compilation command"""
    source_file = "./biliFAV.py"
    if not Path(source_file).exists():
        raise FileNotFoundError(f"Source file {source_file} does not exist")

    # Create output directory
    exe_dir = Path("./exe")
    exe_dir.mkdir(parents=True, exist_ok=True)
    
    # Detect system architecture and generate output filename (Windows only supports x64 and arm64)
    arch = platform.machine().lower()
    if arch in ['amd64', 'x86_64']:
        arch_name = "x64"
    elif arch in ['arm64', 'aarch64']:
        arch_name = "arm64"
    else:
        # Default to x64 because x86 no longer supports Python
        arch_name = "x64"
        print(f"Warning: Unknown architecture '{arch}' detected, defaulting to x64")
    
    # Generate output filename with new version and architecture
    output_filename = f"biliFAV_win_{arch_name}_{new_version}.exe"
    
    # Get nuitka command
    nuitka_cmd = find_nuitka()
    if isinstance(nuitka_cmd, list):
        cmd = nuitka_cmd
    else:
        cmd = [nuitka_cmd]
    
    # Set encoding environment
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    
    # Add compilation parameters
    cmd.extend([
        "--onefile",
        "--standalone",
        f"--output-dir={exe_dir}",
        f"--output-filename={output_filename}",
        "--windows-product-name=Bilibili Favorite Downloader",
        f"--windows-product-version={new_version}",  # Use new version number
        "--windows-file-description=Bilibili favorite video downloader with QR code login, SQLite database, and FFmpeg audio/video merging",
        "--follow-imports",
        #"--clang",
        "--msvc=latest",
        "--lto=yes",
        #"--remove-output",
        "--assume-yes-for-downloads",  # Automatically accept downloads to avoid Dependency Walker prompt
        source_file
    ])

    # Execute command with real-time output
    print("Executing command:", " ".join(cmd),f"\n")
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        universal_newlines=True,
        env=env  # Pass encoding environment
    )

    try:
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                print(output.strip())
        return process.poll()
    except KeyboardInterrupt:
        print("\n[!] Interrupt signal detected, terminating compilation process...")
        process.terminate()
        return 1
    finally:
        # Clean up temporary directories
        build_dir = Path("./biliFAV.build")
        if build_dir.exists():
            shutil.rmtree(build_dir, ignore_errors=True)
        dist_dir = Path("./biliFAV.dist")
        if dist_dir.exists():
            shutil.rmtree(dist_dir, ignore_errors=True)

def main():
    try:
        # Read current version number
        current_version = read_current_version()
        
        # Validate version format
        if not validate_version_format(current_version):
            print(f"[ERROR] Invalid version format: {current_version}")
            print("Version format should be: X.Y.Z (e.g., 7.12.1)")
            sys.exit(1)
        
        new_version = increment_version(current_version)
        
        print(f"Current version: {current_version}")
        print(f"Will compile as new version: {new_version}\n")

        # Execute compilation (using new version number)
        exit_code = run_nuitka(current_version, new_version)
        
        if exit_code == 0:
            print(f"\n[OK] Compilation successful, updating version to: {new_version}")
            write_new_version(new_version)
            
            # 显示输出文件路径
            exe_path = Path("./exe") / f"biliFAV_win_x64_{new_version}.exe"
            print(f"Generated executable: {exe_path}")
            
            # 验证版本更新
            updated_version = read_current_version()
            if updated_version == new_version:
                print(f"[OK] Version file update verified: {updated_version}")
            else:
                print(f"[ERROR] Version file update mismatch: expected {new_version}, got {updated_version}")
        else:
            print(f"\n[FAILED] Compilation failed, keeping version unchanged (exit code: {exit_code})")
            sys.exit(1)

    except Exception as e:
        print(f"\n[ERROR] An error occurred: {str(e)}")
        print("Please ensure Nuitka is installed: pip install nuitka")
        print("If already installed, try adding Python scripts directory to PATH environment variable")
        sys.exit(1)

if __name__ == "__main__":
    main()
