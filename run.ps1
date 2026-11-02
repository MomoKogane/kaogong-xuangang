<#
  考公选岗（xuangang）一键入口。

  用法（推荐，能绕过 Windows  PowerShell 执行策略）：
    .\run.cmd doctor
    .\run.cmd init
    .\run.cmd import --inspect data\incoming\positions
    .\run.cmd run --config config\bob.toml --positions data\incoming\positions --history data\incoming\history --out out\2027
    .\run.cmd serve --port 8765

  也可以直接用 Python：
    python -m xuangang run --config config\bob.toml ...

  说明：脚本会依次寻找“装了 pandas / openpyxl / xlsxwriter”的 Python，
  优先使用 DSH 自带运行时，其次 py -3.12 / py -3.13 / python。
#>

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

$candidates = @(
    (Join-Path $env:USERPROFILE '.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'),
    'C:\Users\邵国豪\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
)

$python = $null
foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
        & $candidate -c "import pandas, openpyxl, xlsxwriter" 2>$null
        if ($LASTEXITCODE -eq 0) { $python = $candidate; break }
    }
}

if (-not $python) {
    foreach ($launcher in @(@('py', '-3.12'), @('py', '-3.13'), @('python', $null))) {
        $exe = Get-Command $launcher[0] -ErrorAction SilentlyContinue
        if (-not $exe) { continue }
        $cmdArgs = @()
        if ($launcher[1]) { $cmdArgs += $launcher[1] }
        $cmdArgs += @('-c', 'import pandas, openpyxl, xlsxwriter')
        & $exe.Source @cmdArgs 2>$null
        if ($LASTEXITCODE -eq 0) {
            $python = $exe.Source
            if ($launcher[1]) { $script:PyLauncherArgs = @($launcher[1]) }
            break
        }
    }
}

if (-not $python) {
    Write-Host '[xuangang] 没有找到安装了 pandas/openpyxl/xlsxwriter 的 Python。' -ForegroundColor Red
    Write-Host '请先安装： pip install pandas openpyxl XlsxWriter' -ForegroundColor Yellow
    Write-Host '（本机网络受限时，也可指定已有虚拟环境里的 python 手动运行： python -m xuangang ...）' -ForegroundColor Yellow
    exit 1
}

$pyPrefix = @()
if ($script:PyLauncherArgs) { $pyPrefix = @($script:PyLauncherArgs) }

if ($args.Count -eq 0) {
    & $python @pyPrefix -m xuangang --help
} else {
    & $python @pyPrefix -m xuangang @args
}
exit $LASTEXITCODE
