# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## 项目概述
BiliFAV是一个B站收藏夹视频下载工具，使用Python异步编程实现。项目使用uv管理Python环境，Nuitka进行打包。

## 关键命令
- **运行程序**: `uv run python biliFAV.py` (主程序) 或 `uv run python main.py` (简单测试)
- **编译打包**: `uv run python auto_complainer.py` - 自动版本递增并生成Windows可执行文件
- **依赖管理**: 使用`uv.toml`配置中国镜像源，依赖在`pyproject.toml`中定义

## 非显而易见的设计约束

### 文件处理
- **文件名清理**: 使用`sanitize_filename()`函数清理非法字符但保留emoji，文件名长度限制180字符
- **数据库文件**: `.get_my_favourite.sqlite`缓存收藏夹数据，避免重复API请求
- **Token文件**: `bili_token.toml`保存登录信息，删除可强制重新登录

### 视频下载逻辑
- **清晰度限制**: 非大会员最高1080P (代码80)，大会员可下载4K (代码120)
- **格式选择**: 360P及以下使用FLV格式，其他使用DASH格式需要FFmpeg合并
- **合并队列**: 后台线程处理音视频合并，使用线程锁保证队列安全
- **多分P支持**: 自动检测多分P视频，用户可选择下载所有分P或指定分P

### 错误处理
- **中断处理**: 全局`interrupted`标志，Ctrl+C可优雅退出
- **文件覆盖**: 全局`overwrite_all`和`skip_existing`标志控制批量操作
- **数据库升级**: 自动检测并升级数据库结构，添加`last_updated`字段

### 编译配置
- **版本管理**: `complainer_count.txt`存储当前版本，`auto_complainer.py`自动递增
- **Nuitka参数**: 使用MSVC编译器，启用LTO优化，设置Windows文件属性
- **编码设置**: 强制UTF-8编码环境，确保中文正常显示

## 关键依赖关系
- **必需**: FFmpeg用于DASH格式音视频合并
- **核心**: aiohttp, httpx用于异步HTTP请求
- **工具**: tqdm显示进度条，qrcode生成登录二维码

## 架构注意事项
- 主类`BiliFavDownloader`包含完整功能，避免修改核心下载逻辑
- 异步操作使用`asyncio`和`httpx.AsyncClient`
- 数据库操作使用SQLite，表结构在`upgrade_database()`中定义