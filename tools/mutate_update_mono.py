#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""变异测试：把三条收敛规则逐一改回旧写法，确认闸门能抓到。"""
import io
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JS = os.path.join(REPO, 'src', 'emule', 'app', 'web', 'js', 'app.js')
GATE = os.path.join(REPO, 'tools', 'check_update_mono.py')
BACKUP = os.path.join(REPO, 'tmp', '_app_js_mono_backup.js')

CASES = [
    ('删 attempt 重置',
     'if (attempt !== this.updateMonoAttempt) {', 'if (false) {'),
    ('删「后退快照丢弃」',
     'if (prevRank !== undefined && nextRank !== undefined && nextRank < prevRank) {',
     'if (false) {'),
    ('total 不累积',
     'progress.total = Math.max(Number(prev.total) || 0, nextTotal);',
     'progress.total = nextTotal;'),
    ('安装阶段不清零 total',
     'progress.total = 0;', 'progress.total = nextTotal;'),
    ('重新用安装响应画进度',
     'if (r && typeof r.rollback === "boolean") this.updateRollbackReady = r.rollback;',
     'if (r && r.task) this.applyUpdateTask(r.task);'),
]

os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
shutil.copyfile(APP_JS, BACKUP)
missed = 0
try:
    for label, old, new in CASES:
        text = io.open(APP_JS, encoding='utf-8').read()
        if old not in text:
            print('SKIP  ', label, '(anchor missing)')
            continue
        io.open(APP_JS, 'w', encoding='utf-8', newline='\n').write(
            text.replace(old, new, 1))
        r = subprocess.run([sys.executable, GATE], capture_output=True,
                           text=True, encoding='utf-8', errors='replace')
        ok = r.returncode != 0
        if not ok:
            missed += 1
        first = ((r.stdout or r.stderr or '').strip().splitlines() or [''])[0]
        print(('CAUGHT' if ok else 'MISSED'), label, '->', first[:64])
        io.open(APP_JS, 'w', encoding='utf-8', newline='\n').write(text)
finally:
    shutil.copyfile(BACKUP, APP_JS)
    os.remove(BACKUP)

print()
print('missed =', missed)
sys.exit(1 if missed else 0)
