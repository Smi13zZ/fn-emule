#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""升级进度三条收敛规则的静态闸门。

这三条不是风格偏好，是 26.11.57 上真实出现过的「点一键更新后卡在遮罩里」
的直接成因。删掉任何一条，同样的故障会回来：

  1. 阶段只允许前进（checking < downloading < verifying < installing）
  2. total 只增不减，且只在 downloading 分支内累积
  3. 单调性只在同一 attempt 内成立（attempt 变了必须整体重置）

另外两条配套约束同样必须存在，否则修法本身会引入新 bug：

  4. 不拿安装响应体里的 task 绘制进度（那是 total=0 的一帧快照）
  5. installing 阶段把 total 归零是**有意**的，不能被当成「减少」而丢弃

用法：python3 tools/check_update_mono.py
退出码 0 = 通过，1 = 有规则缺失。
"""

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
APP_JS = os.path.join(REPO_ROOT, "src", "emule", "app", "web", "js", "app.js")


def read():
    with io.open(APP_JS, encoding="utf-8") as fh:
        return fh.read()


def slice_function(text, name):
    """截出 `name: function (...) {` 到配对的右括号为止。"""
    start = text.find(name)
    if start < 0:
        return ""
    brace = text.find("{", start)
    if brace < 0:
        return ""
    depth = 0
    for i in range(brace, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return ""


def main():
    src = read()
    body = slice_function(src, "applyUpdateTask: function")
    failures = []

    if not body:
        print("FAIL 找不到 applyUpdateTask —— 进度收敛逻辑被改名或删掉了")
        return 1

    # 1. 阶段顺序表
    if re.search(r"checking\s*:\s*0", body) is None:
        failures.append("规则 1 缺少阶段顺序表（checking 应为 0）")
    if re.search(r"installing\s*:\s*3", body) is None:
        failures.append("规则 1 缺少阶段顺序表（installing 应为 3）")
    if "nextRank < prevRank" not in body:
        failures.append("规则 1 缺少「后退快照丢弃」的比较")

    # 2. total 只在 downloading 分支累积
    if 'phase === "downloading"' not in body:
        failures.append("规则 2 缺少 downloading 分支判断")
    if "Math.max(Number(prev.total) || 0, nextTotal)" not in body:
        failures.append("规则 2 下载阶段没有用 Math.max 累积 total")

    # 3. attempt 变化时整体重置
    if "updateMonoAttempt" not in body:
        failures.append("规则 3 缺少 attempt 基线字段")
    if "attempt !== this.updateMonoAttempt" not in body:
        failures.append("规则 3 缺少「attempt 变了就重置」的判断")

    # 4. 安装响应体不得用于绘制进度
    if re.search(r"applyUpdateTask\(\s*r\.task\s*\)", src):
        failures.append("规则 4 仍在用安装响应里的 task 绘制进度")

    # 5. installing 阶段 total 归零必须保留
    if not re.search(r"progress\.total\s*=\s*0", body):
        failures.append("约束 5 安装阶段没有把 total 归零")

    # 配套：刷新必须等面板回来
    if "reloadWhenBack" not in src:
        failures.append("配套 缺少 reloadWhenBack（装完直接 reload 会撞进离线窗口）")
    # 只看升级收尾这一段：备份导入/恢复那两处 setTimeout(reload) 是正当的，
    # 它们不涉及「面板自己被卸载重装」。
    finish = slice_function(src, "finishUpdate: function")
    if not finish:
        failures.append("配套 找不到 finishUpdate")
    elif "reloadWhenBack" not in finish:
        failures.append("配套 finishUpdate 没有走 reloadWhenBack")
    elif re.search(r"location\.reload\(\)", finish):
        failures.append("配套 finishUpdate 里仍有直接 location.reload()")

    # 配套：每轮开工清空安装日志（后端）
    panel_py = os.path.join(REPO_ROOT, "src", "emule", "app", "server", "emulepanel.py")
    with io.open(panel_py, encoding="utf-8") as fh:
        back = fh.read()
    if "_reset_update_log" not in back:
        failures.append("配套 后端没有 _reset_update_log（上一轮结论会被当成这一轮）")
    if '"verifying"' not in back:
        failures.append("配套 后端 UPDATE_ACTIVE_PHASES 缺少 verifying")

    if failures:
        for item in failures:
            print("FAIL", item)
        return 1

    print("OK   升级进度收敛规则齐备（阶段只前进 / total 只增 / attempt 隔离）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
