# 只读预检与准备重启脚本；配置编辑和安排重启仍由各自的独立工具调用完成。
param(
  [Parameter(Mandatory = $true)]
  [ValidateSet('preflight', 'prepare')]
  [string]$Stage,
  [Parameter(Mandatory = $true)]
  [ValidateSet('gitee', 'github')]
  [string]$Source,
  [string]$SetupScript
)

$ErrorActionPreference = 'Stop'
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $OutputEncoding
$env:PYTHONIOENCODING = 'utf-8'
$installBase = @{
  gitee = 'https://gitee.com/openagent-org/workbuddy-plugin/raw/rel'
  github = 'https://raw.githubusercontent.com/openagent-org/workbuddy-plugin/rel'
}[$Source]

if ($Stage -eq 'preflight') {
  $setup = Join-Path ([IO.Path]::GetTempPath()) ('openagent-setup-' + [guid]::NewGuid().ToString('N') + '.py')
  try {
    curl.exe --fail --location --silent --show-error --proto '=https' --proto-redir '=https' "$installBase/scripts/openagent-workbuddy-setup.py" -o $setup
    if ($LASTEXITCODE -ne 0) { throw 'Setup download failed' }
    & python3 -X utf8 -B -c "import ast,sys; from pathlib import Path; ast.parse(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))" $setup
    if ($LASTEXITCODE -ne 0) { throw 'Setup syntax check failed' }
    try {
      $ErrorActionPreference = 'Continue'
      $checkOutput = @(& python3 -X utf8 -B $setup --source $Source --verify-only 2>&1)
      $checkCode = $LASTEXITCODE
    } finally {
      $ErrorActionPreference = 'Stop'
    }
    $checkLines = @($checkOutput | ForEach-Object { $_.ToString() })
    $checkLines | Write-Output
    Write-Output ('SETUP_CHECK_EXIT=' + $checkCode)
    $ready = $checkCode -eq 0 -and $checkLines -contains 'PLUGIN_READY'
    $needsEdit = $checkCode -eq 1 -and $checkLines.Count -eq 1 -and $checkLines[0] -match '^CONFIG_UPDATE_REQUIRED=.+$'
    if (-not ($ready -or $needsEdit)) { throw 'Setup preflight failed' }
    Write-Output ('SETUP_SCRIPT_READY=' + $setup)
    Write-Output ('PREPARE_SCRIPT_READY=' + $PSCommandPath)
  } catch {
    Remove-Item -LiteralPath $setup -Force -ErrorAction SilentlyContinue
    throw
  }
  return
}

$setup = $SetupScript
if (-not $setup -or -not [IO.Path]::IsPathRooted($setup) -or -not (Test-Path -LiteralPath $setup -PathType Leaf)) { throw 'Downloaded setup not found' }
$setupItem = Get-Item -LiteralPath $setup -Force
if ($setupItem.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Invalid downloaded setup' }
$targetDir = Join-Path $HOME '.workbuddy'
$restartDir = Join-Path ([IO.Path]::GetTempPath()) ('openagent-restart-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $restartDir | Out-Null
try {
  $result = & python3 -X utf8 -B $setup --source $Source --verify-only
  $code = $LASTEXITCODE
  $result | Write-Output
  if ($code -ne 0 -or $result -notcontains 'PLUGIN_READY') { throw 'Plugin verification failed' }
  $pythonOutput = @(& python3 -c "import sys; assert sys.version_info >= (3,9); print(sys.executable)")
  if ($LASTEXITCODE -ne 0 -or $pythonOutput.Count -ne 1) { throw 'Python resolution failed' }
  $pythonExe = $pythonOutput[0].Trim()
  if (-not [IO.Path]::IsPathRooted($pythonExe) -or -not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) { throw 'Invalid Python executable' }
  $download = Join-Path $restartDir 'openagent-workbuddy-restart.py'
  curl.exe --fail --location --silent --show-error --proto '=https' --proto-redir '=https' "$installBase/scripts/openagent-workbuddy-restart.py" -o $download
  if ($LASTEXITCODE -ne 0) { throw 'Restart script download failed' }
  & $pythonExe -B -c "import ast,sys; from pathlib import Path; ast.parse(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))" $download
  if ($LASTEXITCODE -ne 0) { throw 'Python syntax check failed' }
  $destination = Join-Path $targetDir 'openagent-workbuddy-restart.py'
  if (Test-Path -LiteralPath $destination) {
    $item = Get-Item -LiteralPath $destination -Force
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Invalid script destination' }
  }
  Move-Item -LiteralPath $download -Destination $destination -Force
  Write-Output ('RESTART_SCRIPT_READY=' + $destination)
  Write-Output ('RESTART_PYTHON_READY=' + $pythonExe)
} finally {
  Remove-Item -LiteralPath $restartDir -Recurse -Force
  Remove-Item -LiteralPath $setup -Force
}
