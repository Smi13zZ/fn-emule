# 图标源素材

`emule-logo.svg` / `emule-logo-2x.png` 是 eMule **官方吉祥物（驴头）**：

- 出处：<https://commons.wikimedia.org/wiki/File:EMule_logo.svg>，版权方为 eMule 项目（<https://www.emule-project.net>），
  Wikimedia 页面标注许可为 **GPL**。
- `emule-logo-2x.png` 是把该 SVG 用 Chromium 渲染出的 1000px 位图（透明背景），供 `tools/make_icons.py` 裁切合成。

重新生成图标：

```bash
python tools/make_icons.py     # 读 emule-logo-2x.png → 输出 ICON.PNG / ICON_256.PNG / web icon
```

如果以后要换回矢量渲染，重新渲染的命令（在设备上）：

```bash
chromium --headless --no-sandbox --default-background-color=00000000 \
  --force-device-scale-factor=2 --window-size=500,498 \
  --screenshot=emule-logo-2x.png file://$PWD/emule-logo.svg
```