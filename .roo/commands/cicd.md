---
description: "处理git事务，推送到仓库，并询问用户是否编译"
---
git status
git diff 查看更改
git add 暂存变更文件
询问用户是否更新 ./pyproject.toml中的版本号
git commit 提交变更，忽略测试代码
git pull 拉取远程变更
git pull 提交到远程仓库
询问用户是否运行 ./auto_complainer.py
根据编译后的新版本号添加tag