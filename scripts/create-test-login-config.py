#!/usr/bin/env python3
"""Generate a private enabled test-login configuration; never print its secret."""
import argparse
import json
import os
from pathlib import Path
import secrets

parser = argparse.ArgumentParser()
parser.add_argument('output', help='private destination outside web assets / Git')
args = parser.parse_args()
target = Path(args.output)
target.parent.mkdir(parents=True, exist_ok=True)
try:
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    parser.exit(1, '配置已存在，未覆盖密钥。\n')
with os.fdopen(descriptor, 'w') as output:
    json.dump({'enabled': True, 'secret': secrets.token_urlsafe(32)}, output, indent=2)
    output.write('\n')
print(f'已生成开启的测试登录配置（0600）：{target}；密钥未输出。')
