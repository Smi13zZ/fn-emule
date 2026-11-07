# 会话压缩摘要（2026-11-07 15:5x CST）

> 本文件是跨 fn-emule / qbpanel / pvepanel / fail2ban 四条产品线会话的压缩状态卡，
> 供后续会话快速续接。完整规则见 `~/.dsh/AGENTS.md`（本次已同步更新）。

## 一、四条产品线当前状态

| 产品 | 仓库 | 最新版本 | 测试机 | 生产机 |
| --- | --- | --- | --- | --- |
| eMule | Smi13zZ/fn-emule | **26.11.47** | 26.11.47 | **仍 26.11.44**，未升级（只读巡检过） |
| qBpanel | Smi13zZ/qbpanel | **26.11.11** | 26.11.11 | — |
| PVEpanel | Smi13zZ/pvepanel | **26.11.17** | 26.11.17 | — |
| Fail2ban | 无 GitHub 仓库 | 26.11.4（本地交付） | — | 用户自行在应用中心升级，**绝不代操作** |

本次会话发布的 3 个 Release：

- https://github.com/Smi13zZ/fn-emule/releases/tag/v26.11.44 / .45 / .46 / .47
- https://github.com/Smi13zZ/qbpanel/releases/tag/v26.11.11
- https://github.com/Smi13zZ/pvepanel/releases/tag/v26.11.17

## 二、本次会话做的事（按时间）

1. **26.11.44**：修网友反馈的两个 bug + 附带发现的一个
   - 通知通道删不掉：前端发 `{id, remove:true}`，后端只认 `delete` → 落到新增分支报「未知类型」。
   - 共享目录上千文件只扫几百：aMule `AddFilesFromDirectory()` 不递归子目录且不给提示。
     面板写 `shareddir.dat` 前摊平目录树（4000 条 / 8 层上限）。
   - `EC_OP_SHAREDFILES_RELOAD` 同步阻塞整个面板 → 改 fire-and-forget + `_pending_noop` 计数吞 NOOP。
2. **生产机日志只读巡检**：健康；历史 error（11-04 的 `require_method`）已修；
   11-06 唯一一条「更新包下载截断」是自愈的；Bark 密钥正常（`__SET__` 是打码，别重填）；
   共享目录确实为空；`updates/` 16 个包 / 135 MB 待清理。
3. **26.11.45**：设置新增「维护 / 存储」页
   - 统计各目录占用；清理旧安装包（保留最近 2 个 + 当前运行版本永不删 + 删所有 `.part`）；
   - 清空日志（引擎运行中 **truncate 不能 unlink**，否则 fd 占着 inode 空间不释放）；
   - 日志页「清屏」按钮原来是假的（只清浏览器数组），改成真清磁盘。
4. **26.11.46 / 26.11.47**：手机端更新状态条两轮迭代
   - .46 把图标与两行文字并排、按钮独占一行；.47 再给两按钮包 `.vactions` 让它们并排。
   - 关键坑：零高整行宽的 `.vbreak` 断不了行，必须直接给按钮/容器 `flex-basis:100%`；
     `display:contents` 保住桌面端布局。
   - `--dump-dom` 忽略 `--window-size`（报 780px 桌面布局），量手机端必须用 `--screenshot`。
5. **qBpanel 26.11.11 / PVEpanel 26.11.17**：把同一套 `.vactions` 方案同步过去。
   - **Fail2ban 没有更新界面**（SPEC 写明无 GitHub 仓库、不做在线升级），本次不涉及。
   - qbpanel 本地 `build_fpk.py` 依赖已消失的 WorkBuddy 路径，本地打包失效，但项目本就只走 CI。

## 三、长期规则（已写进 AGENTS.md）

- 版本 `年.月.序号`、**每条产品线独立计数**、交付必 bump、tag 用 `v` 前缀。
- CHANGELOG / Release / commit / 注释里**不写「参照/对齐/和 xxx 一致」**。
- eMule 应用名不带「电驴」；**不要删测试机上那 6 个下载任务**。
- `fnos-prod` 任何变更必须先取得用户明确同意，只读巡检可直接做；`fnos-test` 可自由操作。
- 改完先在 fnos-test 实机验证再发布；用户要看效果时给截图。
- 发布后自检：下载 Release 包 → verify → 装到测试机 → 旧版本面板对真实 Release 查更新。

## 四、待办 / 未完成

1. **生产机仍是 26.11.44**，`updates/` 里 16 个包 / 135 MB 未清。用户尚未点头升级+清理。
2. 生产机日志里「更新包下载截断 → 自动重试」那条 error 建议降级成 info（体验优化，非 bug，未做）。
3. 升级成功后自动清理 `updates/` 下 `.part` 的机制未做（目前靠维护页手动清）。
4. qbpanel 本地 `tools/build_fpk.py` 的两个失效路径未修（不影响 CI 发布）。

## 五、验证手段速查

- 无头截图：`ssh fnos-test` → `/usr/bin/chromium --headless=new --screenshot`，scp 回本地。
- 手机布局断言用截图（或把测量值画进页面再截图）；别用 `--dump-dom`。
- 临时面板：`EMULE_VERSION=<旧> EMULE_VAR=/tmp/xxx EMULE_NO_SERVICE=1 ...`，按端口查 pid 精确杀。
- GitHub token 走 `git-credential-manager.exe get`，只在内存里用，绝不落盘。
- 三道闸门：`check_structure.py` / `build_fpk.py` / `verify_fpk.py`；pvepanel 另有 `preflight.py`。