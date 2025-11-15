# Project Coding Rules (Non-Obvious Only)

## 核心类结构
- 主类`BiliFavDownloader`在`biliFAV.py`中，包含完整的下载逻辑
- 异步方法使用`async/await`模式，HTTP请求使用`httpx.AsyncClient`
- 数据库操作集中在`upgrade_database()`和`save_to_db()`方法中

## 关键函数约束
- **文件名处理**: 必须使用`sanitize_filename()`和`shorten_filename()`处理文件名
- **中断检查**: 所有长时间操作必须检查全局`interrupted`标志
- **合并队列**: 使用`queue_merge_task()`添加合并任务，后台线程自动处理
- **多分P处理**: 使用`get_video_pages()`检测多分P视频，`download_single_video()`处理用户选择

## API调用模式
- B站API调用需要包含正确的`User-Agent`和`Referer`头
- 视频URL获取使用`get_video_url()`，支持DASH和FLV格式
- 清晰度映射在`QUALITY_MAP`和`QUALITY_CODE_TO_DESC`中定义
- 多分P信息通过`get_video_info()`的`pages`字段获取

## 错误处理要求
- 文件下载失败必须删除不完整文件
- 数据库操作必须使用try-finally确保连接关闭
- 合并失败时尝试保存视频文件（无音频）
- 多分P选择失败时默认下载所有分P