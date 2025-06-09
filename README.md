# BiliFAV - B站收藏夹视频下载工具

![GitHub release (latest by date)](https://img.shields.io/github/v/release/Qtgcy08/biliFAV?style=flat-square)
![Python Version](https://img.shields.io/badge/python-3.10+-blue?style=flat-square)
![License](https://img.shields.io/badge/license-AGPL--3.0-orange?style=flat-square)

> **免责声明**：本项目仅供学习交流使用，禁止用于商业用途。使用者需自行承担所有法律责任。

BiliFAV是一个功能强大的命令行工具，用于下载Bilibili收藏夹中的视频内容。通过扫码登录B站账号，用户可以轻松下载自己收藏的视频，支持多种清晰度选择和后台合并功能。

## 功能特点

- 🔑 扫码登录B站账号
- 📂 列出用户所有收藏夹
- ⬇️ 下载指定收藏夹的全部视频
- 🎚️ 支持多种清晰度选择（4K、1080P60、1080P+等）
- 🔀 自动合并音视频流（需要FFmpeg）
- 🚀 断点续传和跳过已下载文件
- ⏯️ 支持覆盖或跳过已存在文件
- 💾 数据库缓存收藏夹信息，减少API请求

## 安装方法

### 从Release安装(Windows x64)

1. 前往[Release页面](https://github.com/Qtgcy08/biliFAV/releases/tag/Stable)下载对应平台的预编译版本
2. 解压后运行可执行文件（Windows为`biliFAV_win_x64_版本号.exe`）

### 从源码运行(Windows其他架构,MAC OS,Linux)

确保已安装Python 3.10+

```bash
# 克隆仓库
git clone https://github.com/Qtgcy08/biliFAV.git
cd biliFAV

# 安装依赖
pip install -r requirements.txt

# 运行程序
python main.py
```

## 安装FFmpeg（必需）

BiliFAV需要FFmpeg来合并音视频流（DASH格式）。以下是各平台的安装方法：

### Windows用户

1. 访问 [Gyan.dev FFmpeg Builds](https://www.gyan.dev/ffmpeg/builds/ffmpeg-git-full.7z) 下载完整版FFmpeg
2. 解压下载的压缩包（例如解压到 `C:\ffmpeg`）
3. 将FFmpeg的`bin`目录添加到系统PATH环境变量（例如 `C:\ffmpeg\bin`）
4. 打开命令提示符，运行 `ffmpeg -version` 验证安装

### Mac用户

```bash
# 使用Homebrew安装
brew install ffmpeg
```

### Linux用户

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install ffmpeg

# Fedora
sudo dnf install ffmpeg

# Arch Linux
sudo pacman -S ffmpeg
```

## 使用说明

1. 运行程序后，使用B站APP扫码登录
2. 程序将列出所有收藏夹，并询问是否更新数据（首次运行必须更新）
3. 选择要下载的收藏夹ID
4. 选择清晰度（输入序号，如1代表4K，2代表1080P60等）
5. 指定下载目录（默认为`./favourite_download`）
6. 程序将开始下载，下载过程中可以按Ctrl+C中断

### 注意事项

- 大会员账号可以下载更高清晰度的视频（如4K、1080P60等）
- 非大会员账号最高可下载1080P
- **必须安装FFmpeg**才能合并高清晰度视频（DASH格式）
- 如果未安装FFmpeg，程序只能下载FLV格式（含音频）的视频

## 配置说明

程序运行后会在当前目录生成以下文件：

- `bili_token.toml`: 保存登录token，避免重复扫码
- `.get_my_favourite.sqlite`: SQLite数据库，缓存收藏夹信息

如需重新登录，删除`bili_token.toml`文件即可。

## 技术实现

BiliFAV基于以下技术构建：

- Python 3.10+ 异步编程
- HTTPX 高性能HTTP客户端
- SQLite 轻量级数据库
- FFmpeg 音视频处理
- TOML 配置文件格式

项目结构遵循模块化设计原则，主要模块包括：

- 认证模块：处理扫码登录和token管理
- API模块：封装Bilibili接口调用
- 下载模块：实现多线程下载和进度显示
- 合并模块：后台音视频流合并
- 数据库模块：收藏夹数据缓存

## 法律免责声明

1. 本项目与哔哩哔哩(bilibili)无任何关联
2. 使用的API来自第三方逆向工程，存在法律风险
3. **禁止用于商业用途**，仅限个人学习研究
4. 使用者需自行承担所有法律责任
5. 项目作者不承担因滥用导致的侵权责任

## 参考项目

- [bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect) - 哔哩哔哩API收集整理

## 作者

依轨泠QTY
B站主页: [https://space.bilibili.com/3461567223957589](https://space.bilibili.com/3461567223957589)
GitHub: [https://github.com/Qtgcy08](https://github.com/Qtgcy08)

## 开源许可

本项目采用AGPL-3.0许可证。详情请见LICENSE文件。

**温馨提示**：请合理使用本工具，尊重视频创作者和平台权益。过度下载可能导致账号异常或被限制访问。
