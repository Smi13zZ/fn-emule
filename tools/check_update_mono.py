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

    if not check_notes_and_log(src):
        return 1

    extra = check_indeterminate_and_verline()
    if extra:
        for item in extra:
            print("FAIL", item)
        return 1

    print("OK   升级进度收敛规则齐备（阶段只前进 / total 只增 / attempt 隔离）")
    return 0


def check_notes_and_log(src):
    """Release 正文渲染与安装日志展示的约束。

    这四条都是「要么用户投诉、要么自己踩过」才补上的，删掉会以同样的形态回来：
      1. Release 正文经 md.js 渲染（纯文本 / 剥语法都会丢结构）
      2. index.html 引入 md.js（少了它渲染器不存在，正文退回纯文本）
      3. 安装日志只在失败时展开（升级途中一直显示=噪音）
      4. 装完不再弹第二条 toast（遮罩里已经有同一句话）
    """
    failures = []
    web = os.path.join(REPO_ROOT, "src", "emule", "app", "web")
    html_path = os.path.join(web, "index.html")
    html = ""
    if os.path.isfile(html_path):
        with io.open(html_path, encoding="utf-8") as fh:
            html = fh.read()

    if "updateNotesHtml" not in src:
        failures.append("Release 正文没有走 Markdown 渲染（缺少 updateNotesHtml）")
    if html and "js/md.js" not in html:
        failures.append("index.html 没有引入 js/md.js")
    if not os.path.isfile(os.path.join(web, "js", "md.js")):
        failures.append("缺少 web/js/md.js")

    # 安装日志必须绑在 updateError 上
    for line in html.splitlines():
        if "upinstalllog" in line and "v-if=" in line and "updateError" not in line:
            failures.append("安装日志没有绑在 updateError 上（升级途中会一直显示）")
            break
    if html and "updateInstallLog" not in html:
        failures.append("index.html 没有安装日志块")

    finish = slice_function(src, "finishUpdate: function")
    if finish and "this.ok(" in finish:
        failures.append("finishUpdate 仍在弹 toast（遮罩已显示同一句话）")

    # 后端必须清洗 appcenter-cli 的转圈帧
    panel_py = os.path.join(REPO_ROOT, "src", "emule", "app", "server", "emulepanel.py")
    with io.open(panel_py, encoding="utf-8") as fh:
        back = fh.read()
    if "clean_install_log" not in back:
        failures.append("后端没有 clean_install_log（转圈帧会原样进界面）")
    elif "clean_install_log(handle.read())" not in back:
        failures.append("update_log_tail 没有调用 clean_install_log")

    for item in failures:
        print("FAIL", item)
    return not failures


def check_indeterminate_and_verline():
    """不确定态进度条 + 版本行图标对齐。

    两条都是「实测过才定下来的数值」，删掉会以同样的形态回来：

    1. 遮罩在检查 / 校验 / 安装阶段没有可测总量，原先显示一句静态的
       「准备中…」。它看不出「还在动」，而且与上方阶段文字
       （「安装包已就绪，正在重启服务…」）语义打架。改成一条来回流动的
       条，颜色取 var(--primary) —— 浅色主题近黑、深色主题近白，自动反色。
    2. 版本行的地球图标与版本文字：flex 的 align-items:center 对齐的是
       行盒，而数字墨迹偏上、默认行高又比字形高小半行，实测图标低
       2.0–2.3px。收窄行高 + 图标上移 1px 后降到 0.0–0.33px。
    """
    fails = []
    css_path = os.path.join(REPO_ROOT, "src", "emule", "app", "web", "style.css")
    css = io.open(css_path, encoding="utf-8").read() if os.path.isfile(css_path) else ""
    if not css:
        fails.append("找不到 style.css，无法核对遮罩样式")
        return fails

    # 1) 不确定态：必须有 .upprog.indeterminate 与流动动画
    #    这里一律用「选择器 + 大括号 + 关键声明」精确匹配。
    #    裸子串会把 @media 里的 .upprog.indeterminate .upprog-flow 也算进来，
    #    删掉主规则后仍然判过 —— 变异测试抓过这个洞。
    if not re.search(r"\.upprog\.indeterminate\s*\{[^}]*\}", css):
        fails.append("缺少 .upprog.indeterminate 规则（不确定态退回静态文字）")
    if not re.search(r"\.upprog\.indeterminate\s+\.upprog-flow\s*\{[^}]*\}", css):
        fails.append("缺少 .upprog-flow 规则（那条流动的亮条）")
    if not re.search(r"@keyframes\s+upprogFlow\s*\{", css):
        fails.append("缺少 upprogFlow 动画（条不会动，等于还是静态）")
    # 动画必须真的被挂到流动条上
    m = re.search(r"\.upprog\.indeterminate\s+\.upprog-flow\s*\{([^}]*)\}", css)
    if m and "animation" not in m.group(1):
        fails.append(".upprog-flow 没有挂动画")
    # 颜色必须走主题变量，不能写死蓝色或黑色
    if m:
        body = m.group(1)
        if "var(--primary)" not in body:
            fails.append("不确定条没有用 var(--primary)（夜间模式不会反色）")
        for hard in ("#3b82f6", "#2563eb", "#000", "#111", "rgb(0, 0, 0)"):
            if hard in body:
                fails.append("不确定条写死了颜色 %s（夜间模式不会反色）" % hard)
    # 关掉动效时必须退回静止条，不能继续动
    # 同样要精确到「那条 reduced-motion 媒体查询里确实改了 .upprog-flow」
    rm = re.search(r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{"
                   r"[\s\S]{0,400}?\.upprog-flow[\s\S]{0,200}?\}", css)
    if not rm:
        fails.append("缺少 prefers-reduced-motion 兜底（前庭敏感用户会不适）")
    elif "animation: none" not in rm.group(0):
        fails.append("reduced-motion 兜底里没有关掉动画")

    # 2) 版本行对齐
    if not re.search(r"\.ver-line\s*\{[^}]*line-height:\s*16px", css):
        fails.append("版本行没有 line-height: 16px（图标会比文字低 2px）")
    if not re.search(r"\.ver-line\s+svg\s*\{[^}]*translateY\(-1px\)", css):
        fails.append("版本行图标没有 translateY(-1px) 补偿")

    return fails


if __name__ == "__main__":
    sys.exit(main())
