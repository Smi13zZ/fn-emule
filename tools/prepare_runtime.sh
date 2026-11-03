#!/bin/bash
### prepare_runtime.sh - 从 Debian 12 官方包抽出 aMule 运行时（支持 amd64 / arm64）
###
### 目的：让 fpk 自带 amuled 与它需要的共享库，不往用户系统里装任何 apt 包，
### 也不依赖 fnOS 是否预装了 libupnp/wxWidgets。
###
### 用法：
###   ./prepare_runtime.sh [--arch amd64|arm64] [输出目录]      # 默认 amd64 + /tmp/emule-runtime-<arch>
###
### 产物：
###   <输出目录>/out/usr/bin/amuled
###   <输出目录>/out/usr/lib/<triplet>/*.so*
###   <输出目录>/out/usr/share/doc/amule-daemon/*          （许可证原文）
###   <输出目录>/amule-runtime-<arch>.tar.gz
###
### 说明：
###   * amd64 在本机直接跑 ldd + amuled --version 自检；
###   * arm64 交叉取包：dpkg 加 arm64 架构 → apt 下 *:arm64 包 → 用 tools/resolve_libs.py
###     静态解析 ELF 依赖（不执行目标二进制），再校验没有未解析依赖。
set -euo pipefail

ARCH="amd64"
DEST=""
while [ $# -gt 0 ]; do
    case "$1" in
        --arch) ARCH="${2:-}"; shift 2 ;;
        --arch=*) ARCH="${1#--arch=}"; shift ;;
        -*) echo "未知参数：$1" >&2; exit 2 ;;
        *) DEST="$1"; shift ;;
    esac
done

case "${ARCH}" in
    amd64) TRIPLET="x86_64-linux-gnu"; AMULE_ARCH_SUFFIX="" ;;
    arm64) TRIPLET="aarch64-linux-gnu"; AMULE_ARCH_SUFFIX=":arm64" ;;
    *) echo "不支持的架构：${ARCH}（只支持 amd64 / arm64）" >&2; exit 2 ;;
esac

DEST="${DEST:-/tmp/emule-runtime-${ARCH}}"
WORK="${DEST}/work"
OUT="${DEST}/out"
LIBDIR="${OUT}/usr/lib/${TRIPLET}"

HERE="$(cd "$(dirname "$0")" && pwd)"
RESOLVE="${HERE}/resolve_libs.py"

PKGS="amule-daemon libwxbase3.2-1 libcrypto++8 libupnp13 libixml10 libpcre2-32-0"

rm -rf "${WORK}" "${OUT}"
mkdir -p "${WORK}/debs" "${WORK}/root" "${OUT}/usr/bin" "${LIBDIR}"

# 容器里是 root（没有 sudo），测试机上是普通用户（需要 sudo）
if [ "$(id -u)" -eq 0 ]; then APT_SUDO=""; else APT_SUDO="sudo"; fi

if [ "${ARCH}" = "arm64" ]; then
    if ! dpkg --print-foreign-architectures | grep -qx arm64; then
        echo "== 启用 arm64 多架构支持 =="
        ${APT_SUDO} dpkg --add-architecture arm64
        ${APT_SUDO} apt-get update -qq
    fi
fi

echo "== 下载 Debian 包（${ARCH}）=="
cd "${WORK}/debs"
apt-get download $(for p in ${PKGS}; do printf '%s%s ' "${p}" "${AMULE_ARCH_SUFFIX}"; done)
ls -1 *.deb | sed 's/^/   /'

echo "== 解包 =="
for d in *.deb; do
    dpkg-deb -x "${d}" "${WORK}/root"
done

echo "== 复制 amuled =="
cp -f "${WORK}/root/usr/bin/amuled" "${OUT}/usr/bin/amuled"
chmod 755 "${OUT}/usr/bin/amuled"

echo "== 解析共享库依赖并复制 =="
if [ "${ARCH}" = "amd64" ]; then
    TMPLIBDIR="${WORK}/libs"
    mkdir -p "${TMPLIBDIR}"
    find "${WORK}/root/usr/lib" -name '*.so*' \( -type f -o -type l \) -exec cp -Lf {} "${TMPLIBDIR}/" \; 2>/dev/null || true
    LD_LIBRARY_PATH="${TMPLIBDIR}" ldd "${OUT}/usr/bin/amuled" | awk '{for(i=1;i<=NF;i++) if($i ~ /^\//) print $i}' | sort -u > "${WORK}/ldd.txt"
    echo "   amuled 依赖："; sed 's/^/     /' "${WORK}/ldd.txt"

    BASE_LIBS="libc.so.6 libm.so.6 libpthread.so.0 libdl.so.2 librt.so.1 libresolv.so.2
libstdc++.so.6 libgcc_s.so.1 libz.so.1 ld-linux-x86-64.so.2 libutil.so.1"
    MISSING=0
    while read -r lib; do
        base="$(basename "${lib}")"
        skip=0
        for b in ${BASE_LIBS}; do [ "${base}" = "${b}" ] && skip=1 && break; done
        [ "${skip}" -eq 1 ] && continue
        if [ -f "${TMPLIBDIR}/${base}" ]; then src="${TMPLIBDIR}/${base}"
        elif [ -f "${lib}" ]; then src="${lib}"
        else echo "   !! 找不到 ${base}" >&2; MISSING=1; continue; fi
        cp -Lf "${src}" "${LIBDIR}/${base}"
        chmod 644 "${LIBDIR}/${base}"
    done < "${WORK}/ldd.txt"

    echo "== 自检：只靠随包库能否运行 =="
    NOTFOUND="$(LD_LIBRARY_PATH="${LIBDIR}" ldd "${OUT}/usr/bin/amuled" 2>&1 | grep 'not found' || true)"
    if [ -n "${NOTFOUND}" ]; then
        echo "   !! 仍有库没打进来：" >&2; echo "${NOTFOUND}" >&2; exit 1
    fi
    VER_OUT="$(LD_LIBRARY_PATH="${LIBDIR}" "${OUT}/usr/bin/amuled" --version 2>&1 || true)"
    if printf '%s' "${VER_OUT}" | grep -q 'aMule'; then
        echo "   OK  ${VER_OUT}"
    else
        echo "   !! amuled 无法启动：" >&2; echo "${VER_OUT}" >&2; exit 1
    fi
else
    JSON="$(python3 "${RESOLVE}" --binary "${OUT}/usr/bin/amuled" --pool "${WORK}/root/usr/lib" --out "${LIBDIR}" --json)"
    printf '%s\n' "${JSON}" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("   arch=%s 库=%d 未解析=%d" % (d["arch"], len(d["copied"]), len(d["unresolved"]))); print("   库清单：" + ", ".join(d["copied"]))'
    ARCH_SEEN="$(printf '%s' "${JSON}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["arch"])')"
    UNRESOLVED="$(printf '%s' "${JSON}" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["unresolved"]))')"
    if [ "${ARCH_SEEN}" != "aarch64" ]; then
        echo "   !! amuled 不是 aarch64（实际 ${ARCH_SEEN}）" >&2; exit 1
    fi
    if [ "${UNRESOLVED}" -ne 0 ]; then
        echo "   !! 有 ${UNRESOLVED} 个依赖没找到" >&2
        printf '%s' "${JSON}" >&2
        exit 1
    fi
    for f in "${LIBDIR}"/*.so*; do
        head -c 20 "${f}" | grep -q 'ELF' || { echo "   !! ${f} 不是 ELF" >&2; exit 1; }
    done
    echo "   OK  arm64 运行时依赖完整（静态校验通过，无法在本机执行）"
fi

echo "== 附带许可证 =="
mkdir -p "${OUT}/usr/share/doc/amule-daemon"
cp -f "${WORK}/root/usr/share/doc/amule-daemon/copyright" "${OUT}/usr/share/doc/amule-daemon/" 2>/dev/null || true
for p in libwxbase3.2-1 libcrypto++8 libupnp13 libixml10 libpcre2-32-0; do
    src="${WORK}/root/usr/share/doc/${p}/copyright"
    [ -f "${src}" ] && cp -f "${src}" "${OUT}/usr/share/doc/amule-daemon/${p}.copyright" || true
done
ls -1 "${OUT}/usr/share/doc/amule-daemon/" | sed 's/^/   /'

echo "== 体积 =="
du -sh "${OUT}"
du -sh "${OUT}/usr/bin/amuled" "${LIBDIR}"

echo "== 打包 =="
tar -czf "${DEST}/amule-runtime-${ARCH}.tar.gz" -C "${OUT}" .
ls -lh "${DEST}/amule-runtime-${ARCH}.tar.gz"
echo "ARCH=${ARCH} TRIPLET=${TRIPLET}"
