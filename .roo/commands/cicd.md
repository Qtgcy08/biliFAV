---
description: "处理git事务，推送到仓库，并询问用户是否编译"
---
git status
git diff 查看更改
询问用户是否更新 ./pyproject.toml 中的版本号
询问用户是否运行 ./auto_complainer.py
git add 暂存变更文件，忽略测试代码
添加版本号tag "x.xx.x"
git commit 提交变更
```git commit
提交类型(如fix):变更摘要

- 版本：x.xx.x → x.xx.x
- 变更1的详细描述
- 变更2的详细描述
…

```
git pull 拉取远程变更
git push 提交到远程仓库