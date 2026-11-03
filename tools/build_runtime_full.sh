#!/bin/bash
### build_runtime_full.sh - 把 x86 与 ARM 两套 aMule 运行时合成一个"全架构"运行时
###
### 产物：
###   <输出目录>/out/amd64/usr/bin/amuled + usr/lib/x86_64-linux-gnu/*.so*
###   <输出目录>/out/arm64/usr/bin/amuled + usr/lib/aarch64-linux-gnu/*.so*
###   <输出目录>/amule-runtime-full.tar.gz
###
### 面板运行时会按 platform.machine() 选 amd64 / arm64 子目录，
### 所以一个 fpk 能同时装到飞牛的 x86 与 ARM 设备上（manifest platform = all）。
###
### 用法：./build_runtime_full.sh [输出目录]     # 默认 /tmp/emule-runtime-full
set -euo pipefail

DEST="${1:-/tmp/emule-runtime-full}"
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="${DEST}/work"
OUT="${DEST}/out"

rm -rf "${WORK}" "${OUT}"
mkdir -p "${WORK}" "${OUT}"

for ARCH in amd64 arm64; do
    echo ""
    echo "========== 构建 ${ARCH} 运行时 =========="
    bash "${HERE}/prepare_runtime.sh" --arch "${ARCH}" "${WORK}/${ARCH}"
    mkdir -p "${OUT}/${ARCH}"
    cp -a "${WORK}/${ARCH}/out/." "${OUT}/${ARCH}/"
    echo "   -> ${OUT}/${ARCH}: $(du -sh "${OUT}/${ARCH}" | cut -f1)"
done

echo ""
echo "== 全架构运行时自检 =="
for ARCH in amd64 arm64; do
    BIN="${OUT}/${ARCH}/usr/bin/amuled"
    [ -f "${BIN}" ] || { echo "   !! 缺 ${BIN}" >&2; exit 1; }
    MACHINE="$(od -An -tu2 -j18 -N2 "${BIN}" | tr -d ' ')"
    case "${ARCH}" in
        amd64) WANT=62 ;;
        arm64) WANT=183 ;;
    esac
    if [ "${MACHINE}" != "${WANT}" ]; then
        echo "   !! ${ARCH} amuled 的 ELF machine=${MACHINE}，期望 ${WANT}" >&2
        exit 1
    fi
    COUNT=$(ls "${OUT}/${ARCH}/usr/lib/"*/ 2>/dev/null | wc -l)
    echo "   ${ARCH}: amuled machine=${MACHINE} OK，库目录 ${COUNT} 个"
done

echo ""
echo "== 体积 =="
du -sh "${OUT}" "${OUT}"/amd64 "${OUT}"/arm64

echo "== 打包 =="
tar -czf "${DEST}/amule-runtime-full.tar.gz" -C "${OUT}" .
ls -lh "${DEST}/amule-runtime-full.tar.gz"
echo "FULL_RUNTIME_OK"
