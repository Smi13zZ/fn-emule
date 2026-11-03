#!/usr/bin/env python3
"""build_fpk.py - 把 src/emule 打成飞牛 fnOS 可安装的 .fpk（x86 + ARM 两份）

为什么必须在 Linux 上打：
  * fnpack 在 Windows 上产出的包会把 cmd/* 与 app/ui/index.cgi 的可执行位写成
    0666，fnOS 安装时直接报 appcenter 10111；
  * 手工重新 tar 会破坏 fnpack 的归档装配，同样被拒。

多架构：
  * manifest 的 platform 字段必须是 x86 / arm（fnOS 用它决定能不能装到该架构的设备）；
  * 引擎运行时来自 Debian 12 对应架构的包：amd64 用本机 ldd 自检，arm64 用
    tools/resolve_libs.py 静态解析 ELF 依赖（构建机是 x86 也能做）；
  * 一份源码分别打两次包，其他文件完全相同。

用法（仓库根目录）：
    python tools/build_fpk.py                     # 打 x86 + arm 两个包到 output/
    python tools/build_fpk.py --platforms x86     # 只打一个
    python tools/build_fpk.py --install           # 打完把 x86 包装到测试机
"""
import argparse
import base64
import os
import posixpath
import subprocess
import sys
import tarfile
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "emule")
OUT = os.path.join(ROOT, "output")

DEFAULT_HOST = "fnos-test"
REMOTE_WORK = "/tmp/emule-build"

SKIP_DIRS = {"__pycache__", ".pytest_cache", "node_modules", ".git", "runtime", "_prev"}
SKIP_EXT = {".pyc", ".pyo", ".prev", ".log", ".orig", ".rej", ".fpk"}

PLATFORM_ARCH = {"all": "full", "x86": "amd64", "arm": "arm64"}


def manifest_field(key, default=""):
    path = os.path.join(SRC, "manifest")
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s.startswith(key) and "=" in s:
                return s.split("=", 1)[1].strip()
    return default


def run(argv):
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    out = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                         errors="replace", env=env)
    if out.stdout:
        sys.stdout.write(out.stdout)
    if out.returncode != 0:
        if out.stderr:
            sys.stderr.write(out.stderr)
        raise SystemExit("command failed (%d): %s" % (out.returncode, " ".join(argv[:3])))
    return out.stdout


def ssh(script, host):
    b64 = base64.b64encode(script.encode()).decode()
    return run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host,
                "echo %s | base64 -d | bash -s" % b64])


def scp_up(local, remote, host):
    run(["scp", "-o", "BatchMode=yes", "-q", local, "%s:%s" % (host, remote)])


def scp_down(remote, local, host):
    run(["scp", "-o", "BatchMode=yes", "-q", "%s:%s" % (host, remote), local])


def _filter(ti):
    norm = ti.name.replace("\\", "/")
    if any(part in SKIP_DIRS for part in norm.split("/")):
        return None
    if os.path.splitext(norm)[1].lower() in SKIP_EXT:
        return None
    return ti


def build_one(host, workdir, platform, ver, app, keywords):
    arch = PLATFORM_ARCH[platform]
    if arch == "full":
        runtime_dir = "/tmp/emule-runtime-full"
        rt_tar = posixpath.join(runtime_dir, "amule-runtime-full.tar.gz")
    else:
        runtime_dir = "/tmp/emule-runtime-%s" % arch
        rt_tar = posixpath.join(runtime_dir, "amule-runtime-%s.tar.gz" % arch)

    print("\n===== 打包 platform=%s (arch=%s) =====" % (platform, arch))
    # 1) 源码（每次覆盖，保证手机 manifest 是源里的原样）
    tmp_tar = os.path.join(tempfile.gettempdir(), "emule-src-%s.tar" % platform)
    with tarfile.open(tmp_tar, "w") as tf:
        for name in sorted(os.listdir(SRC)):
            if name in ("emule.fpk", "fn-emule.fpk"):
                continue
            tf.add(os.path.join(SRC, name), arcname=name, filter=_filter)
    ssh("mkdir -p %s" % workdir, host)
    scp_up(tmp_tar, posixpath.join(workdir, "emule-src.tar"), host)
    ssh("cd {wd} && rm -rf app cmd config wizard manifest ICON.PNG ICON_256.PNG && "
        "tar -xf emule-src.tar && ls -1 | head -5".format(wd=workdir), host)

    # 2) manifest 的 platform 按本次目标改写（只改 NAS 上的副本，不动源码）
    ssh("cd {wd} && sed -i 's/^platform.*/platform              = {p}/' manifest && "
        "grep -E '^(appname|version|platform)' manifest".format(wd=workdir, p=platform), host)

    # 3) 运行时
    have = ssh("test -f %s && echo HAVE || echo MISS" % rt_tar, host)
    if "MISS" in have:
        print("[runtime] NAS 上没有 %s，现场生成（需要能访问 Debian 源）…" % rt_tar)
        for name in ("prepare_runtime.sh", "resolve_libs.py", "build_runtime_full.sh"):
            scp_up(os.path.join(ROOT, "tools", name), "/tmp/" + name, host)
        ssh("chmod +x /tmp/prepare_runtime.sh /tmp/build_runtime_full.sh && cd /tmp && "
            "bash /tmp/build_runtime_full.sh %s 2>&1 | tail -22" % runtime_dir, host)
    else:
        print("[runtime] 复用 %s" % rt_tar)
    ssh("cd {wd} && rm -rf app/runtime && mkdir -p app/runtime && "
        "tar -xzf {rt} -C app/runtime && ls app/runtime/ && "
        "(ls app/runtime/usr/bin 2>/dev/null || ls app/runtime/*/usr/bin) && "
        "du -sh app/runtime".format(wd=workdir, rt=rt_tar), host)

    # 4) 权限 + fnpack build
    ssh("cd {wd} && "
        "find . -name '__pycache__' -type d -prune -exec rm -rf {{}} + ; "
        "find . -type d -exec chmod 755 {{}} + ; "
        "find . -type f -exec chmod 644 {{}} + ; "
        "chmod 755 cmd/* app/ui/index.cgi ; "
        "chmod 755 app/runtime/usr/bin/* 2>/dev/null || true ; "
        "chmod 755 app/runtime/usr/lib/*/*.so* 2>/dev/null || true ; "
        "chmod 755 app/runtime/*/usr/bin/* 2>/dev/null || true ; "
        "chmod 755 app/runtime/*/usr/lib/*/*.so* 2>/dev/null || true ; "
        "fnpack build 2>&1 | tail -3 && ls -l {app}.fpk".format(wd=workdir, app=app), host)

    # 5) 取回 + 校验
    out_name = "%s-%s-fnos-%s.fpk" % (app, ver, platform)
    out_path = os.path.join(OUT, out_name)
    scp_down(posixpath.join(workdir, "%s.fpk" % app), out_path, host)
    print("[out] %s (%d bytes)" % (out_name, os.path.getsize(out_path)))

    scp_up(os.path.join(ROOT, "tools", "verify_fpk.py"), "/tmp/emule-verify-fpk.py", host)
    scp_up(out_path, "/tmp/emule-last-%s.fpk" % platform, host)
    print(ssh("python3 /tmp/emule-verify-fpk.py /tmp/emule-last-%s.fpk 2>&1" % platform, host))
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--workdir", default=REMOTE_WORK)
    ap.add_argument("--platforms", default="all", help="默认 all（一个包通吃 x86+ARM）；可选 x86/arm 单打")
    ap.add_argument("--install", action="store_true", help="构建后把 x86 包装到测试机")
    args = ap.parse_args()
    host = args.host

    ver = manifest_field("version")
    app = manifest_field("appname")
    if not ver or not app:
        raise SystemExit("manifest 缺 version/appname")
    os.makedirs(OUT, exist_ok=True)

    # 打之前先做语法闸门：语法错误的面板打进去，装完就是"引擎组件不可用"，很贵的教训
    print("[0/3] 语法检查 src/emule/app/server/**/*.py")
    py_files = []
    for root, _dirs, files in os.walk(os.path.join(SRC, "app", "server")):
        for fn in files:
            if fn.endswith(".py"):
                py_files.append(os.path.join(root, fn))
    check = subprocess.run([sys.executable, "-m", "py_compile"] + py_files,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check.returncode != 0:
        sys.stderr.write(check.stderr)
        raise SystemExit("语法检查失败，已中止打包")
    print("       %d 个文件通过" % len(py_files))

    # 结构闸门：语法合法但方法缩进跑偏（类上少方法）这种错误，py_compile 抓不到，
    # 装到设备上要等真实请求才报 AttributeError。
    print("[0b/3] 结构检查（类方法是否齐全）")
    checker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check_structure.py")
    struct = subprocess.run([sys.executable, checker] + py_files,
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if struct.returncode != 0:
        sys.stderr.write(struct.stdout)
        sys.stderr.write(struct.stderr)
        raise SystemExit("结构检查失败，已中止打包")
    print("       结构正常")

    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
    for p in platforms:
        if p not in PLATFORM_ARCH:
            raise SystemExit("不支持的 platform：%s（只支持 %s）" % (p, ",".join(PLATFORM_ARCH)))

    built = []
    for p in platforms:
        built.append(build_one(host, args.workdir, p, ver, app, None))

    if args.install:
        installable = [b for b in built if b.endswith("-fnos-all.fpk") or b.endswith("-fnos-x86.fpk")]
        if not installable:
            raise SystemExit("--install 需要构建 all 或 x86 包")
        x86 = installable[:1]
        env_file = os.path.join(tempfile.gettempdir(), "fn-emule.env")
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("wizard_backend_port=17581\nwizard_tcp_port=4662\nwizard_udp_port=4672\n")
        scp_up(env_file, "/tmp/fn-emule.env", host)
        scp_up(x86[0], "/tmp/fn-emule-install.fpk", host)
        print(ssh("sudo appcenter-cli uninstall fn-emule >/dev/null 2>&1 || true; "
                  "sudo appcenter-cli install-fpk /tmp/fn-emule-install.fpk -e /tmp/fn-emule.env -v 1 "
                  "2>&1 | tr '\\r' '\\n' | grep -vE 'installing|Verifying' | tail -4", host))
        print(ssh("sudo appcenter-cli list 2>&1 | grep fn-emule", host))

    print("\n== 完成 ==")
    for b in built:
        print("  %s  %d bytes" % (os.path.basename(b), os.path.getsize(b)))


if __name__ == "__main__":
    main()
