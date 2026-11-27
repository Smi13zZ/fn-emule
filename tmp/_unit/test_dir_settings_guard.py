# -*- coding: utf-8 -*-
# 整份 draft 保存时，打码的 ec_password 不能污染 amule.conf / EC。
# 这是 26.11.63 修的洞：前端拿到 "__SET__"，整份回传，amule.conf 的
# ECPassword 就被写成 md5("__SET__")，引擎重启后再也连不上。
import os, sys, re, hashlib
REPO = r'D:\Workspace\DSH\fn-emule'
sys.path.insert(0, os.path.join(REPO, 'src', 'emule', 'app', 'server', 'core'))
sys.path.insert(0, os.path.join(REPO, 'src', 'emule', 'app', 'server'))

FAILS = []


def check(name, cond, detail=''):
    if cond:
        print('  ok   ' + name)
    else:
        print('  FAIL ' + name + ' ' + detail)
        FAILS.append(name)


PANEL = os.path.join(REPO, 'src', 'emule', 'app', 'server', 'emulepanel.py')
src = open(PANEL, encoding='utf-8').read()

print('1) 面板必须在调用 apply_prefs 之前把打码密码剔除')
block = src[src.index('settings, changed = RT.store.update(patch)'):]
block = block[:block.index('RT.log("设置已更新')]
check('有剔除逻辑', 'storemod.SECRET_MARK' in block, '没找到 SECRET_MARK 过滤')
check('过滤的是 ec_password', 'k != "ec_password"' in block or "k != 'ec_password'" in block)
check('__KEEP__ 也挡', '__KEEP__' in block)
# 顺序：剔除必须在 apply_prefs 之前
i_filter = block.index('k != "ec_password"')
i_apply = block.index('"apply_prefs"')
check('顺序：先剔除再 apply_prefs', i_filter < i_apply,
      'filter@%d apply@%d' % (i_filter, i_apply))

print('2) core.apply_prefs 也确实会写 ECPassword（漏洞成立的前提还在）')
CTL = os.path.join(REPO, 'src', 'emule', 'app', 'server', 'core', 'amule_ctl.py')
ctl = open(CTL, encoding='utf-8').read()
check('conf_text 写 ECPassword', '("ExternalConnect", "ECPassword")' in ctl)
check('用 md5 写', '_md5_hex(settings["ec_password"])' in ctl)
# 确认：如果它拿到的就是 "__SET__"，写进 conf 的 md5 就是那个值
check('md5("__SET__") 与真实密码不同',
      hashlib.md5(b'__SET__').hexdigest() != hashlib.md5(b'realpw').hexdigest())

print('3) 落盘那一层（store.update）也必须挡')
STORE = os.path.join(REPO, 'src', 'emule', 'app', 'server', 'store.py')
store = open(STORE, encoding='utf-8').read()
check('store.update 剔除打码值', 'SECRET_MARK' in store and 'pop("ec_password"' in store)

print('4) 面板在标记要重启时必须真的去重启')
check('调用了 schedule_engine_restart', 'schedule_engine_restart' in src)
i_flag = block.index('restart_required and RT.service is not None')
check('重启挂在 restart_required 上', i_flag > 0)
# 后台线程必须存在，否则请求会超时
check('重启是后台线程', 'engine-restart' in src)
check('重启预算 > 15 秒（要等 partfile 落盘）',
      'ENGINE_RESTART_BUDGET' in src and 'ENGINE_RESTART_BUDGET = 120.0' in src)

print('5) 目录在落盘前必须先验可写')
i_check = src.index('RT.service.check_dir')
i_update = src.index('settings, changed = RT.store.update(patch)')
check('校验在 store.update 之前', i_check < i_update,
      'check_dir@%d store.update@%d' % (i_check, i_update))
check('校验失败返回 400 且不落盘', '设置未保存' in src)
# 目录校验只碰文件系统，不该排进引擎队列（引擎卡在慢调用时会一起被堵）
check('目录校验不走 EC 队列', 'RT.call("check_dir"' not in src)

print('6) 迁移提示卡片的样式要跟其余警告卡片一致（不加粗左边框）')
CSS = os.path.join(REPO, 'src', 'emule', 'app', 'web', 'style.css')
css = open(CSS, encoding='utf-8').read()


def rule(selector):
    """取出某个选择器的规则块（第一个匹配的顶层规则）。"""
    i = css.find(selector + ' {')
    if i < 0:
        return ''
    j = css.find('}', i)
    return css[i:j]


dirmig = rule('.dirmig')
check('有 .dirmig 规则', bool(dirmig))
check('没有加粗左边框', 'border-left' not in dirmig, dirmig.replace('\n', ' '))
check('保留整体 1px 边框', 'border: 1px solid' in dirmig)
# 项目里警告类卡片的底子是 --card，不是 transparent（否则浅色主题下透出白底发灰）
check('底色基于 --card', 'var(--card)' in dirmig, dirmig.replace('\n', ' '))
# 与已有的上行提示条保持同一套写法
upbanner = rule('.upbanner')
check('.upbanner 也是 1px + --card（同一套写法）',
      'border: 1px solid' in upbanner and 'var(--card)' in upbanner)

print('')
if FAILS:
    print('FAILED: ' + ', '.join(FAILS))
    sys.exit(1)
print('ALL PASS')
