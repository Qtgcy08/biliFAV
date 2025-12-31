---
description: "处理git事务，推送到仓库，并询问用户是否编译"
---
1.git status
2.git diff 查看更改
3.git add 暂存变更文件
4.询问用户是否更新 ./pyproject.toml中的版本号
5.git commit 提交变更
6.git pull 提交到远程仓库
7.询问用户是否运行 ./auto_complainer.py