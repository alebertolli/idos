---
description: Stage all changes and create a git commit with the given message
---

Stage all changes in the repo root (C:\REPOS\idos), then run:
```powershell
& "C:\Program Files\Git\bin\git.exe" -C C:\REPOS\idos add -A
& "C:\Program Files\Git\bin\git.exe" -C C:\REPOS\idos commit -m "$ARGUMENTS"
```
Return the commit output to the user.