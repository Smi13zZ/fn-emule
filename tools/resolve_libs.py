#!/usr/bin/env python3
"""resolve_libs.py - 不执行目标二进制，静态求出它需要的共享库闭包。

为什么要自己解析 ELF：
  * 打 ARM 包时构建机是 x86，arm64 的 amuled 跑不起来，ldd 用不了；
  * 交叉解包出不依赖 binutils（fnOS 上也没有 readelf）。

用法：
    python tools/resolve_libs.py --binary <amuled> --pool <解包目录>[,<目录>] --out <输出目录>
                                 [--base libc.so.6,libm.so.6,...] [--json]

输出：把闭包里除基础库以外的 .so 复制到 --out，并在 stdout 打印 JSON
      {arch, machine, needed, copied, unresolved, from_glibc}
"""
import argparse
import json
import os
import shutil
import struct
import sys

EM_NAMES = {3: "x86", 40: "arm", 62: "x86_64", 183: "aarch64"}

DEFAULT_BASE = [
    "libc.so.6", "libm.so.6", "libpthread.so.0", "libdl.so.2", "librt.so.1",
    "libresolv.so.2", "libutil.so.1", "libstdc++.so.6", "libgcc_s.so.1",
    "libz.so.1", "ld-linux-x86-64.so.2", "ld-linux-aarch64.so.1",
]


def _read_elf(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"\x7fELF":
        raise SystemExit("不是 ELF 文件：%s" % path)
    is64 = data[4] == 2
    endian = "<" if data[5] == 1 else ">"
    if is64:
        e_machine = struct.unpack_from(endian + "H", data, 18)[0]
        e_shoff = struct.unpack_from(endian + "Q", data, 40)[0]
        e_shentsize = struct.unpack_from(endian + "H", data, 58)[0]
        e_shnum = struct.unpack_from(endian + "H", data, 60)[0]
        e_shstrndx = struct.unpack_from(endian + "H", data, 62)[0]
        sh_fmt = endian + "IIQQQQIIQQ"
    else:
        e_machine = struct.unpack_from(endian + "H", data, 18)[0]
        e_shoff = struct.unpack_from(endian + "I", data, 32)[0]
        e_shentsize = struct.unpack_from(endian + "H", data, 46)[0]
        e_shnum = struct.unpack_from(endian + "H", data, 48)[0]
        e_shstrndx = struct.unpack_from(endian + "H", data, 50)[0]
        sh_fmt = endian + "IIIIIIIIII"
    shsz = struct.calcsize(sh_fmt)
    sections = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        vals = struct.unpack_from(sh_fmt, data, off)
        if is64:
            sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size = vals[:6]
            sh_link, sh_info, sh_align, sh_entsize = vals[6:]
        else:
            sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size = vals[:6]
            sh_link, sh_info, sh_align, sh_entsize = vals[6:]
        sections.append({"name_off": sh_name, "type": sh_type, "offset": sh_offset,
                         "size": sh_size, "link": sh_link, "entsize": sh_entsize})
    shstr = sections[e_shstrndx]
    names = data[shstr["offset"]: shstr["offset"] + shstr["size"]]

    def sname(off):
        end = names.find(b"\x00", off)
        return names[off:end].decode("utf-8", "replace")

    for s in sections:
        s["name"] = sname(s["name_off"])

    dynamic = next((s for s in sections if s["name"] == ".dynamic"), None)
    dynstr = None
    needed = []
    if dynamic:
        strtab_idx = dynamic["link"]
        if 0 <= strtab_idx < len(sections):
            dynstr = sections[strtab_idx]
        strdata = data[dynstr["offset"]: dynstr["offset"] + dynstr["size"]] if dynstr else b""
        rpath = None
        entry = 16 if is64 else 8
        for off in range(0, dynamic["size"], entry):
            if is64:
                tag, val = struct.unpack_from(endian + "qQ", data, dynamic["offset"] + off)
            else:
                tag, val = struct.unpack_from(endian + "iI", data, dynamic["offset"] + off)
            if tag == 0:
                break
            if tag == 1:  # DT_NEEDED
                end = strdata.find(b"\x00", val)
                needed.append(strdata[val:end].decode("utf-8", "replace"))
            elif tag == 29:  # DT_RUNPATH
                end = strdata.find(b"\x00", val)
                rpath = strdata[val:end].decode("utf-8", "replace")
    return {"machine": e_machine, "needed": needed, "rpath": rpath}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--binary", required=True)
    ap.add_argument("--pool", required=True, help="逗号分隔的解包目录")
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default=",".join(DEFAULT_BASE))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    pools = [p for p in args.pool.split(",") if p]
    base = set(x for x in args.base.split(",") if x)

    index = {}
    for p in pools:
        for root, _dirs, files in os.walk(p):
            for fn in files:
                if ".so" in fn:
                    index.setdefault(fn, os.path.join(root, fn))

    os.makedirs(args.out, exist_ok=True)
    root_info = _read_elf(args.binary)
    machine = root_info["machine"]
    arch = EM_NAMES.get(machine, str(machine))

    seen, order, unresolved, copied = set(), [], [], []
    queue = list(root_info["needed"])
    info_cache = {}
    while queue:
        soname = queue.pop(0)
        if soname in seen:
            continue
        seen.add(soname)
        if soname in base:
            continue
        src = index.get(soname)
        if not src:
            unresolved.append(soname)
            continue
        dst = os.path.join(args.out, soname)
        if not os.path.exists(dst):
            shutil.copyfile(src, dst)
            os.chmod(dst, 0o644)
        copied.append(soname)
        if soname not in info_cache:
            info_cache[soname] = _read_elf(src)
        for dep in info_cache[soname]["needed"]:
            if dep not in seen:
                queue.append(dep)

    result = {
        "arch": arch,
        "machine": machine,
        "needed": root_info["needed"],
        "rpath": root_info["rpath"],
        "copied": sorted(copied),
        "unresolved": sorted(unresolved),
        "base_skipped": sorted(seen & base),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2 if not args.json else None))
    return 1 if unresolved else 0


if __name__ == "__main__":
    sys.exit(main())
