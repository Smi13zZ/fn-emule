#!/usr/bin/env python3
"""verify_fpk.py - 检查打好的 .fpk 结构是否完整、权限是否正确。

    python tools/verify_fpk.py output/fn-emule-26.11.0-fnos-x86.fpk

检查项：
  * 外层：manifest / app.tgz / cmd / config / wizard / ICON*.PNG
  * manifest 的 version 与文件名版本一致；appname / platform 存在
  * cmd/* 带可执行位
  * app.tgz：面板服务、core 模块、前端资源、ui/index.cgi（可执行位）、
    随包 amuled 与依赖库（可执行位）
"""
import io
import os
import re
import sys
import tarfile

# app.tgz 里必须存在的文件（相对 app/ 根）
NEED_INNER = [
    "server/emulepanel.py",
    "server/core/ec.py",
    "server/core/amule_ctl.py",
    "server/core/service.py",
    "server/core/bootstrap.py",
    "server/core/__init__.py",
    "server/store.py",
    "server/netutil.py",
    "server/notify.py",
    "ui/index.cgi",
    "web/index.html",
    "web/style.css",
    "web/js/app.js",
    "web/js/api.js",
    "web/js/i18n.js",
    "web/js/util.js",
    "web/js/charts.js",
    "web/lib/vue.global.prod.js",
    "runtime/amd64/usr/bin/amuled",
    "runtime/arm64/usr/bin/amuled",
]


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def manifest_field(text, key):
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(key) and "=" in s:
            return s.split("=", 1)[1].strip()
    return ""


def main():
    if len(sys.argv) < 2:
        fail("usage: verify_fpk.py <file.fpk>")
    path = sys.argv[1]
    if not os.path.isfile(path):
        fail("not found: %s" % path)

    with tarfile.open(path) as outer:
        members = {m.name: m for m in outer.getmembers()}
        for need in ("manifest", "app.tgz", "cmd", "config", "wizard", "ICON.PNG", "ICON_256.PNG"):
            if need not in members:
                fail("outer archive is missing %s" % need)

        manifest = outer.extractfile("manifest").read().decode("utf-8", "replace")
        version = manifest_field(manifest, "version")
        appname = manifest_field(manifest, "appname")
        platform = manifest_field(manifest, "platform")
        if not version:
            fail("manifest has no version")
        m = re.search(r"-(\d+\.\d+\.\d+)-fnos-", os.path.basename(path))
        if m and m.group(1) != version:
            fail("file name version %s != manifest version %s" % (m.group(1), version))

        cmd = [mm for n, mm in members.items() if n.startswith("cmd/") and mm.isfile()]
        if not cmd:
            fail("outer archive has no cmd/ scripts")
        bad = [mm.name for mm in cmd if not mm.mode & 0o111]
        if bad:
            fail("cmd scripts lost their executable bit: %s" % ", ".join(bad))

        inner = tarfile.open(fileobj=io.BytesIO(outer.extractfile("app.tgz").read()))
        inner_members = {mm.name: mm for mm in inner.getmembers()}
        missing = [n for n in NEED_INNER if n not in inner_members]
        if missing:
            fail("app.tgz is missing: %s" % ", ".join(missing))
        if not inner_members["ui/index.cgi"].mode & 0o111:
            fail("ui/index.cgi is not executable")

        # 一个包要同时带 x86 与 ARM 两套引擎，且各自架构正确
        libs = []
        for arch, expect_machine in (("amd64", 62), ("arm64", 183)):
            amuled = inner_members["runtime/%s/usr/bin/amuled" % arch]
            if not amuled.mode & 0o111:
                fail("runtime/%s/usr/bin/amuled is not executable" % arch)
            if amuled.size < 1_000_000:
                fail("runtime/%s/usr/bin/amuled looks truncated (%d bytes)" % (arch, amuled.size))
            head = inner.extractfile(amuled).read(20)
            if head[:4] != b"\x7fELF":
                fail("runtime/%s/usr/bin/amuled is not an ELF binary" % arch)
            machine = int.from_bytes(head[18:20], "little")
            if machine != expect_machine:
                fail("runtime/%s/usr/bin/amuled ELF machine=%d，期望 %d" % (arch, machine, expect_machine))
            arch_libs = [n for n in inner_members if n.startswith("runtime/%s/usr/lib/" % arch) and ".so" in n]
            if len(arch_libs) < 5:
                fail("runtime/%s 的共享库不全（%d 个）" % (arch, len(arch_libs)))
            libs.extend(arch_libs)
        if platform not in ("all", "x86", "arm"):
            fail("platform=%s 不是 fnOS 认可的值" % platform)

        # 结构闸门：把包里的面板代码真的解出来做一次结构检查。
        # 语法合法但方法缩进跑偏时类上会少方法，装到设备上才报 AttributeError。
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import check_structure
        # 直接在内存里解析源码，不落地：包里同名文件（如多个 __init__.py）不会互相覆盖，
        # 也不会受临时目录权限影响。
        for name in sorted(n for n in inner_members if n.endswith(".py")):
            source = inner.extractfile(inner_members[name]).read()
            problems = check_structure.check_source(source, name)
            if problems:
                fail("%s 结构有问题：%s" % (name, "；".join(problems)))

    size = os.path.getsize(path)
    print("OK  %s" % os.path.basename(path))
    print("    appname=%s version=%s platform=%s" % (appname, version, platform))
    print("    外层 %d 项 / app.tgz %d 项（含 %d 个随包库）" % (len(members), len(inner_members), len(libs)))
    print("    size=%.2f MB" % (size / 1048576.0))


if __name__ == "__main__":
    main()
