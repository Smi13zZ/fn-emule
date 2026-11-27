# -*- coding: utf-8 -*-
# 目录可用性 + 临时目录迁移的单元测试。全部在本地 tmp/_unit 里造目录，不碰 NAS。
import os, sys, shutil
REPO = r'D:\Workspace\DSH\fn-emule'
sys.path.insert(0, os.path.join(REPO, 'src', 'emule', 'app', 'server', 'core'))
import amule_ctl
from amule_ctl import AmuleCtl

BASE = os.path.join(REPO, 'tmp', '_unit', 'dirmig')
FAILS = []


def check(name, cond, detail=''):
    if cond:
        print('  ok   ' + name)
    else:
        print('  FAIL ' + name + ' ' + detail)
        FAILS.append(name)


def fresh():
    if os.path.isdir(BASE):
        shutil.rmtree(BASE, ignore_errors=True)
    os.makedirs(BASE, exist_ok=True)


def make_ctl(engine):
    def provider():
        return {"engine": engine, "bootstrap": {}}
    return AmuleCtl(provider, var_dir=os.path.join(BASE, 'var'))


# ---------------------------------------------------------------- check_dir
print('1) 可写的目录：建出来、能写、权限放开')
fresh()
ctl = make_ctl({})
target = os.path.join(BASE, 'ok', 'deep', 'Temp')
check('空原因表示可用', ctl.check_dir_writable(target) == '', repr(ctl.check_dir_writable(target)))
check('目录已建出来', os.path.isdir(target))
mode = os.stat(target).st_mode & 0o777
check('权限是 777（否则其它账号进不去）', mode == 0o777, oct(mode))

print('2) 空路径 / 相对路径一律拒绝')
check('空串被拒', ctl.check_dir_writable('') != '')
check('相对路径被拒', ctl.check_dir_writable('relative/path') != '')
check('绝对路径通过', ctl.check_dir_writable(os.path.join(BASE, 'abs')) == '')

print('2b) 新建出来的中间层也要放开权限（只修末层没用）')
fresh()
# 模拟 fnOS 数据盘根：父目录带一条清掉其它位的规则，让新建目录继承成 0000。
# 本地没法改 umask 的父 ACL，这里退而验证：中间层被建出来且也被 chmod 过。
deep = os.path.join(BASE, 'mid1', 'mid2', 'mid3', 'Temp')
check('可用', ctl.check_dir_writable(deep) == '', repr(ctl.check_dir_writable(deep)))
for layer in ('mid1', os.path.join('mid1', 'mid2'),
              os.path.join('mid1', 'mid2', 'mid3'),
              os.path.join('mid1', 'mid2', 'mid3', 'Temp')):
    p = os.path.join(BASE, layer)
    mode = os.stat(p).st_mode & 0o777
    check('中间层 ' + layer + ' 权限 777', mode == 0o777, oct(mode))

print('2c) 已经存在的目录不改权限（不碰用户自己的目录）')
fresh()
existing = os.path.join(BASE, 'userdir')
os.makedirs(existing, exist_ok=True)
os.chmod(existing, 0o750)
check('可用', ctl.check_dir_writable(existing) == '')
# 目录权限位只在 POSIX 上真实生效；Windows 的 os.chmod 只认只读位，
# 0o750 和 0o777 读回来是同一个值，所以这两条断言只在 POSIX 上跑。
POSIX = os.name == 'posix'
if POSIX:
    mode = os.stat(existing).st_mode & 0o777
    check('末层被改成 777（它就是要用的目录）', mode == 0o777, oct(mode))
    parent = os.path.join(BASE, 'keepme')
    os.makedirs(parent, exist_ok=True)
    os.chmod(parent, 0o755)
    check('子目录可用', ctl.check_dir_writable(os.path.join(parent, 'sub')) == '')
    check('已有父目录权限没被动过', (os.stat(parent).st_mode & 0o777) == 0o755,
          oct(os.stat(parent).st_mode & 0o777))
else:
    print('  skip 权限位断言（Windows 的 os.chmod 不表达 rwx）')
    parent = os.path.join(BASE, 'keepme')
    os.makedirs(parent, exist_ok=True)
    check('子目录可用（不依赖权限位）',
          ctl.check_dir_writable(os.path.join(parent, 'sub')) == '')

print('3) 父路径是文件时建不出来 → 必须报错，不能静默通过')
fresh()
blocker = os.path.join(BASE, 'blocker')
open(blocker, 'w').write('x')
bad = os.path.join(blocker, 'Temp')
reason = ctl.check_dir_writable(bad)
check('返回了中文原因', bool(reason), repr(reason))
check('原因里提到无法创建', '无法创建' in reason, reason)

print('4) 路径存在但不是目录 → 报错')
check('指向文件被拒', ctl.check_dir_writable(blocker) != '')

# ------------------------------------------------------------- ensure_dirs
print('5) ensure_dirs：用户目录要 chmod，失败要能看见')
fresh()
engine = {"incoming_dir": os.path.join(BASE, 'inc'),
          "temp_dir": os.path.join(BASE, 'tmp'),
          "shared_dirs": [os.path.join(BASE, 'share')]}
ctl = make_ctl(engine)
failures = ctl.ensure_dirs(engine)
check('没有失败项', failures == [], repr(failures))
for key in ('incoming_dir', 'temp_dir'):
    mode = os.stat(engine[key]).st_mode & 0o777
    check(key + ' 权限 777', mode == 0o777, oct(mode))
mode = os.stat(engine['shared_dirs'][0]).st_mode & 0o777
check('共享目录权限 777', mode == 0o777, oct(mode))

fresh()
blocker2 = os.path.join(BASE, 'blocker2')
open(blocker2, 'w').write('x')
bad_engine = {"incoming_dir": os.path.join(BASE, 'inc2'),
              "temp_dir": os.path.join(blocker2, 'Temp'),
              "shared_dirs": []}
failures = ctl.ensure_dirs(bad_engine)
check('坏目录被记进失败清单', len(failures) == 1, repr(failures))
check('失败项带路径', failures and failures[0][0] == bad_engine['temp_dir'], repr(failures))

print('6) ensure_dirs 的返回不影响好目录的创建')
check('好目录照样建出来', os.path.isdir(bad_engine['incoming_dir']))

# ------------------------------------------------------------ migrate_temp
print('7) migrate_temp：只搬 part 文件，别的一概不动')
fresh()
old = os.path.join(BASE, 'old')
new = os.path.join(BASE, 'new')
os.makedirs(old, exist_ok=True)
for name in ('001.part', '001.part.met', '001.part.met.bak', '001.part.met.seeds',
             '002.part', '002.part.met'):
    open(os.path.join(old, name), 'w').write(name)
open(os.path.join(old, 'notes.txt'), 'w').write('keep me')
open(os.path.join(old, 'readme.log'), 'w').write('keep me too')


class FakeCtl(object):
    DIR_MODE = 0o777
    def __init__(self):
        self.pid = 0
    def find_pid(self):
        return self.pid
    def check_dir_writable(self, path):
        return ''
    def _log(self, *a, **k):
        pass


# migrate_temp 在 core.service 里，这里用最小的替身把方法借过来
sys.path.insert(0, os.path.join(REPO, 'src', 'emule', 'app', 'server', 'core'))
import service as servicemod

svc = servicemod.EmuleService(lambda: {"engine": {"temp_dir": old}}, var_dir=os.path.join(BASE, 'var'))
svc._ctl = FakeCtl()
svc._ctl.pid = 0
result = svc.migrate_temp(old, new)
check('搬了 6 个文件', result['count'] == 6, repr(result))
check('新目录里 part 齐全',
      all(os.path.exists(os.path.join(new, n)) for n in
          ('001.part', '001.part.met', '001.part.met.bak', '001.part.met.seeds',
           '002.part', '002.part.met')))
check('非 part 文件留在原地', os.path.exists(os.path.join(old, 'notes.txt')))
check('旧目录里不再有 part', not os.path.exists(os.path.join(old, '001.part')))
check('新目录权限 777', (os.stat(new).st_mode & 0o777) == 0o777,
      oct(os.stat(new).st_mode & 0o777))

print('8) 引擎在跑时拒绝迁移（不然搬走的是半个文件）')
fresh()
old2 = os.path.join(BASE, 'old2')
new2 = os.path.join(BASE, 'new2')
os.makedirs(old2, exist_ok=True)
open(os.path.join(old2, '001.part'), 'w').write('x')
svc2 = servicemod.EmuleService(lambda: {"engine": {"temp_dir": old2}}, var_dir=os.path.join(BASE, 'var2'))
svc2._ctl = FakeCtl()
svc2._ctl.pid = 1234
try:
    svc2.migrate_temp(old2, new2)
    check('应当抛错', False, '没抛')
except servicemod.EmuleError as exc:
    check('报「先停止引擎」', '先停止引擎' in str(exc), str(exc))
check('文件没动', os.path.exists(os.path.join(old2, '001.part')))

print('9) 目标已有同名文件时整批拒绝，不留半套')
fresh()
old3 = os.path.join(BASE, 'old3')
new3 = os.path.join(BASE, 'new3')
os.makedirs(old3, exist_ok=True)
os.makedirs(new3, exist_ok=True)
open(os.path.join(old3, '001.part'), 'w').write('a')
open(os.path.join(old3, '002.part'), 'w').write('b')
open(os.path.join(new3, '002.part'), 'w').write('conflict')
svc3 = servicemod.EmuleService(lambda: {"engine": {"temp_dir": old3}}, var_dir=os.path.join(BASE, 'var3'))
svc3._ctl = FakeCtl()
svc3._ctl.pid = 0
try:
    svc3.migrate_temp(old3, new3)
    check('应当抛错', False, '没抛')
except servicemod.EmuleError as exc:
    check('报同名冲突', '同名' in str(exc), str(exc))
check('001 被回滚回旧目录', os.path.exists(os.path.join(old3, '001.part')) and
      not os.path.exists(os.path.join(new3, '001.part')))
check('冲突文件内容没被覆盖', open(os.path.join(new3, '002.part')).read() == 'conflict')

print('10) 新旧目录相同时什么都不做')
fresh()
svc4 = servicemod.EmuleService(lambda: {"engine": {"temp_dir": BASE}}, var_dir=os.path.join(BASE, 'var4'))
svc4._ctl = FakeCtl()
svc4._ctl.pid = 0
res = svc4.migrate_temp(BASE, BASE)
check('count=0', res['count'] == 0, repr(res))

print('11) temp_part_files 只认 part 命名')
fresh()
names = ['001.part', '002.part.met', '003.part.met.bak', '004.part.met.seeds',
         'notes.txt', 'abc.part', '12.part']
for n in names:
    open(os.path.join(BASE, n), 'w').write('x')
svc5 = servicemod.EmuleService(lambda: {"engine": {"temp_dir": BASE}}, var_dir=os.path.join(BASE, 'var5'))
got = svc5.temp_part_files(BASE)
check('认 4 个', len(got) == 4, repr(got))
check('不认 txt', 'notes.txt' not in got)
check('不认非数字前缀', 'abc.part' not in got)
check('不认两位编号', '12.part' not in got)

print('')
if FAILS:
    print('FAILED: ' + ', '.join(FAILS))
    sys.exit(1)
print('ALL PASS')
