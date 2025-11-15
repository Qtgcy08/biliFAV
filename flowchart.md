# BiliFAV 程序流程图

## 完整程序逻辑流程图

```mermaid
flowchart TD
    Start((开始)) --> Init[程序初始化]
    Init --> FFmpegCheck{FFmpeg检测}
    FFmpegCheck -->|成功| LoginCheck{登录状态检查}
    FFmpegCheck -->|失败| FFmpegError[FFmpeg未找到错误]
    
    LoginCheck -->|已登录| MemberCheck{会员状态检测}
    LoginCheck -->|未登录| QRLogin[显示登录二维码]
    QRLogin --> ScanWait{等待扫码}
    ScanWait -->|成功| TokenSave[保存登录Token]
    ScanWait -->|失败| LoginRetry[登录重试]
    
    TokenSave --> MemberCheck
    MemberCheck -->|大会员| HighRes[支持4K高分辨率]
    MemberCheck -->|普通会员| NormalRes[最高1080P]
    
    HighRes --> MainMenu
    NormalRes --> MainMenu
    
    subgraph MainMenu[主菜单]
        MenuChoice{选择操作}
        MenuChoice -->|1| FavDownload[下载收藏夹视频]
        MenuChoice -->|2| DirectDownload[直接下载视频]
        MenuChoice -->|3| Exit[退出程序]
    end
    
    subgraph FavDownloadProcess[收藏夹下载流程]
        FavDownload --> DBExist{数据库存在检查}
        DBExist -->|存在| UpdateAsk{是否更新数据}
        DBExist -->|不存在| FetchData[获取收藏夹数据]
        
        UpdateAsk -->|是| FetchData
        UpdateAsk -->|否| LoadDB[加载本地数据库]
        
        FetchData --> SaveDB[保存到数据库]
        SaveDB --> LoadDB
        LoadDB --> ShowFavs[显示收藏夹列表]
        ShowFavs --> SelectFav{选择收藏夹ID}
        SelectFav --> QualitySelect{选择清晰度}
        QualitySelect --> PathSelect{选择下载路径}
        PathSelect --> StartDownload[开始下载]
    end
    
    subgraph DownloadProcess[下载处理流程]
        StartDownload --> FileExistCheck{文件存在检查}
        FileExistCheck -->|不存在| DownloadNew[下载新文件]
        FileExistCheck -->|存在| OverwriteChoice{覆盖选项}
        
        OverwriteChoice -->|跳过| SkipFile[跳过文件]
        OverwriteChoice -->|覆盖| DownloadOverwrite[覆盖下载]
        OverwriteChoice -->|跳过所有| SkipAll[跳过所有已存在]
        OverwriteChoice -->|覆盖所有| OverwriteAll[覆盖所有已存在]
        
        DownloadNew --> MultiPartCheck{多分P检查}
        MultiPartCheck -->|单分P| DownloadSingle[下载单分P]
        MultiPartCheck -->|多分P| PartSelection{分P选择}
        
        PartSelection -->|所有分P| DownloadAllParts[下载所有分P]
        PartSelection -->|指定分P| DownloadSelected[下载指定分P]
        PartSelection -->|仅新分P| DownloadNewParts[仅下载未存在分P]
        
        DownloadSingle --> MergeCheck{格式检查}
        DownloadAllParts --> MergeCheck
        DownloadSelected --> MergeCheck
        DownloadNewParts --> MergeCheck
        
        MergeCheck -->|DASH格式| BackgroundMerge[后台合并音视频]
        MergeCheck -->|FLV格式| DirectSave[直接保存]
        
        BackgroundMerge --> MergeComplete[合并完成]
        DirectSave --> DownloadComplete[下载完成]
        MergeComplete --> DownloadComplete
    end
    
    DownloadOverwrite --> MultiPartCheck
    SkipFile --> NextVideo[下一个视频]
    SkipAll --> NextVideo
    OverwriteAll --> MultiPartCheck
    
    NextVideo --> MoreVideos{还有更多视频}
    MoreVideos -->|是| FileExistCheck
    MoreVideos -->|否| DownloadSummary[下载统计]
    
    DownloadSummary --> MainMenu
    
    DirectDownload --> InputURL[输入视频URL/BV号]
    InputURL --> DirectQuality{选择清晰度}
    DirectQuality --> DirectPath{选择下载路径}
    DirectPath --> DirectDownloadProcess[直接下载处理]
    DirectDownloadProcess --> MultiPartCheck
    
    Exit --> End((结束))
    
    class Start,End fill:#e6f3ff
    class Error fill:#ffe6e6
    class DownloadProcess fill:#e6ffe6
    class MainMenu fill:#fff2e6
```

## 流程图说明

### 主要模块

1. **初始化模块**
   - FFmpeg检测
   - 登录状态检查
   - 会员权限检测

2. **主菜单模块**
   - 下载收藏夹视频
   - 直接下载视频
   - 退出程序

3. **收藏夹下载模块**
   - 数据库缓存管理
   - 收藏夹列表显示
   - 清晰度选择
   - 下载路径设置

4. **下载处理模块**
   - 文件存在检查
   - 覆盖选项处理
   - 多分P视频处理
   - 音视频合并

### 关键特性

- **智能缓存**：使用SQLite数据库缓存收藏夹数据
- **断点续传**：支持从上次中断处继续下载
- **批量操作**：支持覆盖所有/跳过所有操作
- **多分P处理**：智能检测和处理多分P视频
- **后台合并**：异步处理DASH格式音视频合并

### 错误处理

- FFmpeg未找到错误处理
- 登录失败重试机制
- 网络异常处理
- 文件操作异常处理

## 技术架构

该流程图展示了BiliFAV程序的完整逻辑流程，体现了以下技术特点：

- **模块化设计**：各功能模块独立且可复用
- **异步处理**：后台合并不影响主下载流程
- **用户友好**：提供清晰的交互界面和选项
- **容错性强**：完善的错误处理和恢复机制

流程图使用标准的Mermaid语法，可以在支持Mermaid的Markdown查看器中正确渲染。