"""
Bilibili收藏夹视频下载器
功能：登录B站账号，获取收藏夹列表，下载收藏夹中的视频，支持多清晰度选择和后台合并
作者：依轨泠QTY
"""

import asyncio
import toml
import qrcode
import sqlite3
import time
import random
import json
import os
import signal
import sys
import io
import threading
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any, Callable
import httpx
import concurrent.futures
import re
import logging
from datetime import datetime, timedelta
from tqdm import tqdm  # 进度条显示
import ffmpeg
import shutil
import subprocess

# ========================
# 系统设置与初始化
# ========================

# 设置系统默认编码为UTF-8，确保中文显示正常
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 配置日志系统
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# 减少HTTPX库的日志输出级别
httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.WARNING)

# 控制台日志处理器配置
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING)
console_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
console_handler.setFormatter(console_formatter)

logger.addHandler(console_handler)
logger.propagate = False  # 防止日志传递给父记录器

# ========================
# 全局常量定义
# ========================

# 配置文件路径
TOKEN_FILE = "bili_token.toml"  # 保存登录token的文件
DB_FILE = ".get_my_favourite.sqlite"  # SQLite数据库文件

# HTTP请求头配置
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Referer": "https://www.bilibili.com"  # 必要的Referer头
}

# 清晰度映射表 (清晰度描述 -> 代码)
QUALITY_MAP = {
    "4K": 120,
    "1080P60": 112,
    "1080P+": 116,
    "1080P": 80,
    "720P60": 74,
    "720P": 64,
    "480P": 32,
    "360P": 16,
    "最低": 6  # 最低清晰度
}

# 清晰度代码到描述的映射 (代码 -> 清晰度描述)
QUALITY_CODE_TO_DESC = {
    120: "4K",
    112: "1080P60",
    116: "1080P+",
    80: "1080P",
    74: "720P60",
    64: "720P",
    32: "480P",
    16: "360P",
    6: "最低"
}

# 非大会员账号可下载的最高清晰度代码
NON_MEMBER_MAX_QUALITY = 80 # 1080P

# ========================
# 全局状态变量
# ========================

interrupted = False  # 程序中断标志
overwrite_all = False  # 覆盖所有文件标志
skip_existing = False  # 跳过所有已存在文件标志

# ========================
# 辅助函数
# ========================

def signal_handler(sig, frame):
    """处理系统中断信号(Ctrl+C)"""
    global interrupted
    interrupted = True
    logger.warning("检测到中断，正在退出...")
    print("\n程序被中断，正在清理资源...")

# 注册信号处理函数
signal.signal(signal.SIGINT, signal_handler)

def sanitize_filename(filename: str) -> str:
    """
    清理文件名中的非法字符，但保留emoji
    参数:
        filename: 原始文件名
    返回:
        清理后的安全文件名
    """
    # 移除Windows文件系统不允许的字符: <>:"/\\|?*
    return re.sub(r'[<>:"/\\|?*]', '', filename)

def shorten_filename(filename: str, max_length: int = 180) -> str:
    """
    缩短文件名以防止路径过长
    参数:
        filename: 原始文件名
        max_length: 最大允许长度(默认180)
    返回:
        缩短后的文件名
    """
    if len(filename) <= max_length:
        return filename
    
    # 分离文件名和扩展名
    name, ext = os.path.splitext(filename)
    # 截断文件名主体部分
    name = name[:max_length - len(ext) - 10]  # 保留10字符给随机后缀
    # 生成8位随机后缀防止冲突
    suffix = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz1234567890', k=8))
    return f"{name}_{suffix}{ext}"

# ========================
# 主下载器类
# ========================

class BiliFavDownloader:
    """Bilibili收藏夹视频下载器主类"""
    
    def __init__(self):
        """初始化下载器实例"""
        self.cookies = {}  # 存储登录cookies
        self.token_data = {}  # 存储登录token数据
        self.all_data = []  # 存储所有收藏夹数据
        self.db_exists = Path(DB_FILE).exists()  # 数据库文件是否存在
        self.is_member = False  # 用户是否为大会员
        self.qr_file = None  # 二维码保存路径(默认不保存)
        self.ffmpeg_available = False  # FFmpeg是否可用
        self.ffmpeg_version = "未知"  # FFmpeg版本信息
        self.ffmpeg_path = None  # FFmpeg可执行文件路径
        self.merge_queue = []  # 音视频合并任务队列
        self.merge_lock = threading.Lock()  # 合并队列的线程锁
        self.merge_thread = None  # 合并线程对象
        self.merge_running = True  # 合并线程运行标志
        self.last_updated = None  # 数据库最后更新时间
        self.current_update_time = None  # 当前更新时间
        self.first_run = not self.db_exists  # 是否首次运行标志
    
    async def initialize(self) -> bool:
        """
        初始化下载器
        步骤:
          1. 检查FFmpeg可用性
          2. 检查并加载token
          3. 二维码登录(如果需要)
          4. 检查会员状态
          5. 启动合并线程
          6. 获取数据库最后更新时间
        返回:
            bool: 初始化是否成功
        """
        global interrupted
        
        # 1. 检查FFmpeg是否可用
        self.check_ffmpeg()
        
        # 2. 检查并加载token
        self.token_data = await self.check_token()
        if not self.token_data:
            print("未检测到登录信息，需要登录...")
            # 3. 二维码登录
            self.token_data = await self.qr_login()
            if interrupted:  # 检查是否在登录过程中被中断
                print("登录过程被中断")
                return False
            if self.token_data:
                self.save_token(self.token_data)
            else:
                print("登录失败，无法继续")
                return False
        
        # 设置cookies
        if self.token_data:
            self.cookies = self.token_data["cookies"]
        
        # 4. 检查会员状态
        if self.cookies:
            try:
                if interrupted:  # 再次检查中断
                    return False
                print("正在检查会员状态...")
                self.is_member = await self.check_member_status()
                if self.is_member:
                    print("检测到大会员账号，可下载高分辨率视频")
                else:
                    print("普通账号，最高可下载1080P分辨率")
            except Exception as e:
                print(f"检查会员状态失败: {str(e)}")
                print("默认使用普通账号模式")
                self.is_member = False
        
        # 5. 启动合并线程
        self.start_merge_thread()
        
        # 6. 获取数据库最后更新时间
        self.get_last_updated_time()
        
        return True
    
    def get_last_updated_time(self):
        """从数据库获取最后更新时间"""
        if not self.db_exists:
            self.last_updated = None
            return
        
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            
            # 检查表结构是否包含last_updated字段
            c.execute("PRAGMA table_info(favorites)")
            columns = [col[1] for col in c.fetchall()]
            if "last_updated" not in columns:
                self.last_updated = None
                return
            
            # 查询最后更新时间
            c.execute("SELECT MAX(last_updated) FROM favorites")
            result = c.fetchone()
            if result and result[0]:
                self.last_updated = datetime.fromisoformat(result[0])
            else:
                self.last_updated = None
        except Exception as e:
            print(f"获取数据库最后更新时间失败: {str(e)}")
            self.last_updated = None
        finally:
            if conn:
                conn.close()
    
    def check_ffmpeg(self):
        """
        检查系统上是否安装了FFmpeg，支持跨平台检测
        按照流程图逻辑：
        1. 检测操作系统类型
        2. Windows: 使用shutil.which进行全局检测
        3. Unix-like (Linux/macOS): 使用which命令进行全局检测
        4. 如果全局检测失败，进行三层向下搜索（程序目录、第一层子目录、第二层子目录）
        5. 对找到的路径进行有效性测试
        6. 如果所有方法都失败，尝试直接运行ffmpeg命令
        """
        import platform
        
        # 获取操作系统信息
        system = platform.system().lower()
        is_windows = system == "windows"
        is_linux = system == "linux"
        is_macos = system == "darwin"
        
        print(f"检测到操作系统: {platform.system()} ({platform.release()})")
        
        # 1. 全局检测（根据操作系统类型使用不同方法）
        global_ffmpeg_path = None
        
        if is_windows:
            # Windows: 使用shutil.which进行全局检测
            global_ffmpeg_path = shutil.which("ffmpeg")
            if global_ffmpeg_path:
                print(f"Windows全局检测: 找到FFmpeg路径 - {global_ffmpeg_path}")
        else:
            # Unix-like (Linux/macOS): 使用which命令进行全局检测
            try:
                result = subprocess.run(
                    ["which", "ffmpeg"],
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore'
                )
                if result.returncode == 0:
                    global_ffmpeg_path = result.stdout.strip()
                    print(f"Unix全局检测: 找到FFmpeg路径 - {global_ffmpeg_path}")
            except Exception as e:
                print(f"Unix全局检测失败: {str(e)}")
        
        # 测试全局检测到的FFmpeg路径
        if global_ffmpeg_path and self._test_ffmpeg_path(global_ffmpeg_path):
            self.ffmpeg_path = global_ffmpeg_path
            self.ffmpeg_available = True
            print(f"FFmpeg检测成功 (全局路径: {self.ffmpeg_path}, 版本: {self.ffmpeg_version})")
            return
        
        # 2. 全局检测失败，进行三层向下搜索
        print("全局检测失败，开始本地搜索...")
        program_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 搜索策略：程序目录 -> 第一层子目录 -> 第二层子目录
        search_depths = [0, 1, 2]  # 0=仅程序目录，1=程序目录+第一层子目录，2=程序目录+第一层+第二层子目录
        
        for depth in search_depths:
            print(f"正在搜索第{depth+1}层目录...")
            local_ffmpeg_path = self._find_ffmpeg_in_directory(program_dir, max_depth=depth)
            
            if local_ffmpeg_path and self._test_ffmpeg_path(local_ffmpeg_path):
                self.ffmpeg_path = local_ffmpeg_path
                self.ffmpeg_available = True
                print(f"FFmpeg检测成功 (本地搜索深度{depth}: {self.ffmpeg_path}, 版本: {self.ffmpeg_version})")
                return
        
        # 3. 如果上述方法都失败，尝试直接运行ffmpeg命令
        print("本地搜索失败，尝试直接运行ffmpeg命令...")
        try:
            # 根据操作系统使用不同的命令
            if is_windows:
                result = subprocess.run(
                    ["ffmpeg", "-version"],
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                result = subprocess.run(
                    ["ffmpeg", "-version"],
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore'
                )
            
            if result.returncode == 0:
                self.ffmpeg_available = True
                self.ffmpeg_path = "ffmpeg"  # 使用命令名称
                self._parse_ffmpeg_version(result.stdout)
                print(f"FFmpeg检测成功 (命令方式, 版本: {self.ffmpeg_version})")
                return
        except Exception as e:
            print(f"直接运行ffmpeg命令失败: {str(e)}")
        
        # 4. 所有方法都失败
        print("警告: 未检测到FFmpeg，DASH格式视频将无法合并音频")
        print("   请安装FFmpeg并添加到系统PATH，或放置在程序目录下")
        print("   下载地址：https://ffmpeg.org/download.html")
        self.ffmpeg_available = False
    
    def _find_ffmpeg_in_directory(self, directory: str, max_depth: int = 2) -> Optional[str]:
        """
        在指定目录中搜索FFmpeg可执行文件，支持多层向下搜索
        参数:
            directory: 起始搜索目录
            max_depth: 最大搜索深度（0=仅当前目录，1=当前目录+第一层子目录，2=当前目录+第一层+第二层子目录）
        返回:
            FFmpeg可执行文件路径，如果未找到则返回None
        """
        ffmpeg_names = ["ffmpeg", "ffmpeg.exe", "ffmpeg.bat"]
        
        # 搜索当前目录
        for file in os.listdir(directory):
            file_path = os.path.join(directory, file)
            if os.path.isfile(file_path) and file.lower() in ffmpeg_names:
                return file_path
        
        # 如果允许深度搜索，搜索子目录
        if max_depth > 0:
            for item in os.listdir(directory):
                item_path = os.path.join(directory, item)
                if os.path.isdir(item_path):
                    # 搜索第一层子目录
                    for sub_file in os.listdir(item_path):
                        sub_file_path = os.path.join(item_path, sub_file)
                        if os.path.isfile(sub_file_path) and sub_file.lower() in ffmpeg_names:
                            return sub_file_path
                    
                    # 如果允许第二层深度搜索，搜索第二层子目录
                    if max_depth > 1:
                        for sub_item in os.listdir(item_path):
                            sub_item_path = os.path.join(item_path, sub_item)
                            if os.path.isdir(sub_item_path):
                                for sub_sub_file in os.listdir(sub_item_path):
                                    sub_sub_file_path = os.path.join(sub_item_path, sub_sub_file)
                                    if os.path.isfile(sub_sub_file_path) and sub_sub_file.lower() in ffmpeg_names:
                                        return sub_sub_file_path
        
        return None
    
    def _test_ffmpeg_path(self, ffmpeg_path: str) -> bool:
        """测试FFmpeg路径是否有效"""
        try:
            result = subprocess.run(
                [ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.returncode == 0:
                self._parse_ffmpeg_version(result.stdout)
                return True
        except Exception:
            pass
        return False
    
    def _parse_ffmpeg_version(self, version_output: str):
        """解析FFmpeg版本信息"""
        try:
            version_line = version_output.split('\n')[0]
            parts = version_line.split(' ')
            self.ffmpeg_version = parts[2] if len(parts) > 2 else "未知"
        except Exception:
            self.ffmpeg_version = "未知"
    
    def start_merge_thread(self):
        """启动后台合并线程"""
        if not self.ffmpeg_available:
            print("合并线程未启动，因为FFmpeg不可用")
            return
        
        self.merge_running = True
        # 创建守护线程，主线程退出时自动结束
        self.merge_thread = threading.Thread(target=self._merge_worker, daemon=True)
        self.merge_thread.start()
        print("后台合并线程已启动")
    
    def stop_merge_thread(self):
        """停止后台合并线程"""
        if self.merge_thread and self.merge_thread.is_alive():
            self.merge_running = False
            self.merge_thread.join(timeout=5.0)  # 等待线程结束
            print("后台合并线程已停止")
    
    def _merge_worker(self):
        """合并工作线程的主函数"""
        print(f"\n合并线程启动 (FFmpeg路径: {self.ffmpeg_path})")
        
        # 持续运行直到收到停止信号且队列为空
        while self.merge_running or self.merge_queue:
            if interrupted:  # 检查全局中断标志
                break
                
            if not self.merge_queue:
                time.sleep(0.5)  # 队列为空时短暂休眠
                continue
            
            # 从队列中获取任务
            with self.merge_lock:
                task = self.merge_queue.pop(0) if self.merge_queue else None
            
            if not task:
                continue
                
            # 解包任务参数
            video_file, audio_file, output_file, title, bvid = task
            
            try:
                print(f"\n开始合并: {title} ({bvid}) [使用FFmpeg]")
                
                # 构建FFmpeg命令
                ffmpeg_cmd = [
                    self.ffmpeg_path,
                    '-i', video_file,  # 输入视频文件
                    '-i', audio_file,  # 输入音频文件
                    '-c', 'copy',      # 流复制模式(不重新编码)
                    '-map', '0:v:0',   # 选择第一个输入的视频流
                    '-map', '1:a:0',   # 选择第二个输入的音频流
                    '-y',               # 覆盖输出文件
                    output_file        # 输出文件
                ]
                
                # 执行FFmpeg命令
                process = subprocess.run(
                    ffmpeg_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    encoding='utf-8',
                    errors='ignore',
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                
                # 检查命令执行结果
                if process.returncode != 0:
                    error_msg = process.stderr if process.stderr else "无错误信息"
                    raise Exception(f"FFmpeg合并失败 (返回码 {process.returncode}): {error_msg}")
                
                # 删除临时文件
                if os.path.exists(video_file):
                    os.remove(video_file)
                if os.path.exists(audio_file):
                    os.remove(audio_file)
                
                print(f"合并完成: {title} ({bvid})\n")
                
            except Exception as e:
                print(f"合并视频失败: {title} ({bvid}) - {str(e)}")
                # 合并失败时尝试保存视频文件
                if os.path.exists(video_file):
                    try:
                        os.rename(video_file, output_file)
                        print(f"已保存视频文件（无音频）: {title}")
                    except Exception:
                        pass
    
    def queue_merge_task(self, video_file: str, audio_file: str, output_file: str, title: str, bvid: str) -> bool:
        """
        将合并任务添加到队列
        参数:
            video_file: 视频临时文件路径
            audio_file: 音频临时文件路径
            output_file: 最终输出文件路径
            title: 视频标题
            bvid: 视频BV号
        返回:
            bool: 是否成功加入队列
        """
        if not self.ffmpeg_available:
            print(f"无法合并: {title} ({bvid}) - FFmpeg不可用")
            return False
        
        # 使用线程锁保证队列操作安全
        with self.merge_lock:
            self.merge_queue.append((video_file, audio_file, output_file, title, bvid))
        
        print(f"\n已加入合并队列: {title} (队列长度: {len(self.merge_queue)})")
        return True
    
    def save_token(self, token_data: Dict):
        """保存token到TOML文件"""
        try:
            with open(TOKEN_FILE, "w") as f:
                toml.dump(token_data, f)
            print(f"登录信息已保存\n")
        except Exception as e:
            print(f"保存登录信息失败: {str(e)}")
    
    async def check_member_status(self) -> bool:
        """检查用户大会员状态，支持自动重新登录"""
        try:
            async with httpx.AsyncClient(headers=HEADERS, cookies=self.cookies, timeout=10.0) as client:
                # 调用API获取用户信息
                resp = await client.get("https://api.bilibili.com/x/web-interface/nav")
                resp.raise_for_status()
                data = resp.json()
                
                # 检查登录状态
                if data.get("code") == -101:
                    print("检测到登录失效，尝试重新登录...")
                    new_token = await self.qr_login()
                    if new_token:
                        self.cookies = new_token["cookies"]
                        self.token_data = new_token
                        self.save_token(new_token)
                        print("重新登录成功，重试会员状态检测...")
                        # 重试一次
                        return await self.check_member_status()
                    else:
                        print("重新登录失败，使用普通账号模式")
                        return False
                
                if data.get("code") == 0:
                    return data["data"].get("vipStatus", 0) == 1
                else:
                    print(f"会员状态API错误: {data.get('message')}")
                    return False
        except Exception as e:
            print(f"检查会员状态失败: {str(e)}")
            return False

    def get_token(self) -> Dict:
        """获取当前token数据"""
        return self.token_data
    
    async def check_token(self) -> Optional[Dict]:
        """检查并加载token文件"""
        if Path(TOKEN_FILE).exists():
            try:
                return toml.load(TOKEN_FILE)
            except Exception as e:
                print(f"读取登录信息失败: {str(e)}")
                # 删除无效的token文件
                try:
                    os.remove(TOKEN_FILE)
                    print("已删除无效的登录信息")
                except:
                    pass
        return None

    async def qr_login(self, qr_output: str = None) -> Optional[Dict]:
        """
        二维码登录流程
        参数:
            qr_output: 二维码图片保存路径(可选)
        返回:
            Dict: 登录成功后的token数据
        """
        print("请打开哔哩哔哩APP扫描二维码登录...")
        
        # 设置二维码输出路径
        if qr_output:
            self.qr_file = qr_output
            print(f"二维码将保存到: {qr_output}")
        else:
            self.qr_file = None
        
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=30.0) as client:
                # 1. 获取二维码信息
                qr_resp = await client.get("https://passport.bilibili.com/x/passport-login/web/qrcode/generate")
                qr_resp.raise_for_status()
                qr_data = qr_resp.json()
                
                if qr_data.get("code") != 0:
                    print(f"获取二维码失败: {qr_data.get('message')}")
                    return None
                
                qr_url = qr_data["data"]["url"]
                qrcode_key = qr_data["data"]["qrcode_key"]
                
                # 2. 创建二维码
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_L,
                    box_size=15,  # 增大box_size以提高分辨率
                    border=2,
                )
                qr.add_data(qr_url)
                qr.make(fit=True)
                
                # 3. 在终端打印二维码
                print("\n终端二维码预览:")
                qr.print_ascii(invert=True)  # 使用ASCII字符打印二维码
                
                # 4. 保存二维码图片(如果需要)
                if self.qr_file:
                    img = qr.make_image(fill_color="black", back_color="white")
                    img = img.resize((600, 600))  # 调整图像大小
                    img.save(self.qr_file)
                    print(f"\n二维码已保存为: {self.qr_file}")
                
                print("\n请使用哔哩哔哩APP扫码登录（二维码有效期为180秒）")
                print("按Ctrl+C可取消登录")
                
                # 5. 轮询登录状态
                for i in range(180):  # 180秒超时
                    if interrupted:
                        print("\n登录过程被中断")
                        return None
                    
                    print(f"\r等待扫码确认... [{i}/180秒]", end="", flush=True)
                    
                    try:
                        # 检查登录状态
                        check_resp = await client.get(
                            "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
                            params={"qrcode_key": qrcode_key},
                            timeout=5.0
                        )
                        check_resp.raise_for_status()
                        check_data = check_resp.json()
                    except httpx.TimeoutException:
                        # 超时继续尝试
                        await asyncio.sleep(1)
                        continue
                    except Exception as e:
                        print(f"\n检查登录状态失败: {str(e)}")
                        await asyncio.sleep(1)
                        continue
                    
                    # 处理不同状态码
                    if check_data.get("data", {}).get("code") == 86038:  # 二维码过期
                        print("\n二维码已过期，请重新运行程序获取新二维码")
                        return None
                    elif check_data.get("data", {}).get("code") == 86039:  # 未扫描
                        await asyncio.sleep(1)
                        continue
                    elif check_data.get("data", {}).get("code") == 0:  # 登录成功
                        # 从响应头解析cookies
                        cookies = self.parse_cookies(str(check_resp.headers.get("set-cookie", "")))
                        if not cookies:
                            print("\n获取登录Cookie失败")
                            return None
                        
                        # 构建token信息
                        token_info = {
                            "cookies": cookies,
                            "timestamp": int(time.time())
                        }
                        print("\n登录成功！")
                        return token_info
                    
                    # 等待1秒后继续
                    await asyncio.sleep(1)
                
                print("\n登录超时，请重试")
                return None
        except Exception as e:
            print(f"\n登录出错: {str(e)}")
            return None
    
    def parse_cookies(self, cookie_header: str) -> Dict:
        """
        从HTTP响应头解析cookies
        参数:
            cookie_header: Set-Cookie头内容
        返回:
            Dict: 解析出的cookies字典
        """
        cookies = {}
        if not cookie_header:
            return cookies
        
        # 解析关键cookies
        for item in cookie_header.split(","):
            item = item.strip()
            if "SESSDATA=" in item:
                cookies["SESSDATA"] = item.split("SESSDATA=")[1].split(";")[0]
            elif "bili_jct=" in item:
                cookies["bili_jct"] = item.split("bili_jct=")[1].split(";")[0]
            elif "DedeUserID=" in item:
                cookies["DedeUserID"] = item.split("DedeUserID=")[1].split(";")[0]
        return cookies

    async def get_favorites(self, session: httpx.AsyncClient) -> List[Dict]:
        """获取用户创建的收藏夹列表，支持自动重新登录"""
        try:
            print("正在获取收藏夹列表...")
            
            # 检查DedeUserID是否存在
            dede_user_id = session.cookies.get("DedeUserID")
            if not dede_user_id:
                print("错误: 未找到DedeUserID，请重新登录")
                return []
            
            # 发送API请求
            resp = await session.get(
                "https://api.bilibili.com/x/v3/fav/folder/created/list-all",
                params={"up_mid": dede_user_id},
                timeout=30.0
            )
            resp.raise_for_status()
            data = resp.json()
            
            # 检查登录失效
            if data.get("code") == -101:
                print("检测到登录失效，尝试重新登录...")
                new_token = await self.qr_login()
                if new_token:
                    # 更新session的cookies
                    session.cookies.update(new_token["cookies"])
                    self.cookies = new_token["cookies"]
                    self.token_data = new_token
                    self.save_token(new_token)
                    print("重新登录成功，重试收藏夹API...")
                    # 重试一次
                    return await self.get_favorites(session)
                else:
                    print("重新登录失败，返回空列表")
                    return []
            
            # 检查API响应状态码
            if data.get("code") != 0:
                error_msg = data.get('message', '未知错误')
                print(f"获取收藏夹列表失败: {error_msg}")
                return []
            
            # 检查data字段是否存在且不为None
            if data.get("data") is None:
                print("错误: API响应中data字段为None")
                return []
            
            # 检查list字段是否存在且不为None
            favorite_list = data["data"].get("list")
            if favorite_list is None:
                print("错误: API响应中list字段为None")
                return []
            
            # 返回收藏夹列表
            return favorite_list
            
        except httpx.TimeoutException:
            print("获取收藏夹列表超时，请检查网络连接")
            return []
        except httpx.HTTPStatusError as e:
            print(f"HTTP错误: {e.response.status_code}")
            return []
        except Exception as e:
            print(f"获取收藏夹列表失败: {str(e)}")
            return []
    
    async def get_favorite_detail(self, session: httpx.AsyncClient, media_id: int, media_count: int) -> List[Dict]:
        """获取指定收藏夹的详细内容"""
        global interrupted
        all_items = []
        page = 1
        page_size = 20  # 每页项目数
        max_retries = 3  # 最大重试次数
        consecutive_failures = 0  # 连续失败次数
        
        try:
            print(f"开始获取收藏夹内容，共约{media_count}项...")
            
            # 创建进度条
            pbar = tqdm(total=media_count, desc=f"收藏夹ID {media_id}", unit="项")
            
            while not interrupted:
                # 随机延迟防止请求过快
                delay = random.uniform(0.1, 0.8)
                await asyncio.sleep(delay)
                
                retry_count = 0
                page_success = False
                items = []
                
                # 重试机制
                while retry_count < max_retries and not page_success and not interrupted:
                    try:
                        # 获取当前页内容
                        resp = await session.get(
                            "https://api.bilibili.com/x/v3/fav/resource/list",
                            params={
                                "media_id": media_id,
                                "ps": page_size,
                                "pn": page,
                                "platform": "web"
                            },
                            timeout=30.0
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        
                        if data.get("code") != 0:
                            error_msg = data.get('message', '未知错误')
                            if page == 1 and retry_count == 0:
                                print(f"获取收藏夹详情失败: {error_msg}")
                            
                            # 如果是登录失效，尝试重新登录
                            if data.get("code") == -101:
                                print("检测到登录失效，尝试重新登录...")
                                new_token = await self.qr_login()
                                if new_token:
                                    # 更新session的cookies
                                    session.cookies.update(new_token["cookies"])
                                    self.cookies = new_token["cookies"]
                                    self.token_data = new_token
                                    self.save_token(new_token)
                                    print("重新登录成功，重试当前页...")
                                    # 重试当前页
                                    retry_count += 1
                                    continue
                            
                            # 其他错误，记录并重试
                            retry_count += 1
                            if retry_count < max_retries:
                                print(f"第{page}页获取失败: {error_msg}, 第{retry_count}次重试...")
                                await asyncio.sleep(1.0)  # 重试前等待
                                continue
                            else:
                                print(f"第{page}页获取失败，已达到最大重试次数: {error_msg}")
                                break
                        
                        # 成功获取数据
                        page_success = True
                        consecutive_failures = 0  # 重置连续失败计数
                        
                        # 提取项目列表
                        items = data["data"].get("medias", [])
                        all_items.extend(items)
                        
                        # 更新进度条（即使items为空也更新0）
                        pbar.update(len(items))
                        
                        # 检查是否还有更多页
                        has_more = data["data"].get("has_more", 0) == 1
                        
                        # 如果has_more=0，检查完成度
                        if not has_more:
                            current_count = len(all_items)
                            if current_count < media_count:
                                print(f"警告: API返回has_more=0，但只获取到{current_count}/{media_count}项")
                                # 可以尝试继续获取下一页，但这里我们尊重API的指示
                        
                        # 判断是否继续获取下一页
                        if not has_more or len(items) < page_size:
                            # 没有更多页或当前页不满，结束循环
                            break
                        
                        # 准备获取下一页
                        page += 1
                        if page > 50:  # 安全限制
                            print("达到最大页数限制(50页)，停止获取")
                            break
                            
                    except httpx.TimeoutException:
                        retry_count += 1
                        if retry_count < max_retries:
                            print(f"第{page}页请求超时，第{retry_count}次重试...")
                            await asyncio.sleep(2.0)  # 超时重试等待更长时间
                            continue
                        else:
                            print(f"第{page}页请求超时，已达到最大重试次数")
                            consecutive_failures += 1
                            break
                    except Exception as e:
                        retry_count += 1
                        if retry_count < max_retries:
                            print(f"第{page}页获取失败: {str(e)}, 第{retry_count}次重试...")
                            await asyncio.sleep(1.0)
                            continue
                        else:
                            print(f"第{page}页获取失败，已达到最大重试次数: {str(e)}")
                            consecutive_failures += 1
                            break
                
                # 如果重试后仍然失败，跳过当前页继续下一页
                if not page_success and retry_count >= max_retries:
                    print(f"跳过第{page}页，继续下一页...")
                    consecutive_failures += 1
                    page += 1
                    # 如果连续失败太多，可能有问题，提前结束
                    if consecutive_failures >= 5:
                        print("连续失败过多，可能网络或API有问题，停止获取")
                        break
                    continue
                
                # 检查是否应该结束循环
                if not page_success or interrupted:
                    break
                
                # 检查是否还有更多页
                if len(items) < page_size:
                    # 当前页不满，通常意味着没有更多数据
                    break
            
            pbar.close()
            current_count = len(all_items)
            print(f"获取完成: {current_count}/{media_count} 项")
            
            # 检查获取完整性
            if current_count < media_count:
                if current_count == 0:
                    print("警告: 未能获取到任何收藏夹内容")
                elif current_count < media_count * 0.5:  # 获取不到一半
                    print(f"警告: 获取不完整，只获取到{current_count}项，应有{media_count}项")
                else:
                    print(f"提示: 获取到{current_count}项，应有{media_count}项")
            
            return all_items
        except Exception as e:
            print(f"\n获取收藏夹详情失败: {str(e)}")
            return all_items

    def upgrade_database(self):
        """升级数据库结构或创建新数据库"""
        if not self.db_exists:
            # 首次运行时创建数据库
            print(f"\n首次运行，创建数据库...")
            try:
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                
                # 创建收藏夹表
                c.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    media_id INTEGER,
                    count INTEGER,
                    last_updated TEXT
                )
                """)
                
                # 创建收藏项表
                c.execute("""
                CREATE TABLE IF NOT EXISTS favorite_items (
                    id TEXT PRIMARY KEY,
                    favorite_id INTEGER,
                    title TEXT,
                    bvid TEXT,
                    owner_name TEXT,
                    FOREIGN KEY(favorite_id) REFERENCES favorites(id)
                )
                """)
                
                conn.commit()
                print("数据库创建成功")
                self.db_exists = True
                self.first_run = True  # 标记为首次运行
            except Exception as e:
                print(f"创建数据库失败: {str(e)}")
            finally:
                if conn:
                    conn.close()
            return
        
        # 已有数据库时的升级逻辑
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            
            # 检查是否有last_updated列
            c.execute("PRAGMA table_info(favorites)")
            columns = [col[1] for col in c.fetchall()]
            if "last_updated" not in columns:
                print("检测到旧版数据库，正在升级...")
                # 添加last_updated列
                c.execute("ALTER TABLE favorites ADD COLUMN last_updated TEXT")
                # 设置默认值
                current_time = datetime.now().isoformat()
                c.execute("UPDATE favorites SET last_updated=?", (current_time,))
                print("数据库升级完成")
            
            conn.commit()
        except Exception as e:
            print(f"数据库升级失败: {str(e)}")
        finally:
            if conn:
                conn.close()

    async def save_to_db(self, data: List[Dict]) -> bool:
        """保存收藏夹数据到数据库"""
        # 确保数据库存在且结构正确
        self.upgrade_database()
        
        conn = None
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            
            # 在保存所有数据前获取当前时间
            current_time = datetime.now().isoformat()
            self.current_update_time = current_time
            
            total_items = 0
            
            # 遍历所有收藏夹
            for folder in data:
                # 检查收藏夹是否存在
                c.execute("SELECT 1 FROM favorites WHERE id=?", (folder["id"],))
                exists = c.fetchone()
                
                if exists:
                    # 更新收藏夹信息
                    c.execute(
                        "UPDATE favorites SET title=?, count=?, last_updated=? WHERE id=?",
                        (folder["title"], folder["media_count"], current_time, folder["id"])
                    )
                else:
                    # 插入新收藏夹
                    c.execute(
                        "INSERT INTO favorites (id, title, media_id, count, last_updated) VALUES (?, ?, ?, ?, ?)",
                        (folder["id"], folder["title"], folder["id"], folder["media_count"], current_time)
                    )
                
                # 删除旧条目
                c.execute("DELETE FROM favorite_items WHERE favorite_id=?", (folder["id"],))
                
                # 插入收藏项
                for item in folder.get("items", []):
                    total_items += 1
                    owner = item.get("upper", {}).get("name", "未知作者") if "upper" in item else "未知作者"
                    bvid = item.get("bvid", "")
                    
                    # 使用组合ID (收藏夹ID_BVID)
                    item_id = f"{folder['id']}_{bvid}"
                    
                    # 插入或忽略重复项
                    c.execute(
                        "INSERT OR IGNORE INTO favorite_items (id, favorite_id, title, bvid, owner_name) VALUES (?, ?, ?, ?, ?)",
                        (item_id, folder["id"], item["title"], bvid, owner)
                    )
            
            conn.commit()
            print(f"成功保存 {len(data)} 个收藏夹，共{total_items}个项目到数据库")
            
            # 更新最后更新时间
            self.last_updated = datetime.fromisoformat(current_time)
            
            return True
        except sqlite3.IntegrityError as e:
            print(f"数据库保存失败 (唯一约束): {str(e)}")
            return False
        except Exception as e:
            print(f"保存到数据库失败: {str(e)}")
            return False
        finally:
            if conn:
                conn.close()

    def print_tree(self, data: List[Dict]):
        """打印收藏夹树形结构"""
        for folder in data:
            print(f"\n📁 {folder['title']} ({folder['media_count']}项)")
            
            items = folder.get("items", [])
            # 最多显示前20项
            for i, item in enumerate(items[:20]):
                prefix = "  ├─" if i < len(items)-1 else "  └─"
                bvid = item.get("bvid", "未知BV号")
                owner = item.get("upper", {}).get("name", "未知作者") if "upper" in item else "未知作者"
                print(f"{prefix} {item['title']} {bvid} by {owner}")
            
            # 如果项目超过20个，显示省略信息
            if len(items) > 20:
                print(f"  └─ ...还有{len(items)-20}项未显示")
            elif folder['media_count'] > len(items):
                print(f"  └─ 获取不完整: 应有{folder['media_count']}项，实际获取{len(items)}项")

    def get_favorite_videos(self, favorite_id: int) -> Tuple[str, List[Tuple[str, str]]]:
        """从数据库获取指定收藏夹的视频列表"""
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            
            # 获取收藏夹标题
            c.execute("SELECT title FROM favorites WHERE id=?", (favorite_id,))
            row = c.fetchone()
            folder_title = row[0] if row else f"收藏夹_{favorite_id}"
            
            # 获取收藏夹中的视频
            c.execute("SELECT title, bvid FROM favorite_items WHERE favorite_id=?", (favorite_id,))
            videos = c.fetchall()
            return folder_title, videos
        except Exception as e:
            print(f"从数据库获取收藏夹视频失败: {str(e)}")
            return f"收藏夹_{favorite_id}", []
        finally:
            if conn:
                conn.close()

    async def get_video_info(self, session: httpx.AsyncClient, bvid: str) -> Optional[Dict]:
        """获取视频详细信息"""
        try:
            resp = await session.get(
                "https://api.bilibili.com/x/web-interface/view",
                params={"bvid": bvid},
                timeout=15.0
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                print(f"获取视频信息失败: {data.get('message')}")
                return None
            return data["data"]  # 返回视频数据
        except Exception as e:
            print(f"获取视频信息失败: {str(e)}")
            return None

    async def get_video_pages(self, session: httpx.AsyncClient, bvid: str) -> Optional[List[Dict]]:
        """获取视频的所有分P信息"""
        try:
            video_info = await self.get_video_info(session, bvid)
            if not video_info:
                return None
            
            # 检查是否有多个分P
            pages = video_info.get("pages", [])
            if len(pages) > 1:
                return pages
            else:
                # 单分P视频，返回包含主分P的列表
                return [{
                    "cid": video_info["cid"],
                    "page": 1,
                    "part": video_info.get("title", "主视频"),
                    "duration": video_info.get("duration", 0)
                }]
        except Exception as e:
            print(f"获取视频分P信息失败: {str(e)}")
            return None

    def parse_page_selection(self, input_str: str, total_pages: int, downloaded_indices: List[int] = None) -> Optional[List[int]]:
        """
        解析用户的分P选择输入
        参数:
            input_str: 用户输入字符串
            total_pages: 总分P数量
            downloaded_indices: 已下载的分P索引列表（可选）
        返回:
            List[int]: 选中的分P索引列表，None表示取消
        """
        if not input_str:
            return list(range(1, total_pages + 1))  # 默认下载所有
        
        input_str = input_str.strip().lower()
        
        # 处理特殊命令
        if input_str in ['a', 'all', '所有']:
            return list(range(1, total_pages + 1))
        elif input_str in ['c', 'cancel', '取消']:
            return None
        elif input_str == 's':
            # 跳过所有已下载分P
            if downloaded_indices:
                # 返回所有未下载的分P
                all_indices = set(range(1, total_pages + 1))
                downloaded_set = set(downloaded_indices)
                selected = sorted(list(all_indices - downloaded_set))
                if not selected:
                    print("所有分P都已下载，没有需要下载的分P")
                    return []
                print(f"跳过已下载分P，将下载: {', '.join(map(str, selected))}")
                return selected
            else:
                print("没有已下载分P信息，将下载所有分P")
                return list(range(1, total_pages + 1))
        
        # 替换中文逗号为英文逗号
        input_str = input_str.replace('，', ',')
        # 替换中文破折号为英文连字符
        input_str = input_str.replace('—', '-')
        
        selected_pages = set()
        
        try:
            # 解析逗号分隔的多个选择
            parts = input_str.split(',')
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                    
                # 检查是否是范围选择 (如: 1-5)
                if '-' in part:
                    range_parts = part.split('-')
                    if len(range_parts) == 2:
                        start = int(range_parts[0].strip())
                        end = int(range_parts[1].strip())
                        if 1 <= start <= total_pages and 1 <= end <= total_pages and start <= end:
                            selected_pages.update(range(start, end + 1))
                        else:
                            print(f"无效范围: {part}")
                            return None
                    else:
                        print(f"无效范围格式: {part}")
                        return None
                else:
                    # 单个数字
                    page_num = int(part)
                    if 1 <= page_num <= total_pages:
                        selected_pages.add(page_num)
                    else:
                        print(f"无效分P号: {page_num}")
                        return None
                        
            return sorted(list(selected_pages))
            
        except ValueError:
            print("输入格式错误，请使用数字、逗号或连字符")
            return None

    async def get_video_url(self, session: httpx.AsyncClient, bvid: str, cid: int, quality: int = 80) -> Optional[Dict]:
        """
        获取视频播放URL
        参数:
            bvid: 视频BV号
            cid: 视频CID
            quality: 清晰度代码
        返回:
            Dict: 包含视频和音频URL的字典
        """
        # 非会员清晰度限制
        if not self.is_member and quality > NON_MEMBER_MAX_QUALITY:
            quality = NON_MEMBER_MAX_QUALITY
        
        # 对于360P和最低清晰度，不使用DASH格式
        use_dash = quality not in [16, 6]  # 16=360P, 6=最低
        
        # 显示使用的格式
        format_type = "DASH" if use_dash else "FLV"
        
        # 获取清晰度描述
        quality_desc = QUALITY_CODE_TO_DESC.get(quality, f"{quality} (未知)")
        
        print(f"清晰度: {quality_desc} ({format_type}格式)")
        
        try:
            # 构建请求参数
            params = {
                "bvid": bvid,
                "cid": cid,
                "qn": quality,
                "fnval": 4048 if use_dash else 0,  # 使用DASH格式
                "fourk": 1,  # 支持4K
                "platform": "pc"
            }
            
            # 获取播放URL
            resp = await session.get(
                "https://api.bilibili.com/x/player/playurl",
                params=params,
                timeout=15.0
            )
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("code") != 0:
                # 回退到非DASH格式
                params["fnval"] = 0
                resp = await session.get(
                    "https://api.bilibili.com/x/player/playurl",
                    params=params,
                    timeout=15.0
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") != 0:
                    return None
                
                # 返回FLV格式URL
                return {
                    "video_url": data["data"]["durl"][0]["url"],
                    "audio_url": None,  # 非DASH格式包含音频
                    "format": "flv"
                }
            
            # 处理DASH格式
            dash_data = data["data"].get("dash")
            if dash_data and use_dash:
                # 获取视频流
                video_streams = dash_data.get("video", [])
                selected_video = None
                for stream in video_streams:
                    if stream.get("id") == quality:
                        selected_video = stream
                        break
                # 如果没有匹配的quality，选择最高质量的视频流
                if not selected_video and video_streams:
                    video_streams.sort(key=lambda x: x.get("id", 0), reverse=True)
                    selected_video = video_streams[0]
                
                # 获取音频流
                audio_streams = dash_data.get("audio", [])
                selected_audio = None
                if audio_streams:
                    # 选择最高质量的音频流
                    audio_streams.sort(key=lambda x: x.get("bandwidth", 0), reverse=True)
                    selected_audio = audio_streams[0]
                
                if selected_video and selected_audio:
                    return {
                        "video_url": selected_video["baseUrl"],
                        "audio_url": selected_audio["baseUrl"],
                        "format": "dash"
                    }
            
            # 非DASH格式或获取失败
            return {
                "video_url": data["data"]["durl"][0]["url"],
                "audio_url": None,
                "format": "flv"
            }
        except Exception as e:
            print(f"获取视频URL失败: {str(e)}")
            return None

    async def download_file(self, url: str, file_path: str, title: str, file_type: str, headers: Dict) -> bool:
        """
        异步下载文件
        参数:
            url: 文件URL
            file_path: 本地保存路径
            title: 文件标题(用于显示)
            file_type: 文件类型(视频/音频)
            headers: HTTP请求头
        返回:
            bool: 下载是否成功
        """
        try:
            # 音频下载换行显示
            if file_type == "音频":
                print(f"\n开始下载{file_type}: {title}")
            else:
                print(f"\n开始下载{file_type}: {title}")
    
            async with httpx.AsyncClient(headers=headers, timeout=60.0) as client:
                # 流式下载
                async with client.stream("GET", url, follow_redirects=True) as response:
                    response.raise_for_status()
                    total_size = int(response.headers.get("Content-Length", 0))
            
                    # 处理无效的文件大小
                    if total_size <= 0:
                        # 尝试从Content-Range头获取文件大小
                        if "Content-Range" in response.headers:
                            try:
                                total_size = int(response.headers["Content-Range"].split("/")[-1])
                            except:
                                # 如果无法确定文件大小，使用默认值
                                total_size = 1024 * 1024  # 1MB
                        else:
                            total_size = 1024 * 1024  # 1MB
            
                    # 创建进度条
                    pbar = tqdm(
                        total=total_size,
                        desc=f"{file_type}下载: {title[:30]}",  # 限制标题长度
                        unit="B",
                        unit_scale=True,
                        unit_divisor=1024,
                        miniters=1,
                        leave=True,  # 完成后不保留显示
                        mininterval=0.1  # 最小更新间隔
                    )
            
                    try:
                        # 初始化进度条
                        pbar.update(0)
                    
                        # 下载文件
                        downloaded_size = 0
                        with open(file_path, "wb") as f:
                            async for chunk in response.aiter_bytes(chunk_size=8192):
                                if interrupted:  # 检查中断
                                    return False
                                f.write(chunk)
                                chunk_size = len(chunk)
                                pbar.update(chunk_size)
                                downloaded_size += chunk_size
                    
                        # 确保进度条完成
                        if downloaded_size < total_size:
                            pbar.update(total_size - downloaded_size)
                    
                        return True
                    finally:
                        # 关闭进度条
                        pbar.close()
            
        except Exception as e:
            print(f"下载{file_type}失败: {title} - {str(e)}")
            # 删除不完整的文件
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
            return False

    async def download_single_video(self, session: httpx.AsyncClient, bvid: str, title: str, output_path: str, quality: int, overwrite: bool = False) -> bool:
        """
        下载单个视频
        参数:
            session: HTTP会话
            bvid: 视频BV号
            title: 视频标题
            output_path: 输出目录
            quality: 清晰度代码
            overwrite: 是否覆盖已存在文件
        返回:
            bool: 下载是否成功
        """
        global interrupted
        
        try:
            # 获取视频的所有分P信息
            pages = await self.get_video_pages(session, bvid)
            if not pages:
                print(f"跳过视频: {title} ({bvid}) - 无法获取视频信息")
                return False
            
            # 如果是多分P视频，让用户选择要下载的分P
            selected_cids = []
            if len(pages) > 1:
                print(f"\n检测到多分P视频: {title} ({bvid})")
                
                # 检查已下载的分P
                downloaded_indices = []
                for i, page in enumerate(pages, 1):
                    part_title = page.get("part", f"分P{i}")
                    safe_title = sanitize_filename(part_title)
                    safe_title = shorten_filename(safe_title)
                    file_path = os.path.join(output_path, f"{safe_title}_{bvid}.mp4")
                    if os.path.exists(file_path):
                        downloaded_indices.append(i)
                
                print("分P列表:")
                for i, page in enumerate(pages, 1):
                    duration_min = page.get("duration", 0) // 60
                    duration_sec = page.get("duration", 0) % 60
                    part_title = page.get("part", f"分P{i}")
                    # 标记已下载的分P
                    if i in downloaded_indices:
                        print(f"  {i}. {part_title} ({duration_min}:{duration_sec:02d}) [已下载]")
                    else:
                        print(f"  {i}. {part_title} ({duration_min}:{duration_sec:02d})")
                
                print("\n请选择要下载的分P:")
                print("  [a/所有/all] 下载所有分P")
                print("  [c/取消/cancel] 取消下载")
                print("  [s] 跳过所有已下载分P")
                print("  [数字] 下载指定分P (如: 1, 2, 3)")
                print("  [范围] 下载范围分P (如: 1-5)")
                print("  [混合] 混合选择 (如: 1,3,5-7)")
                print("请输入选择 (默认下载所有): ", end="", flush=True)
                
                choice = input().strip()
                
                # 解析用户选择，传入已下载分P信息
                selected_indices = self.parse_page_selection(choice, len(pages), downloaded_indices)
                
                if selected_indices is None:
                    if choice and choice not in ['c', 'cancel', '取消']:
                        print("输入无效，将下载所有分P")
                        selected_indices = list(range(1, len(pages) + 1))
                    else:
                        print("取消下载")
                        return False
                
                # 根据选择的索引获取对应的分P
                selected_cids = [(pages[idx-1]["cid"], pages[idx-1].get("part", f"分P{idx}")) for idx in selected_indices]
                print(f"将下载 {len(selected_cids)} 个分P: {', '.join(map(str, selected_indices))}")
            else:
                # 单分P视频
                selected_cids = [(pages[0]["cid"], title)]
            
            # 下载选中的分P
            success_count = 0
            for cid, part_title in selected_cids:
                if interrupted:
                    break
                
                # 为每个分P生成独立的文件名
                safe_title = sanitize_filename(part_title)
                safe_title = shorten_filename(safe_title)
                file_path = os.path.join(output_path, f"{safe_title}_{bvid}.mp4")
                
                # 检查文件是否已存在（即使不在已下载列表中）
                if os.path.exists(file_path):
                    if overwrite:
                        try:
                            os.remove(file_path)
                            print(f"已删除旧文件: {part_title} ({bvid})")
                        except Exception as e:
                            print(f"删除旧文件失败: {part_title} ({bvid}) - {str(e)}")
                            continue
                    else:
                        print(f"文件已存在，跳过下载: {part_title} ({bvid})")
                        continue
                
                # 获取媒体URL
                media_info = await self.get_video_url(session, bvid, cid, quality)
                if not media_info:
                    print(f"跳过分P: {part_title} ({bvid}) - 无法获取下载链接")
                    continue
                
                # 创建输出目录
                os.makedirs(output_path, exist_ok=True)
                
                # 构建请求头
                headers = {
                    "User-Agent": HEADERS["User-Agent"],
                    "Referer": "https://www.bilibili.com",
                    "Cookie": "; ".join([f"{k}={v}" for k, v in session.cookies.items()])
                }
                
                # 下载视频文件
                video_url = media_info["video_url"]
                video_file = os.path.join(output_path, f"{safe_title}_{bvid}_video.tmp")
                
                # 下载视频
                video_success = await self.download_file(
                    video_url, video_file, part_title, "视频", headers
                )
                
                if not video_success:
                    continue
                
                # 下载音频文件（如果是DASH格式）
                audio_file = None
                audio_success = True
                
                if media_info["audio_url"] and self.ffmpeg_available:
                    audio_url = media_info["audio_url"]
                    audio_file = os.path.join(output_path, f"{safe_title}_{bvid}_audio.tmp")
                    
                    # 下载音频
                    audio_success = await self.download_file(
                        audio_url, audio_file, part_title, "音频", headers
                    )
                
                # 处理音频下载失败情况
                if not audio_success:
                    if os.path.exists(video_file):
                        try:
                            os.rename(video_file, file_path)
                            print(f"音频下载失败，已保存视频文件: {part_title}")
                            success_count += 1
                        except Exception as e:
                            print(f"重命名视频文件失败: {part_title} - {str(e)}")
                    continue
                
                # 处理音视频合并
                if audio_file and os.path.exists(audio_file):
                    # 加入合并队列
                    if self.queue_merge_task(video_file, audio_file, file_path, part_title, bvid):
                        success_count += 1
                else:
                    # 非DASH格式，直接重命名视频文件
                    if os.path.exists(video_file):
                        try:
                            os.rename(video_file, file_path)
                            print(f"下载完成: {part_title} ({bvid})")
                            success_count += 1
                        except Exception as e:
                            print(f"重命名视频文件失败: {part_title} - {str(e)}")
            
            return success_count > 0
            
        except Exception as e:
            print(f"下载失败: {title} ({bvid}) - {str(e)}")
            return False

    async def download_favorite_videos(self, session: httpx.AsyncClient, favorite_id: int, output_dir: str, quality: str):
        """
        下载指定收藏夹的所有视频
        参数:
            session: HTTP会话
            favorite_id: 收藏夹ID
            output_dir: 输出目录
            quality: 清晰度描述字符串
        """
        global interrupted, overwrite_all, skip_existing
    
        # 获取收藏夹信息
        folder_title, videos = self.get_favorite_videos(favorite_id)
        if not videos:
            print("该收藏夹中没有视频")
            return
    
        # 创建输出目录
        output_path = os.path.join(output_dir, folder_title)
        os.makedirs(output_path, exist_ok=True)
    
        print(f"开始下载收藏夹: {folder_title} ({len(videos)}个视频)")
        print(f"下载路径: {output_path}")
        print(f"清晰度: {quality}")
    
        # 显示FFmpeg状态
        if self.ffmpeg_available:
            print(f"FFmpeg可用 (版本: {self.ffmpeg_version})")
        else:
            print("FFmpeg不可用，DASH格式视频将无法合并音频")
    
        # 获取清晰度代码
        quality_code = QUALITY_MAP.get(quality, 80)
    
        # 重置全局标志
        overwrite_all = False
        skip_existing = False
    
        download_tasks = []  # 下载任务列表
        skipped_count = 0    # 跳过的视频数
        overwritten_count = 0 # 覆盖的视频数
        new_videos = 0       # 新增的视频数
    
        # 遍历所有视频，处理文件存在情况
        for title, bvid in videos:
            if interrupted:
                break
            
            # 构建安全文件名
            safe_title = sanitize_filename(title)
            safe_title = shorten_filename(safe_title)
            file_path = os.path.join(output_path, f"{safe_title}_{bvid}.mp4")
            file_exists = os.path.exists(file_path)
        
            # 处理跳过所有已存在文件的情况
            if file_exists and skip_existing:
                skipped_count += 1
                continue
            
            # 处理覆盖所有文件的情况
            if file_exists and overwrite_all:
                download_tasks.append((bvid, title, True))
                overwritten_count += 1
                continue
            
            # 文件存在且未设置全局标志，询问用户
            if file_exists and not overwrite_all and not skip_existing:
                print(f"\n视频已存在: {title} ({bvid})")
                print("请选择操作: [s]跳过, [o]覆盖, [a]覆盖所有, [sa]跳过所有, [c]取消 (默认s): ", end='', flush=True)
                choice = input().strip().lower()
                if not choice:
                    choice = "s"
            
                if choice == "s":
                    skipped_count += 1
                    print("跳过下载")
                    continue
                elif choice == "o":
                    download_tasks.append((bvid, title, True))
                    overwritten_count += 1
                elif choice == "a":
                    download_tasks.append((bvid, title, True))
                    overwrite_all = True
                    overwritten_count += 1
                elif choice == "sa":
                    skip_existing = True
                    skipped_count += 1
                    print("跳过所有已存在视频")
                    continue
                elif choice == "c":
                    interrupted = True
                    break
                else:
                    skipped_count += 1
                    print("无效选项，跳过下载")
                    continue
        
            # 文件不存在，添加到下载任务
            if not file_exists:
                download_tasks.append((bvid, title, False))
                new_videos += 1
        
        # 显示处理结果
        print(f"\n下载任务统计:")
        print(f" - 跳过: {skipped_count} 个已存在视频")
        print(f" - 覆盖: {overwritten_count} 个视频")
        print(f" - 新增: {new_videos} 个新视频")
        print(f" - 总计: {len(download_tasks)} 个视频需要下载")
    
        if not download_tasks:
            print("没有需要下载的视频")
            return
    
        # 执行下载任务
        results = []
        for i, (bvid, title, overwrite) in enumerate(download_tasks, 1):
            if interrupted:
                break
            
            print(f"\n[{i}/{len(download_tasks)}] 开始处理视频: {title} ({bvid})")
            result = await self.download_single_video(
                session, bvid, title, output_path, quality_code, overwrite
            )
            results.append(result)
    
        # 等待合并队列完成
        while self.merge_queue and not interrupted:
            queue_size = len(self.merge_queue)
            print(f"等待合并队列完成: 剩余 {queue_size} 个任务...")
            if queue_size > 0:
                print(f"下一个任务: {self.merge_queue[0][3]} ({self.merge_queue[0][4]})")
            await asyncio.sleep(5)
    
        # 统计结果
        success_count = sum(1 for r in results if r)
        failed_count = len(results) - success_count
    
        # 打印最终结果
        if not interrupted:
            print(f"\n收藏夹下载完成: {folder_title}")
            print(f" - 成功: {success_count} 个视频")
            if failed_count > 0:
                print(f" - 失败: {failed_count} 个视频")
            if skipped_count > 0:
                print(f" - 跳过: {skipped_count} 个已存在视频")
            if new_videos > 0:
                print(f" - 新增: {new_videos} 个新视频")

    async def fetch_and_update_favorites(self, session: httpx.AsyncClient) -> bool:
        """
        获取并更新收藏夹数据
        参数:
            session: HTTP会话
        返回:
            bool: 操作是否成功
        """
        global interrupted
        
        # 升级数据库结构
        self.upgrade_database()
        
        # 决定是否更新数据
        default_choice = "n"
        update_reason = ""
        
        # 首次运行强制更新
        if self.first_run:
            default_choice = "y"
            update_reason = " (首次运行需要同步收藏夹)"
            print(f"\n首次运行，需要同步收藏夹...")
        
        # 数据库超过24小时未更新
        elif self.last_updated:
            time_diff = datetime.now() - self.last_updated
            if time_diff > timedelta(hours=24):
                default_choice = "y"
                update_reason = f" (数据库已超过24小时未更新，最后更新于 {self.last_updated.strftime('%Y-%m-%d %H:%M')})"
        
        # 询问用户是否更新
        if self.db_exists and not self.first_run:
            print("\n检测到本地数据库存在")
            
            update = input(f"是否更新收藏夹数据? (y/n, 默认{default_choice}{update_reason}): ").strip().lower() or default_choice
            
            if update == "y":
                print("从B站API获取最新收藏夹数据...")
            else:
                print("使用本地数据库数据")
                return self.load_from_db()  # 从数据库加载
        else:
            print("从B站API获取收藏夹数据...")
        
        # 获取收藏夹列表
        favorites = await self.get_favorites(session)
        if not favorites:
            return False
        
        # 获取每个收藏夹的详细内容
        self.all_data = []
        for fav in favorites:
            if interrupted:
                break
                
            # 随机延迟防止请求过快
            delay = random.uniform(0.1, 0.8)
            await asyncio.sleep(delay)
            
            print(f"\n正在获取收藏夹: {fav['title']} (ID: {fav['id']}, 应有 {fav['media_count']} 项)")
            
            try:
                # 获取收藏夹内容
                items = await self.get_favorite_detail(session, fav["id"], fav["media_count"])
                self.all_data.append({
                    "id": fav["id"],
                    "title": fav["title"],
                    "media_count": fav["media_count"],
                    "items": items
                })
            except Exception as e:
                print(f"  └─ 获取失败: {str(e)}")
        
        # 保存到数据库
        if not interrupted and self.all_data:
            success = await self.save_to_db(self.all_data)
            self.first_run = False  # 重置首次运行标志
            return success
        else:
            return False

    def load_from_db(self) -> bool:
        """从数据库加载收藏夹数据"""
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            
            # 查询收藏夹
            c.execute("SELECT id, title, media_id, count, last_updated FROM favorites")
            folders = c.fetchall()
            
            self.all_data = []
            # 处理每个收藏夹
            for folder in folders:
                # 查询收藏项
                c.execute("SELECT title, bvid, owner_name FROM favorite_items WHERE favorite_id=?", (folder[0],))
                items_rows = c.fetchall()
                items = [
                    {
                        "title": row[0],
                        "bvid": row[1],
                        "upper": {"name": row[2]}  # 构建类似API的结构
                    }
                    for row in items_rows
                ]
                
                # 添加到数据列表
                self.all_data.append({
                    "id": folder[0],
                    "title": folder[1],
                    "media_id": folder[2],
                    "media_count": folder[3],
                    "last_updated": folder[4],
                    "items": items
                })
            
            print(f"成功加载 {len(self.all_data)} 个收藏夹")
            return True
        except Exception as e:
            print(f"数据库加载失败: {str(e)}")
            return False
        finally:
            if conn:
                conn.close()

    async def run(self):
        """下载器主运行方法"""
        global interrupted
        
        # 打印欢迎信息
        print("="*50)
        print("B站收藏夹视频下载器")
        print("="*50)
        print("正在初始化...")
        
        # 初始化下载器
        try:
            init_result = await self.initialize()
            if not init_result:
                print("初始化失败，请重试")
                # 提供更多调试信息
                if not self.token_data:
                    print("原因：未获取到有效的登录信息")
                elif not self.cookies:
                    print("原因：未正确设置Cookies")
                return
        except Exception as e:
            print(f"初始化失败: {str(e)}")
            return
        
        # 检查中断
        if interrupted:
            print("初始化后检测到中断，退出程序")
            return
            
        # 创建HTTP会话
        async with httpx.AsyncClient(
            headers=HEADERS,
            cookies=self.cookies,
            timeout=60.0
        ) as session:
            # 再次检查中断
            if interrupted:
                print("初始化后检测到中断，退出程序")
                return
                
            # 主操作循环
            while not interrupted:
                print("\n请选择操作: 1. 下载收藏夹视频  2. 直接下载视频  3. 退出")
                print("请输入选项 (默认1): ", end="")
                
                choice = input().strip()
                if not choice:
                    choice = "1"
                
                if choice == "1":
                    # 获取并更新收藏夹数据
                    success = await self.fetch_and_update_favorites(session)
                    
                    if interrupted:
                        print("获取收藏夹后检测到中断，退出程序")
                        break
                        
                    # 显示收藏夹内容
                    if success and self.all_data:
                        print("\n收藏夹内容:")
                        self.print_tree(self.all_data)
                        
                        # 显示收藏夹列表
                        print("\n收藏夹列表:")
                        for folder in self.all_data:
                            print(f"ID: {folder['id']} - {folder['title']} ({folder['media_count']}项)")
                        
                        # 获取用户选择的收藏夹ID
                        print("\n请输入要下载的收藏夹ID: ", end="")
                        fav_id = input().strip()
                        if not fav_id.isdigit():
                            print("输入错误，请重新输入")
                            continue
                        fav_id = int(fav_id)
                        
                        # 验证收藏夹ID是否存在
                        found = False
                        for folder in self.all_data:
                            if folder['id'] == fav_id:
                                found = True
                                break
                        if not found:
                            print("收藏夹ID不存在")
                            continue
                        
                        # 创建清晰度选项列表
                        quality_options = list(QUALITY_MAP.keys())
                        
                        # 显示清晰度选项
                        print("\n可用清晰度:")
                        for i, q in enumerate(quality_options, 1):
                            print(f"{i}. {q}")
                        
                        # 获取用户选择的清晰度
                        default_quality_index = quality_options.index('1080P') + 1 if '1080P' in quality_options else 4
                        print(f"请选择清晰度 (1-{len(quality_options)}, 默认{default_quality_index}): ", end="")
                        quality_choice = input().strip()
                        
                        # 处理默认值
                        if not quality_choice:
                            quality_choice = str(default_quality_index)
                        
                        # 验证并获取清晰度
                        if quality_choice.isdigit():
                            choice_index = int(quality_choice) - 1
                            if 0 <= choice_index < len(quality_options):
                                quality = quality_options[choice_index]
                            else:
                                print(f"输入超出范围，使用默认{quality_options[default_quality_index-1]}")
                                quality = quality_options[default_quality_index-1]
                        else:
                            print(f"无效输入，使用默认{quality_options[default_quality_index-1]}")
                            quality = quality_options[default_quality_index-1]
                        
                        # 非会员清晰度调整
                        if not self.is_member and QUALITY_MAP.get(quality, 0) > NON_MEMBER_MAX_QUALITY:
                            print(f"普通账号最高支持1080P，已自动调整为1080P")
                            quality = "1080P"
                        
                        # 获取输出目录
                        print("请输入下载路径 (默认./favourite_download): ", end="")
                        output_dir = input().strip() or "./favourite_download"
                        
                        # 开始下载
                        if interrupted:
                            print("开始下载前检测到中断，退出程序")
                            break
                        
                        await self.download_favorite_videos(session, fav_id, output_dir, quality)
                    else:
                        print("未能获取收藏夹数据")
                elif choice == "2":
                    await self.download_single_video_direct(session)
                elif choice == "3":
                    print("退出程序")
                    break
                else:
                    print("无效选项，请重新输入")
    
        # 停止合并线程
        self.stop_merge_thread()

    def extract_bvid_from_input(self, input_str: str) -> Optional[str]:
        """
        从用户输入中提取BV号
        支持格式:
        - BV号: BV1zsnBzGEzC
        - 完整链接: https://www.bilibili.com/video/BV1zsnBzGEzC/
        - 完整链接: www.bilibili.com/video/BV1zsnBzGEzC/
        - 部分链接: bilibili.com/video/BV1zsnBzGEzC
        - 部分链接: /video/BV1zsnBzGEzC
        - 部分链接: video/BV1zsnBzGEzC
        - 部分链接: com/video/BV1zsnBzGEzC
        - 带参数链接: BV1zsnBzGEzC?spm_id_from=333.788
        - CID: 直接使用CID
        """
        if not input_str:
            return None
        
        input_str = input_str.strip()
        
        # 1. 检查是否是纯BV号格式
        if input_str.startswith('BV') and len(input_str) >= 10:
            # 处理带参数的BV号，如: BV1zsnBzGEzC?spm_id_from=333.788
            if '?' in input_str:
                return input_str.split('?')[0]
            return input_str
        
        # 2. 使用正则表达式从各种格式中提取BV号
        import re
        pattern = r'BV[a-zA-Z0-9]{10,}'
        match = re.search(pattern, input_str)
        if match:
            bvid = match.group()
            # 验证提取的BV号是否有效
            if bvid.startswith('BV') and len(bvid) >= 10:
                return bvid
        
        # 3. 如果是纯数字，可能是CID，返回None让调用方处理
        if input_str.isdigit():
            return None
        
        return None

    async def download_single_video_direct(self, session: httpx.AsyncClient):
        """
        直接下载单个视频
        支持输入: BV号、链接、CID
        """
        global interrupted
        
        print("\n直接下载视频")
        print("支持输入格式:")
        print("  - BV号: BV1zsnBzGEzC")
        print("  - 完整链接: https://www.bilibili.com/video/BV1zsnBzGEzC/")
        print("  - 部分链接: com/video/BV1zsnBzGEzC")
        print("  - 带参数链接: BV1zsnBzGEzC?spm_id_from=333.788")
        print("  - CID: 直接输入CID")
        print("说明: 只要包含完整的BV号即可识别")
        
        while True:
            print("\n请输入视频标识 (输入'q'返回主菜单): ", end="")
            video_input = input().strip()
            
            if video_input.lower() == 'q':
                return
            
            if not video_input:
                print("输入不能为空")
                continue
            
            # 提取BV号
            bvid = self.extract_bvid_from_input(video_input)
            
            if bvid:
                # 使用BV号下载
                print(f"检测到BV号: {bvid}")
                await self.download_by_bvid(session, bvid)
                break
            elif video_input.isdigit():
                # 使用CID下载
                cid = int(video_input)
                print(f"使用CID: {cid}")
                await self.download_by_cid(session, cid)
                break
            else:
                print("无法识别输入格式，请重新输入")

    async def download_by_bvid(self, session: httpx.AsyncClient, bvid: str):
        """通过BV号下载视频"""
        global interrupted
        
        # 获取视频信息
        video_info = await self.get_video_info(session, bvid)
        if not video_info:
            print(f"无法获取视频信息: {bvid}")
            return
        
        title = video_info.get("title", "未知标题")
        print(f"视频标题: {title}")
        
        # 获取清晰度
        quality_options = list(QUALITY_MAP.keys())
        print("\n可用清晰度:")
        for i, q in enumerate(quality_options, 1):
            print(f"{i}. {q}")
        
        default_quality_index = quality_options.index('1080P') + 1 if '1080P' in quality_options else 4
        print(f"请选择清晰度 (1-{len(quality_options)}, 默认{default_quality_index}): ", end="")
        quality_choice = input().strip()
        
        if not quality_choice:
            quality_choice = str(default_quality_index)
        
        if quality_choice.isdigit():
            choice_index = int(quality_choice) - 1
            if 0 <= choice_index < len(quality_options):
                quality = quality_options[choice_index]
            else:
                print(f"输入超出范围，使用默认{quality_options[default_quality_index-1]}")
                quality = quality_options[default_quality_index-1]
        else:
            print(f"无效输入，使用默认{quality_options[default_quality_index-1]}")
            quality = quality_options[default_quality_index-1]
        
        # 非会员清晰度调整
        if not self.is_member and QUALITY_MAP.get(quality, 0) > NON_MEMBER_MAX_QUALITY:
            print(f"普通账号最高支持1080P，已自动调整为1080P")
            quality = "1080P"
        
        # 获取输出目录
        print("请输入下载路径 (默认./direct_download): ", end="")
        output_dir = input().strip() or "./direct_download"
        
        # 创建输出目录
        os.makedirs(output_dir, exist_ok=True)
        
        # 获取清晰度代码
        quality_code = QUALITY_MAP.get(quality, 80)
        
        # 下载视频
        success = await self.download_single_video(
            session, bvid, title, output_dir, quality_code, False
        )
        
        if success:
            print(f"视频下载完成: {title}")
        else:
            print(f"视频下载失败: {title}")

    async def download_by_cid(self, session: httpx.AsyncClient, cid: int):
        """通过CID下载视频"""
        global interrupted
        
        print("通过CID下载功能需要BV号信息，请先提供BV号")
        print("请输入BV号: ", end="")
        bvid = input().strip()
        
        if not bvid.startswith('BV'):
            print("无效的BV号格式")
            return
        
        # 获取视频信息验证CID
        video_info = await self.get_video_info(session, bvid)
        if not video_info:
            print(f"无法获取视频信息: {bvid}")
            return
        
        # 检查CID是否有效
        pages = await self.get_video_pages(session, bvid)
        valid_cids = [page["cid"] for page in pages]
        
        if cid not in valid_cids:
            print(f"CID {cid} 在视频 {bvid} 中不存在")
            print(f"有效的CID: {valid_cids}")
            return
        
        # 找到对应的分P标题
        part_title = "未知分P"
        for page in pages:
            if page["cid"] == cid:
                part_title = page.get("part", "未知分P")
                break
        
        print(f"找到分P: {part_title} (CID: {cid})")
        
        # 获取清晰度
        quality_options = list(QUALITY_MAP.keys())
        print("\n可用清晰度:")
        for i, q in enumerate(quality_options, 1):
            print(f"{i}. {q}")
        
        default_quality_index = quality_options.index('1080P') + 1 if '1080P' in quality_options else 4
        print(f"请选择清晰度 (1-{len(quality_options)}, 默认{default_quality_index}): ", end="")
        quality_choice = input().strip()
        
        if not quality_choice:
            quality_choice = str(default_quality_index)
        
        if quality_choice.isdigit():
            choice_index = int(quality_choice) - 1
            if 0 <= choice_index < len(quality_options):
                quality = quality_options[choice_index]
            else:
                print(f"输入超出范围，使用默认{quality_options[default_quality_index-1]}")
                quality = quality_options[default_quality_index-1]
        else:
            print(f"无效输入，使用默认{quality_options[default_quality_index-1]}")
            quality = quality_options[default_quality_index-1]
        
        # 非会员清晰度调整
        if not self.is_member and QUALITY_MAP.get(quality, 0) > NON_MEMBER_MAX_QUALITY:
            print(f"普通账号最高支持1080P，已自动调整为1080P")
            quality = "1080P"
        
        # 获取输出目录
        print("请输入下载路径 (默认./direct_download): ", end="")
        output_dir = input().strip() or "./direct_download"
        
        # 创建输出目录
        os.makedirs(output_dir, exist_ok=True)
        
        # 获取清晰度代码
        quality_code = QUALITY_MAP.get(quality, 80)
        
        # 下载指定分P
        success = await self.download_single_video_by_cid(
            session, bvid, cid, part_title, output_dir, quality_code
        )
        
        if success:
            print(f"分P下载完成: {part_title}")
        else:
            print(f"分P下载失败: {part_title}")

    async def download_single_video_by_cid(self, session: httpx.AsyncClient, bvid: str, cid: int, title: str, output_path: str, quality: int) -> bool:
        """通过CID下载单个分P视频"""
        global interrupted
        
        try:
            # 为分P生成独立的文件名
            safe_title = sanitize_filename(title)
            safe_title = shorten_filename(safe_title)
            file_path = os.path.join(output_path, f"{safe_title}_{bvid}.mp4")
            
            # 获取媒体URL
            media_info = await self.get_video_url(session, bvid, cid, quality)
            if not media_info:
                print(f"跳过分P: {title} ({bvid}) - 无法获取下载链接")
                return False
            
            # 构建请求头
            headers = {
                "User-Agent": HEADERS["User-Agent"],
                "Referer": "https://www.bilibili.com",
                "Cookie": "; ".join([f"{k}={v}" for k, v in session.cookies.items()])
            }
            
            # 下载视频文件
            video_url = media_info["video_url"]
            video_file = os.path.join(output_path, f"{safe_title}_{bvid}_video.tmp")
            
            # 下载视频
            video_success = await self.download_file(
                video_url, video_file, title, "视频", headers
            )
            
            if not video_success:
                return False
            
            # 下载音频文件（如果是DASH格式）
            audio_file = None
            audio_success = True
            
            if media_info["audio_url"] and self.ffmpeg_available:
                audio_url = media_info["audio_url"]
                audio_file = os.path.join(output_path, f"{safe_title}_{bvid}_audio.tmp")
                
                # 下载音频
                audio_success = await self.download_file(
                    audio_url, audio_file, title, "音频", headers
                )
            
            # 处理音频下载失败情况
            if not audio_success:
                if os.path.exists(video_file):
                    try:
                        os.rename(video_file, file_path)
                        print(f"音频下载失败，已保存视频文件: {title}")
                        return True
                    except Exception as e:
                        print(f"重命名视频文件失败: {title} - {str(e)}")
                return False
            
            # 处理音视频合并
            if audio_file and os.path.exists(audio_file):
                # 加入合并队列
                if self.queue_merge_task(video_file, audio_file, file_path, title, bvid):
                    return True
            else:
                # 非DASH格式，直接重命名视频文件
                if os.path.exists(video_file):
                    try:
                        os.rename(video_file, file_path)
                        print(f"下载完成: {title} ({bvid})")
                        return True
                    except Exception as e:
                        print(f"重命名视频文件失败: {title} - {str(e)}")
            
            return False
            
        except Exception as e:
            print(f"下载失败: {title} ({bvid}) - {str(e)}")
            return False

# ========================
# 程序入口
# ========================

if __name__ == "__main__":
    downloader = None
    try:
        # 创建下载器实例并运行
        downloader = BiliFavDownloader()
        asyncio.run(downloader.run())
    except Exception as e:
        print(f"程序发生错误: {str(e)}")
    finally:
        # 确保合并线程被停止
        if downloader and hasattr(downloader, 'stop_merge_thread'):
            downloader.stop_merge_thread()
