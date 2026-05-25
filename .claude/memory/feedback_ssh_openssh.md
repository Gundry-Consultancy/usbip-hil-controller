---
name: feedback-ssh-openssh
description: Always use Windows OpenSSH (not Git Bash ssh) when SSHing to Tachyon from the Bash tool
metadata:
  type: feedback
---

Use `/c/Windows/System32/OpenSSH/ssh.exe` (Windows OpenSSH) when running SSH commands via the Bash tool. The Bash tool uses Git Bash (`/usr/bin/ssh`) by default, which does not have the user's keys configured.

**Why:** `/usr/bin/ssh` (Git Bash) fails with "Permission denied (publickey,password)" to Tachyon (192.168.1.169). Windows OpenSSH at `/c/Windows/System32/OpenSSH/ssh.exe` has the correct keys and succeeds.

**How to apply:** Any time an SSH or SCP command is needed (deploying to Tachyon, running remote commands), prefix with `/c/Windows/System32/OpenSSH/ssh.exe` or `/c/Windows/System32/OpenSSH/scp.exe` instead of bare `ssh`/`scp`.
