#!/usr/bin/env python3
import subprocess, sys

# 搜索旧的 flat imports：backlink_publisher.errors, adapters, content_fetch
pattern = r"from backlink_publisher\.(errors|adapters|content_fetch)"
result = subprocess.run(['grep', '-r', '-n', '--include=*.py', '-E', pattern, 'src/'], capture_output=True, text=True)
if result.returncode == 0:
    print("发现旧的 flat imports：")
    print(result.stdout)
    sys.exit(1)
else:
    print("未发现违规导入。")
    sys.exit(0)
