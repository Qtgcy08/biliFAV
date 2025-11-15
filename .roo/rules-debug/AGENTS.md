# Project Debug Rules (Non-Obvious Only)

## 调试关键点
- **中断处理**: 全局`interrupted`标志控制程序退出，Ctrl+C触发
- **合并线程**: 后台合并线程使用`_merge_worker()`，检查`merge_running`标志
- **数据库状态**: 数据库文件`.get_my_favourite.sqlite`缓存收藏夹数据

## 错误排查路径
- **登录失败**: 删除`bili_token.toml`强制重新扫码登录
- **合并失败**: 检查FFmpeg路径和权限，临时文件可能保留
- **下载中断**: 检查网络连接和API限流，B站API有请求频率限制

## 状态监控
- **进度显示**: 使用`tqdm`进度条，下载和获取收藏夹都有进度显示
- **队列状态**: 合并队列长度在`merge_queue`中，后台线程自动处理
- **文件覆盖**: 全局`overwrite_all`和`skip_existing`控制批量操作

## 环境要求
- **FFmpeg必需**: DASH格式视频需要FFmpeg合并音视频
- **编码设置**: 强制UTF-8编码确保中文正常显示
- **网络超时**: HTTP请求超时设置为15-60秒