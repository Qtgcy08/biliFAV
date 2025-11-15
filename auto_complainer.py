import os
import re
import sys
import subprocess
from pathlib import Path
import shutil
import platform

def read_current_version():
    """读取当前版本号 (格式: X.Y.Z)"""
    try:
        with open("complainer_count.txt", "r", encoding="utf-8") as f:
            content = f.read().strip()
            match = re.match(r"(\d+\.\d+\.\d+)", content)
            if match:
                return match.group(1)
    except FileNotFoundError:
        pass
    # 默认版本号
    return "5.21.1"

def increment_version(version):
    """版本号自增 (格式: X.Y.Z)"""
    parts = list(map(int, version.split('.')))
    parts[-1] += 1  # 最后一位自增
    return ".".join(map(str, parts))

def write_new_version(version):
    """写入新版本号"""
    with open("complainer_count.txt", "w", encoding="utf-8") as f:
        f.write(version)

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
    
    raise FileNotFoundError("无法找到nuitka可执行文件。请确保已安装Nuitka (pip install nuitka)")

def run_nuitka(current_version, new_version):
    """执行Nuitka编译命令"""
    source_file = "./biliFAV.py"
    if not Path(source_file).exists():
        raise FileNotFoundError(f"源文件 {source_file} 不存在")

    # 创建输出目录
    exe_dir = Path("./exe")
    exe_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成带新版本号的输出文件名
    output_filename = f"biliFAV_win_x64_{new_version}.exe"
    
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
        "--windows-company-name=依轨泠QTY",
        "--windows-product-name=哔哩哔哩收藏夹下载工具",
        f"--windows-product-version={new_version}",  # 使用新版本号
        "--windows-file-description=哔哩哔哩收藏夹下载工具，支持扫描登录，使用sqlite3保存收藏夹数据，使用ffmpeg合并音视频，请确保ffmpeg已添加到系统PATH",
        "--follow-imports",
        #"--clang",
        "--msvc=latest",
        "--lto=yes",
        "--show-progress",
        #"--remove-output",
        source_file
    ])

    # 执行命令并实时输出
    print("执行命令:", " ".join(cmd),f"\n")
    
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
        print("\n[!] 检测到中断信号，终止编译过程...")
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
        new_version = increment_version(current_version)
        
        print(f"当前版本: {current_version}")
        print(f"将编译为新版本: {new_version}\n")

        # 执行编译（使用新版本号）
        exit_code = run_nuitka(current_version, new_version)
        
        if exit_code == 0:
            print(f"\n[✓] 编译成功，更新版本号为: {new_version}")
            write_new_version(new_version)
            
            # 显示输出文件路径
            exe_path = Path("./exe") / f"biliFAV_win_x64_{new_version}.exe"
            print(f"已生成可执行文件: {exe_path}")
        else:
            print(f"\n[×] 编译失败，保持版本号不变 (退出码: {exit_code})")
            sys.exit(1)

    except Exception as e:
        print(f"\n[!] 发生错误: {str(e)}")
        print("请确保已安装Nuitka: pip install nuitka")
        print("如果已安装，请尝试将Python脚本目录添加到PATH环境变量")
        sys.exit(1)

if __name__ == "__main__":
    main()
