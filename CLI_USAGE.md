# BiliFAV 命令行使用指南

## 概述

BiliFAV现在支持完整的非交互式命令行操作，提供了三种主要模式：
1. **收藏夹下载模式** - 下载指定收藏夹的所有视频
2. **直接下载模式** - 下载单个视频
3. **批处理模式** - 从JSON文件批量下载

## 快速参考

### 全局参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `--help` | 显示帮助信息 | `biliFAV.py --help` |
| `--version` | 显示版本信息 | `biliFAV.py --version` |
| `--config` | 指定配置文件 | `biliFAV.py --config config.toml` |
| `--verbose` | 启用详细日志 | `biliFAV.py --verbose` |

### 收藏夹下载模式

```bash
biliFAV.py favorite --favorite-id <ID> [选项]
```

**必需参数：**
- `--favorite-id` - 收藏夹ID

**可选参数：**
- `--quality` - 清晰度 (默认: 1080P)
- `--output-dir` - 下载目录 (默认: ./favourite_download)
- `--force-update` - 强制更新收藏夹数据
- `--overwrite` - 文件覆盖策略: skip/overwrite/all (默认: skip)

**示例：**
```bash
# 下载默认收藏夹，1080P清晰度
biliFAV.py favorite --favorite-id 1735679389

# 下载指定收藏夹，720P清晰度，自定义目录
biliFAV.py favorite --favorite-id 1735679389 --quality 720P --output-dir ./my_videos

# 强制更新数据并覆盖所有文件
biliFAV.py favorite --favorite-id 1735679389 --force-update --overwrite all
```

### 直接下载模式

```bash
biliFAV.py direct <视频标识> [选项]
```

**必需参数：**
- `video_identifier` - 视频标识 (BV号、链接)

**可选参数：**
- `--quality` - 清晰度 (默认: 1080P)
- `--output-dir` - 下载目录 (默认: ./direct_download)
- `--overwrite` - 文件覆盖策略: skip/overwrite/all (默认: skip)

**支持的视频标识格式：**
- BV号: `BV1zsnBzGEzC`
- 完整链接: `https://www.bilibili.com/video/BV1zsnBzGEzC/`
- 短链接: `b23.tv/xxxxxx`

**示例：**
```bash
# 使用BV号下载
biliFAV.py direct BV1zsnBzGEzC --quality 720P

# 使用链接下载
biliFAV.py direct "https://www.bilibili.com/video/BV1zsnBzGEzC/" --output-dir ./videos

# 下载并覆盖已存在文件
biliFAV.py direct BV1zsnBzGEzC --overwrite all
```

### 批处理模式

```bash
biliFAV.py batch --file <任务文件> [选项]
```

**必需参数：**
- `--file` - 任务文件路径 (JSON格式)

**可选参数：**
- `--output-dir` - 下载目录 (默认: ./batch_download)
- `--overwrite` - 文件覆盖策略: skip/overwrite/all (默认: skip)

**任务文件格式：**
```json
[
  {
    "type": "favorite",
    "favorite_id": 1735679389,
    "quality": "1080P",
    "output_dir": "./downloads/favorite1",
    "force_update": false,
    "overwrite": "skip"
  },
  {
    "type": "direct",
    "video_identifier": "BV1zsnBzGEzC",
    "quality": "720P",
    "output_dir": "./downloads/video1",
    "overwrite": "skip"
  }
]
```

**示例：**
```bash
# 执行批处理任务
biliFAV.py batch --file tasks.json

# 指定输出目录
biliFAV.py batch --file tasks.json --output-dir ./batch_results
```

## 配置文件

### 配置文件位置

BiliFAV按以下顺序查找配置文件：
1. 命令行指定的路径: `--config <路径>`
2. 当前目录: `config.toml`
3. 用户配置目录: `~/.config/bilifav/config.toml`
4. 用户主目录: `~/.bilifav.toml`

### 配置优先级

配置按以下优先级应用（从低到高）：
1. 默认值
2. 配置文件
3. 环境变量
4. 命令行参数

### 配置选项

完整配置选项请参考 `config.toml.example` 文件。

## 环境变量

支持以下环境变量：

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `BILIFAV_DOWNLOAD_PATH` | 默认下载路径 | `./downloads` |
| `BILIFAV_MAX_RETRIES` | 最大重试次数 | `3` |
| `BILIFAV_TIMEOUT` | 请求超时时间(秒) | `30` |
| `BILIFAV_CONCURRENT` | 并发下载数量 | `3` |
| `BILIFAV_VERBOSE` | 详细日志 | `false` |

## 使用示例

### 示例1：自动化下载收藏夹

```bash
# 创建配置文件
cat > config.toml << EOF
[general]
default_download_path = "/data/videos"
verbose = true

[quality]
default_quality = "1080P"

[file_handling]
default_overwrite_policy = "skip"
EOF

# 下载收藏夹
biliFAV.py --config config.toml favorite --favorite-id 1735679389
```

### 示例2：批量下载任务

```bash
# 创建任务文件
cat > tasks.json << EOF
[
  {
    "type": "favorite",
    "favorite_id": 1735679389,
    "quality": "1080P",
    "output_dir": "/videos/favorites",
    "force_update": true,
    "overwrite": "skip"
  },
  {
    "type": "direct",
    "video_identifier": "BV1zsnBzGEzC",
    "quality": "720P",
    "output_dir": "/videos/singles",
    "overwrite": "skip"
  }
]
EOF

# 执行批处理
biliFAV.py batch --file tasks.json --output-dir /videos/batch
```

### 示例3：结合cron定时任务

```bash
# 编辑crontab
crontab -e

# 添加定时任务（每天凌晨2点下载收藏夹）
0 2 * * * cd /path/to/bilifav && uv run python biliFAV.py favorite --favorite-id 1735679389 --quality 1080P --output-dir /data/videos >> /var/log/bilifav.log 2>&1
```

## 故障排除

### 常见问题

1. **配置文件未生效**
   - 检查配置文件路径是否正确
   - 使用 `--verbose` 查看配置加载日志

2. **收藏夹ID不存在**
   - 运行交互模式查看可用收藏夹ID
   - 使用 `--force-update` 更新收藏夹数据

3. **视频下载失败**
   - 检查网络连接
   - 确保FFmpeg已正确安装
   - 使用 `--verbose` 查看详细错误信息

### 调试技巧

```bash
# 启用详细日志
biliFAV.py --verbose favorite --favorite-id 1735679389

# 查看配置加载
biliFAV.py --config config.toml --verbose favorite --favorite-id 1735679389

# 测试参数解析
biliFAV.py favorite --help
```

## 高级用法

### 脚本集成

```python
#!/usr/bin/env python3
import subprocess
import json

def download_favorite(favorite_id, quality="1080P", output_dir="./downloads"):
    """使用Python脚本调用BiliFAV"""
    cmd = [
        "python", "biliFAV.py",
        "favorite",
        "--favorite-id", str(favorite_id),
        "--quality", quality,
        "--output-dir", output_dir,
        "--overwrite", "skip"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0

# 使用示例
if __name__ == "__main__":
    download_favorite(1735679389, "720P", "./my_videos")
```

### 与其他工具集成

```bash
# 使用jq处理JSON输出（如果支持）
biliFAV.py --json-output favorite --favorite-id 1735679389 | jq '.videos[] | .title'

# 结合find清理旧文件
find ./downloads -name "*.tmp" -type f -delete
```

## 注意事项

1. **账号安全**
   - 登录token存储在 `bili_token.toml`，请妥善保管
   - 不要在公共计算机上保存token文件

2. **网络使用**
   - 合理控制下载频率，避免对B站服务器造成压力
   - 建议在非高峰时段进行批量下载

3. **存储管理**
   - 定期清理临时文件 (`*.tmp`)
   - 监控磁盘空间使用情况

4. **法律合规**
   - 仅下载个人收藏的视频
   - 遵守B站用户协议
   - 尊重视频创作者版权