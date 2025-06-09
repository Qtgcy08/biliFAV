import asyncio
import aiohttp
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
from tqdm import tqdm
import ffmpeg
import shutil
import subprocess

# 设置系统默认编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# 减少HTTPX的详细日志
httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.WARNING)

# 控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING)
console_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
console_handler.setFormatter(console_formatter)

logger.addHandler(console_handler)
logger.propagate = False

# 配置文件路径
TOKEN_FILE = "bili_token.toml"
DB_FILE = ".get_my_favourite.sqlite"

# 请求头配置
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Referer": "https://www.bilibili.com"
}

# 扩展清晰度映射表
QUALITY_MAP = {
    "4K": 120,
    "1080P60": 112,
    "1080P+": 116,
    "1080P": 80,
    "720P60": 74,
    "720P": 64,
    "480P": 32,
    "360P": 16,
    "最低": 6
}

# 清晰度代码到描述的映射
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

# 非大会员最高分辨率
NON_MEMBER_MAX_QUALITY = 80

# 全局中断标志
interrupted = False
overwrite_all = False
skip_existing = False

def signal_handler(sig, frame):
    """处理中断信号"""
    global interrupted
    interrupted = True
    logger.warning("检测到中断，正在退出...")
    print("\n程序被中断，正在清理资源...")

signal.signal(signal.SIGINT, signal_handler)

def sanitize_filename(filename: str) -> str:
    """清理文件名中的非法字符，但保留emoji"""
    return re.sub(r'[<>:"/\\|?*]', '', filename)

def shorten_filename(filename: str, max_length: int = 180) -> str:
    """缩短文件名以防止路径过长"""
    if len(filename) <= max_length:
        return filename
    
    # 保留扩展名
    name, ext = os.path.splitext(filename)
    # 截断文件名主体
    name = name[:max_length - len(ext) - 10]  # 保留10个字符给随机后缀
    # 添加随机后缀防止冲突
    suffix = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz1234567890', k=8))
    return f"{name}_{suffix}{ext}"

class BiliFavDownloader:
    def __init__(self):
        self.cookies = {}
        self.token_data = {}
        self.all_data = []
        self.db_exists = Path(DB_FILE).exists()
        self.is_member = False
        self.qr_file = None  # 默认为None，不保存文件
        self.ffmpeg_available = False
        self.ffmpeg_version = "未知"
        self.ffmpeg_path = None
        self.merge_queue = []
        self.merge_lock = threading.Lock()
        self.merge_thread = None
        self.merge_running = True
        self.last_updated = None
        self.current_update_time = None
        self.first_run = not self.db_exists  # 标记是否是首次运行
    
    async def initialize(self):
        """初始化下载器"""
        global interrupted
        
        self.check_ffmpeg()
        
        # 获取token或二维码登录
        self.token_data = await self.check_token()
        if not self.token_data:
            print("未检测到登录信息，需要登录...")
            self.token_data = await self.qr_login()
            if interrupted:  # 检查是否在登录过程中被中断
                print("登录过程被中断")
                return False
            if self.token_data:
                self.save_token(self.token_data)
            else:
                print("登录失败，无法继续")
                return False
        
        # 创建带Cookie的会话
        if self.token_data:
            self.cookies = self.token_data["cookies"]
        
        # 检查会员状态（只有在有cookies的情况下）
        if self.cookies:
            try:
                # 添加超时和中断检查
                if interrupted: 
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
        
        # 启动合并线程
        self.start_merge_thread()
        
        # 获取数据库最后更新时间
        self.get_last_updated_time()
        
        return True
    
    def get_last_updated_time(self):
        """获取数据库最后更新时间"""
        if not self.db_exists:
            self.last_updated = None
            return
        
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            
            c.execute("PRAGMA table_info(favorites)")
            columns = [col[1] for col in c.fetchall()]
            if "last_updated" not in columns:
                self.last_updated = None
                return
            
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
        """检查系统上的FFmpeg是否可用"""
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"], 
                capture_output=True, 
                text=True,
                encoding='utf-8',
                errors='ignore',
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.returncode == 0:
                version_line = result.stdout.split('\n')[0]
                parts = version_line.split(' ')
                version = parts[2] if len(parts) > 2 else "未知"
                self.ffmpeg_version = version
                self.ffmpeg_available = True
                self.ffmpeg_path = shutil.which("ffmpeg")
                print(f"FFmpeg检测成功 (版本: {self.ffmpeg_version}, 路径: {self.ffmpeg_path})")
                return
        
        except Exception as e:
            print(f"FFmpeg检测异常: {str(e)}")
        
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            self.ffmpeg_path = ffmpeg_path
            self.ffmpeg_available = True
            print(f"FFmpeg检测成功 (路径: {ffmpeg_path})")
        else:
            print("警告: 未检测到FFmpeg，DASH格式视频将无法合并音频")
            print("   请安装FFmpeg并添加到系统PATH：https://ffmpeg.org/download.html")
            self.ffmpeg_available = False
    
    def start_merge_thread(self):
        """启动合并线程"""
        if not self.ffmpeg_available:
            print("合并线程未启动，因为FFmpeg不可用")
            return
        
        self.merge_running = True
        self.merge_thread = threading.Thread(target=self._merge_worker, daemon=True)
        self.merge_thread.start()
        print("后台合并线程已启动")
    
    def stop_merge_thread(self):
        """停止合并线程"""
        if self.merge_thread and self.merge_thread.is_alive():
            self.merge_running = False
            self.merge_thread.join(timeout=5.0)
            print("后台合并线程已停止")
    
    def _merge_worker(self):
        """合并工作线程"""
        print(f"\n合并线程启动 (FFmpeg路径: {self.ffmpeg_path})")
        
        while self.merge_running or self.merge_queue:
            if interrupted:
                break
                
            if not self.merge_queue:
                time.sleep(0.5)
                continue
            
            with self.merge_lock:
                task = self.merge_queue.pop(0) if self.merge_queue else None
            
            if not task:
                continue
                
            video_file, audio_file, output_file, title, bvid = task
            
            try:
                print(f"\n开始合并: {title} ({bvid}) [使用FFmpeg]")
                
                ffmpeg_cmd = [
                    self.ffmpeg_path,
                    '-i', video_file,
                    '-i', audio_file,
                    '-c', 'copy',
                    '-map', '0:v:0',
                    '-map', '1:a:0',
                    '-y',
                    output_file
                ]
                
                process = subprocess.run(
                    ffmpeg_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    encoding='utf-8',
                    errors='ignore',
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                
                if process.returncode != 0:
                    error_msg = process.stderr if process.stderr else "无错误信息"
                    raise Exception(f"FFmpeg合并失败 (返回码 {process.returncode}): {error_msg}")
                
                if os.path.exists(video_file):
                    os.remove(video_file)
                if os.path.exists(audio_file):
                    os.remove(audio_file)
                
                print(f"合并完成: {title} ({bvid})\n")
                
            except Exception as e:
                print(f"合并视频失败: {title} ({bvid}) - {str(e)}")
                if os.path.exists(video_file):
                    try:
                        os.rename(video_file, output_file)
                        print(f"已保存视频文件（无音频）: {title}")
                    except Exception:
                        pass
    
    def queue_merge_task(self, video_file: str, audio_file: str, output_file: str, title: str, bvid: str):
        """将合并任务添加到队列"""
        if not self.ffmpeg_available:
            print(f"无法合并: {title} ({bvid}) - FFmpeg不可用")
            return False
        
        with self.merge_lock:
            self.merge_queue.append((video_file, audio_file, output_file, title, bvid))
        
        # 修复：合并队列消息换行显示
        print(f"\n已加入合并队列: {title} (队列长度: {len(self.merge_queue)})")
        return True
    
    def save_token(self, token_data: Dict):
        """保存token到文件"""
        try:
            with open(TOKEN_FILE, "w") as f:
                toml.dump(token_data, f)
            print(f"登录信息已保存\n")
        except Exception as e:
            print(f"保存登录信息失败: {str(e)}")
    
    async def check_member_status(self) -> bool:
        """检查用户大会员状态"""
        try:
            async with httpx.AsyncClient(headers=HEADERS, cookies=self.cookies, timeout=10.0) as client:
                resp = await client.get("https://api.bilibili.com/x/web-interface/nav")
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") == 0:
                    return data["data"].get("vipStatus", 0) == 1
        except Exception as e:
            print(f"检查会员状态失败: {str(e)}")
        return False

    def get_token(self) -> Dict:
        return self.token_data
    
    async def check_token(self) -> Optional[Dict]:
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

    async def qr_login(self, qr_output: str = None) -> Dict:
        """二维码登录，默认不保存文件"""
        print("请打开哔哩哔哩APP扫描二维码登录...")
        
        # 如果指定了输出文件，则保存二维码
        if qr_output:
            self.qr_file = qr_output
            print(f"二维码将保存到: {qr_output}")
        else:
            self.qr_file = None
        
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=30.0) as client:
                qr_resp = await client.get("https://passport.bilibili.com/x/passport-login/web/qrcode/generate")
                qr_resp.raise_for_status()
                qr_data = qr_resp.json()
                
                if qr_data.get("code") != 0:
                    print(f"获取二维码失败: {qr_data.get('message')}")
                    return None
                
                qr_url = qr_data["data"]["url"]
                qrcode_key = qr_data["data"]["qrcode_key"]
                
                # 创建高分辨率二维码 (600×600)
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_L,
                    box_size=15,  # 增大box_size以提高分辨率
                    border=2,
                )
                qr.add_data(qr_url)
                qr.make(fit=True)
                
                # 在终端打印二维码
                print("\n终端二维码预览:")
                qr.print_ascii(invert=True)  # 使用ASCII字符打印二维码
                
                # 如果需要保存文件
                if self.qr_file:
                    img = qr.make_image(fill_color="black", back_color="white")
                    # 调整图像大小为600×600
                    img = img.resize((600, 600))
                    img.save(self.qr_file)
                    print(f"\n二维码已保存为: {self.qr_file}")
                
                print("\n请使用哔哩哔哩APP扫码登录（二维码有效期为180秒）")
                print("按Ctrl+C可取消登录")
                
                # 使用更细粒度的循环以便更快响应中断
                for i in range(180):  # 180秒，每秒检查一次
                    # 每次循环开始检查中断
                    if interrupted:
                        print("\n登录过程被中断")
                        return None
                    
                    # 每秒打印一次进度
                    print(f"\r等待扫码确认... [{i}/180秒]", end="", flush=True)
                    
                    try:
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
                    
                    if check_data.get("data", {}).get("code") == 86038:
                        print("\n二维码已过期，请重新运行程序获取新二维码")
                        return None
                    elif check_data.get("data", {}).get("code") == 86039:
                        # 等待1秒后继续
                        await asyncio.sleep(1)
                        continue
                    elif check_data.get("data", {}).get("code") == 0:
                        cookies = self.parse_cookies(str(check_resp.headers.get("set-cookie", "")))
                        if not cookies:
                            print("\n获取登录Cookie失败")
                            return None
                        
                        token_info = {
                            "cookies": cookies,
                            "timestamp": int(time.time())
                        }
                        print("\n登录成功！")
                        return token_info
                    
                    # 等待1秒
                    await asyncio.sleep(1)
                
                print("\n登录超时，请重试")
                return None
        except Exception as e:
            print(f"\n登录出错: {str(e)}")
            return None
    
    def parse_cookies(self, cookie_header: str) -> Dict:
        cookies = {}
        if not cookie_header:
            return cookies
        
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
        try:
            print("正在获取收藏夹列表...")
            resp = await session.get(
                "https://api.bilibili.com/x/v3/fav/folder/created/list-all",
                params={"up_mid": session.cookies.get("DedeUserID")},
                timeout=30.0
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                print(f"获取收藏夹列表失败: {data.get('message')}")
                return []
            return data["data"]["list"]
        except Exception as e:
            print(f"获取收藏夹列表失败: {str(e)}")
            return []
    
    async def get_favorite_detail(self, session: httpx.AsyncClient, media_id: int, media_count: int) -> List[Dict]:
        global interrupted
        all_items = []
        page = 1
        page_size = 20
        
        try:
            print(f"开始获取收藏夹内容，共约{media_count}项...")
            
            # 使用tqdm进度条实现动态刷新
            pbar = tqdm(total=media_count, desc=f"收藏夹ID {media_id}", unit="项")
            count = 0
            
            while not interrupted:
                # 随机延迟防止请求过快
                delay = random.uniform(0.1, 0.8)
                await asyncio.sleep(delay)
                
                try:
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
                        if page == 1:
                            print(f"获取收藏夹详情失败: {data.get('message')}")
                        page += 1
                        if page > 50:
                            break
                        continue
                    
                    items = data["data"].get("medias", [])
                    all_items.extend(items)
                    count = len(all_items)
                    
                    # 更新进度条
                    pbar.update(len(items))
                    
                    has_more = data["data"].get("has_more", 0) == 1
                    if not has_more or len(items) < page_size:
                        break
                        
                    page += 1
                    if page > 50:
                        break
                except Exception as e:
                    print(f"获取收藏夹详情失败: {str(e)}")
                    page += 1
                    if page > 50:
                        break
            
            pbar.close()
            print(f"获取完成: {count}/{media_count} 项")
            return all_items
        except Exception as e:
            print(f"\n获取收藏夹详情失败: {str(e)}")
            return all_items

    def upgrade_database(self):
        """升级数据库结构"""
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
                c.execute("ALTER TABLE favorites ADD COLUMN last_updated TEXT")
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
        """保存数据到数据库"""
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
                
                for item in folder.get("items", []):
                    total_items += 1
                    owner = item.get("upper", {}).get("name", "未知作者") if "upper" in item else "未知作者"
                    bvid = item.get("bvid", "")
                    
                    # 使用BVID作为唯一标识符
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
        for folder in data:
            print(f"\n📁 {folder['title']} ({folder['media_count']}项)")
            
            items = folder.get("items", [])
            for i, item in enumerate(items[:20]):
                prefix = "  ├─" if i < len(items)-1 else "  └─"
                bvid = item.get("bvid", "未知BV号")
                owner = item.get("upper", {}).get("name", "未知作者") if "upper" in item else "未知作者"
                print(f"{prefix} {item['title']} {bvid} by {owner}")
            
            if len(items) > 20:
                print(f"  └─ ...还有{len(items)-20}项未显示")
            elif folder['media_count'] > len(items):
                print(f"  └─ 获取不完整: 应有{folder['media_count']}项，实际获取{len(items)}项")

    def get_favorite_videos(self, favorite_id: int) -> Tuple[str, List[Tuple[str, str]]]:
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            
            c.execute("SELECT title FROM favorites WHERE id=?", (favorite_id,))
            row = c.fetchone()
            folder_title = row[0] if row else f"收藏夹_{favorite_id}"
            
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
            return data["data"]
        except Exception as e:
            print(f"获取视频信息失败: {str(e)}")
            return None

    async def get_video_url(self, session: httpx.AsyncClient, bvid: str, cid: int, quality: int = 80) -> Optional[Dict]:
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
            params = {
                "bvid": bvid,
                "cid": cid,
                "qn": quality,
                "fnval": 4048 if use_dash else 0,  # 使用DASH格式
                "fourk": 1,
                "platform": "pc"
            }
            
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
                
                return {
                    "video_url": data["data"]["durl"][0]["url"],
                    "audio_url": None,  # 非DASH格式包含音频
                    "format": "flv"
                }
            
            dash_data = data["data"].get("dash")
            if dash_data and use_dash:
                # 获取视频流
                video_streams = dash_data.get("video", [])
                selected_video = None
                for stream in video_streams:
                    if stream.get("id") == quality:
                        selected_video = stream
                        break
                if not selected_video and video_streams:
                    # 如果没有匹配的quality，选择最高质量的视频流
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
        """异步下载文件"""
        try:
            # 音频下载换行显示
            if file_type == "音频":
                print(f"\n开始下载{file_type}: {title}")
            else:
                print(f"\n开始下载{file_type}: {title}")
    
            async with httpx.AsyncClient(headers=headers, timeout=60.0) as client:
                async with client.stream("GET", url, follow_redirects=True) as response:
                    response.raise_for_status()
                    total_size = int(response.headers.get("Content-Length", 0))
            
                    # 确保文件大小有效
                    if total_size <= 0:
                        # 尝试从内容中获取文件大小
                        if "Content-Range" in response.headers:
                            try:
                                total_size = int(response.headers["Content-Range"].split("/")[-1])
                            except:
                                # 如果无法确定文件大小，使用默认值
                                total_size = 1024 * 1024  # 1MB
                        else:
                            # 如果无法确定文件大小，使用默认值
                            total_size = 1024 * 1024  # 1MB
            
                    # 使用tqdm标准进度条
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
                        # 确保进度条已初始化
                        pbar.update(0)
                    
                        # 下载文件
                        downloaded_size = 0
                        with open(file_path, "wb") as f:
                            async for chunk in response.aiter_bytes(chunk_size=8192):
                                if interrupted:
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
                        # 显式关闭进度条
                        pbar.close()
            
        except Exception as e:
            print(f"下载{file_type}失败: {title} - {str(e)}")
            # 删除可能不完整的文件
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
            return False

    async def download_single_video(self, session: httpx.AsyncClient, bvid: str, title: str, output_path: str, quality: int, overwrite: bool = False) -> bool:
        global interrupted
        
        try:
            safe_title = sanitize_filename(title)
            # 缩短文件名防止路径过长
            safe_title = shorten_filename(safe_title)
            file_path = os.path.join(output_path, f"{safe_title}_{bvid}.mp4")
            
            if overwrite and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    print(f"已删除旧文件: {title} ({bvid})")
                except Exception as e:
                    print(f"删除旧文件失败: {title} ({bvid}) - {str(e)}")
                    return False
            
            video_info = await self.get_video_info(session, bvid)
            if not video_info:
                print(f"跳过视频: {title} ({bvid}) - 无法获取视频信息")
                return False
            
            cid = video_info["cid"]
            media_info = await self.get_video_url(session, bvid, cid, quality)
            if not media_info:
                print(f"跳过视频: {title} ({bvid}) - 无法获取下载链接")
                return False
            
            os.makedirs(output_path, exist_ok=True)
            
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
            
            # 如果音频下载失败，但视频下载成功，尝试只保存视频
            if not audio_success:
                if os.path.exists(video_file):
                    try:
                        os.rename(video_file, file_path)
                        print(f"音频下载失败，已保存视频文件: {title}")
                        return True
                    except Exception as e:
                        print(f"重命名视频文件失败: {title} - {str(e)}")
                        return False
                return False
            
            # 对于DASH格式且有音频文件，加入合并队列
            if audio_file and os.path.exists(audio_file):
                # 加入合并队列（后台线程会处理）
                self.queue_merge_task(video_file, audio_file, file_path, title, bvid)
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
                return False
        except Exception as e:
            print(f"下载失败: {title} ({bvid}) - {str(e)}")
            return False

    async def download_favorite_videos(self, session: httpx.AsyncClient, favorite_id: int, output_dir: str, quality: str):
        global interrupted, overwrite_all, skip_existing
    
        folder_title, videos = self.get_favorite_videos(favorite_id)
        if not videos:
            print("该收藏夹中没有视频")
            return
    
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
    
        quality_code = QUALITY_MAP.get(quality, 80)
    
        overwrite_all = False
        skip_existing = False
    
        download_tasks = []
        skipped_count = 0
        overwritten_count = 0
        new_videos = 0
    
        # 先处理所有文件存在性检查
        for title, bvid in videos:
            if interrupted:
                break
            
            safe_title = sanitize_filename(title)
            safe_title = shorten_filename(safe_title)
            file_path = os.path.join(output_path, f"{safe_title}_{bvid}.mp4")
            file_exists = os.path.exists(file_path)
        
            if file_exists and skip_existing:
                skipped_count += 1
                continue
            
            if file_exists and overwrite_all:
                download_tasks.append((bvid, title, True))
                overwritten_count += 1
                continue
            
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
    
        # 现在开始下载
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
    
        success_count = sum(1 for r in results if r)
        failed_count = len(results) - success_count
    
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
        global interrupted
        
        self.upgrade_database()
        
        # 检查数据库最后更新时间
        default_choice = "n"
        update_reason = ""
        
        # 首次运行强制更新
        if self.first_run:
            default_choice = "y"
            update_reason = " (首次运行需要同步收藏夹)"
            print(f"\n首次运行，需要同步收藏夹...")
        
        # 或者数据库超过24小时未更新
        elif self.last_updated:
            time_diff = datetime.now() - self.last_updated
            if time_diff > timedelta(hours=24):
                default_choice = "y"
                update_reason = f" (数据库已超过24小时未更新，最后更新于 {self.last_updated.strftime('%Y-%m-%d %H:%M')})"
        
        if self.db_exists and not self.first_run:
            print("\n检测到本地数据库存在")
            
            update = input(f"是否更新收藏夹数据? (y/n, 默认{default_choice}{update_reason}): ").strip().lower() or default_choice
            
            if update == "y":
                print("从B站API获取最新收藏夹数据...")
            else:
                print("使用本地数据库数据")
                return self.load_from_db()
        else:
            print("从B站API获取收藏夹数据...")
        
        favorites = await self.get_favorites(session)
        if not favorites:
            return False
        
        self.all_data = []
        for fav in favorites:
            if interrupted:
                break
                
            # 随机延迟防止请求过快
            delay = random.uniform(0.1, 0.8)
            await asyncio.sleep(delay)
            
            print(f"\n正在获取收藏夹: {fav['title']} (ID: {fav['id']}, 应有 {fav['media_count']} 项)")
            
            try:
                items = await self.get_favorite_detail(session, fav["id"], fav["media_count"])
                self.all_data.append({
                    "id": fav["id"],
                    "title": fav["title"],
                    "media_count": fav["media_count"],
                    "items": items
                })
            except Exception as e:
                print(f"  └─ 获取失败: {str(e)}")
        
        if not interrupted and self.all_data:
            success = await self.save_to_db(self.all_data)
            # 重置首次运行标志
            self.first_run = False
            return success
        else:
            return False

    def load_from_db(self) -> bool:
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            
            c.execute("SELECT id, title, media_id, count, last_updated FROM favorites")
            folders = c.fetchall()
            
            self.all_data = []
            for folder in folders:
                c.execute("SELECT title, bvid, owner_name FROM favorite_items WHERE favorite_id=?", (folder[0],))
                items_rows = c.fetchall()
                items = [
                    {
                        "title": row[0],
                        "bvid": row[1],
                        "upper": {"name": row[2]}
                    }
                    for row in items_rows
                ]
                
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
        global interrupted
        
        print("="*50)
        print("B站收藏夹视频下载器")
        print("="*50)
        print("正在初始化...")
        
        # 初始化并检查是否成功
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
        
        # 添加中断检查
        if interrupted:
            print("初始化后检测到中断，退出程序")
            return
            
        async with httpx.AsyncClient(
            headers=HEADERS,
            cookies=self.cookies,
            timeout=60.0
        ) as session:
            # 添加中断检查
            if interrupted:
                print("初始化后检测到中断，退出程序")
                return
                
            success = await self.fetch_and_update_favorites(session)
            
            # 添加中断检查
            if interrupted:
                print("获取收藏夹后检测到中断，退出程序")
                return
                
            if success and self.all_data:
                print("\n收藏夹内容:")
                self.print_tree(self.all_data)
                
                while not interrupted:
                    print("\n请选择操作: 1. 下载收藏夹视频  2. 退出")
                    print("请输入选项 (默认1): ", end="")
                    
                    choice = input().strip()
                    if not choice:
                        choice = "1"
                    
                    if choice == "1":
                        print("\n收藏夹列表:")
                        for folder in self.all_data:
                            print(f"ID: {folder['id']} - {folder['title']} ({folder['media_count']}项)")
                        
                        print("\n请输入要下载的收藏夹ID: ", end="")
                        fav_id = input().strip()
                        if not fav_id.isdigit():
                            print("输入错误，请重新输入")
                            continue
                        fav_id = int(fav_id)
                        
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
                        
                        # 显示带编号的清晰度选项
                        print("\n可用清晰度:")
                        for i, q in enumerate(quality_options, 1):
                            print(f"{i}. {q}")
                        
                        # 获取用户选择
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
                        
                        print("请输入下载路径 (默认./favourite_download): ", end="")
                        output_dir = input().strip() or "./favourite_download"
                        
                        # 添加中断检查
                        if interrupted:
                            print("开始下载前检测到中断，退出程序")
                            break
                        
                        await self.download_favorite_videos(session, fav_id, output_dir, quality)
                    elif choice == "2":
                        print("退出程序")
                        break
                    else:
                        print("无效选项，请重新输入")
            else:
                print("未能获取收藏夹数据")
    
        self.stop_merge_thread()

if __name__ == "__main__":
    downloader = None
    try:
        downloader = BiliFavDownloader()
        asyncio.run(downloader.run())
    except Exception as e:
        print(f"程序发生错误: {str(e)}")
    finally:
        if downloader and hasattr(downloader, 'stop_merge_thread'):
            downloader.stop_merge_thread()
