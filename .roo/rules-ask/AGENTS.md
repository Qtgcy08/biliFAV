# Project Documentation Rules (Non-Obvious Only)

## 项目架构理解
- **主程序**: `biliFAV.py`是完整实现，`main.py`仅用于简单测试
- **编译系统**: `auto_complainer.py`处理版本递增和Nuitka编译
- **依赖管理**: 使用`uv`包管理器，配置中国镜像源加速下载

## 关键功能流程
- **登录流程**: 二维码扫码登录，token保存在`bili_token.toml`
- **数据获取**: 收藏夹数据缓存到SQLite数据库，避免重复API请求
- **下载流程**: 支持多清晰度，DASH格式需要FFmpeg合并音视频

## 技术实现细节
- **异步架构**: 使用`asyncio`和`httpx.AsyncClient`实现高性能下载
- **文件处理**: 文件名清理保留emoji但移除非法字符，长度限制180字符
- **错误恢复**: 中断后可继续下载，数据库记录最后更新时间

## 配置和部署
- **版本管理**: `complainer_count.txt`记录版本号，编译时自动递增
- **打包配置**: Nuitka编译设置Windows文件属性和公司信息
- **环境要求**: Python 3.10+，必需FFmpeg用于音视频合并