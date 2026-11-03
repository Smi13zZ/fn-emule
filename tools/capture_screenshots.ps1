# capture_screenshots.ps1 - 用本机 Chrome headless 抓面板截图（给 README 用）
# 注意：本机 Chrome 常被沙箱拦截；更可靠的做法是 scp 到测试机用 chromium 抓（见 docs/DEVELOPMENT.md）。
param(
    [string]$Base = "http://192.168.1.13:17581",
    [string]$Out = "docs/images",
    [string]$Chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$outDir = Join-Path $root $Out
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$prof = Join-Path $env:TEMP "emule-shot-profile"
Remove-Item -Recurse -Force $prof -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $prof | Out-Null
$shots = @(
    @{ name = "overview";     url = "?view=dash";           w = 1440; h = 980 },
    @{ name = "tasks";        url = "?view=tasks";          w = 1440; h = 980 },
    @{ name = "servers";      url = "?view=servers";        w = 1440; h = 980 },
    @{ name = "search";       url = "?view=search";         w = 1440; h = 980 },
    @{ name = "shared";       url = "?view=shared";         w = 1440; h = 980 },
    @{ name = "stats";        url = "?view=stats";          w = 1440; h = 980 },
    @{ name = "logs";         url = "?view=logs";           w = 1440; h = 980 },
    @{ name = "settings";     url = "?view=settings";       w = 1440; h = 1000 },
    @{ name = "diagnostics";  url = "?view=diagnostics";    w = 1440; h = 1000 },
    @{ name = "dark";         url = "?view=dash&theme=dark"; w = 1440; h = 980 },
    @{ name = "mobile";       url = "?view=tasks";          w = 390;  h = 844 },
    @{ name = "stats-mobile"; url = "?view=stats";          w = 390;  h = 844 },
    @{ name = "diag-mobile";  url = "?view=diagnostics";    w = 390;  h = 844 }
)
foreach ($s in $shots) {
    $file = Join-Path $outDir ($s.name + ".png")
    Remove-Item -Force $file -ErrorAction SilentlyContinue
    $target = "$Base/$($s.url)"
    & $Chrome --headless=new --disable-gpu --hide-scrollbars --no-first-run --user-data-dir=$prof --window-size=$($s.w),$($s.h) --virtual-time-budget=9000 --screenshot=$file $target 2>$null | Out-Null
    if (Test-Path $file) { Write-Host "OK  $($s.name)  $((Get-Item $file).Length) bytes" }
    else { Write-Host "FAIL $($s.name)" }
}
