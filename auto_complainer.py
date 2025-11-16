import os
import re
import sys
import subprocess
from pathlib import Path
import shutil
import platform
import io

# 强制设置UTF-8编码环境
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def read_current_version():
    """从pyproject.toml读取当前版本号 (格式: X.Y.Z)"""
    try:
        with open("pyproject.toml", "r", encoding="utf-8") as f:
            content = f.read()
            # 使用正则表达式匹配版本号
            match = re.search(r'version\s*=\s*"([^"]+)"', content)
            if match:
                version = match.group(1)
                if validate_version_format(version):
                    return version
    except FileNotFoundError:
        pass
    # 默认版本号
    return "7.12.1"

def increment_version(version):
    """版本号自增 (格式: X.Y.Z)"""
    parts = list(map(int, version.split('.')))
    parts[-1] += 1  # 最后一位自增
    return ".".join(map(str, parts))

def validate_version_format(version):
    """验证版本号格式是否正确"""
    return bool(re.match(r"^\d+\.\d+\.\d+$", version))

def write_new_version(version):
    """写入新版本号到pyproject.toml"""
    try:
        with open("pyproject.toml", "r", encoding="utf-8") as f:
            content = f.read()
        
        # 替换版本号
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
    """尝试找到nuitka可执行文件路径"""
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
    """执行Nuitka编译命令"""
    source_file = "./biliFAV.py"
    if not Path(source_file).exists():
        raise FileNotFoundError(f"源文件 {source_file} 不存在")

    # 创建输出目录
    exe_dir = Path("./exe")
    exe_dir.mkdir(parents=True, exist_ok=True)
    
    # 检测系统架构并生成输出文件名 (Windows只支持x64和arm64)
    arch = platform.machine().lower()
    if arch in ['amd64', 'x86_64']:
        arch_name = "x64"
    elif arch in ['arm64', 'aarch64']:
        arch_name = "arm64"
    else:
        # 默认使用x64，因为x86不再支持Python
        arch_name = "x64"
        print(f"Warning: Unknown architecture '{arch}' detected, defaulting to x64")
    
    # 生成带新版本号和架构的输出文件名
    output_filename = f"biliFAV_win_{arch_name}_{new_version}.exe"
    
    # 获取nuitka命令
    nuitka_cmd = find_nuitka()
    if isinstance(nuitka_cmd, list):
        cmd = nuitka_cmd
    else:
        cmd = [nuitka_cmd]
    
    # 设置中文编码环境
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    
    # 添加编译参数
    cmd.extend([
        "--onefile",
        "--standalone",
        f"--output-dir={exe_dir}",
        f"--output-filename={output_filename}",
        "--windows-product-name=Bilibili Favorite Downloader",
        f"--windows-product-version={new_version}",  # 使用新版本号
        "--windows-file-description=Bilibili favorite video downloader with QR code login, SQLite database, and FFmpeg audio/video merging",
        "--follow-imports",
        #"--clang",
        "--msvc=latest",
        "--lto=yes",
        "--show-progress",
        #"--remove-output",
        source_file
    ])

    # 执行命令并实时输出
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
        env=env  # 传递编码环境
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
        # 清理临时目录
        build_dir = Path("./biliFAV.build")
        if build_dir.exists():
            shutil.rmtree(build_dir, ignore_errors=True)
        dist_dir = Path("./biliFAV.dist")
        if dist_dir.exists():
            shutil.rmtree(dist_dir, ignore_errors=True)

def main():
    try:
        # 读取当前版本号
        current_version = read_current_version()
        
        # 验证版本格式
        if not validate_version_format(current_version):
            print(f"[ERROR] Invalid version format: {current_version}")
            print("Version format should be: X.Y.Z (e.g., 7.12.1)")
            sys.exit(1)
        
        new_version = increment_version(current_version)
        
        print(f"Current version: {current_version}")
        print(f"Will compile as new version: {new_version}\n")

        # 执行编译（使用新版本号）
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
