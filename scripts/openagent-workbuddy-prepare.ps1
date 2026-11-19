param(
  [Parameter(Mandatory = $true)]
  [ValidateSet('preflight', 'prepare', 'check-and-prepare')]
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

function Resolve-Python {
  foreach ($command in (Get-Command -Name python3, python -All -CommandType Application -ErrorAction SilentlyContinue)) {
    try {
      $lines = @(& $command.Path -I -X utf8 -c "import sys; print(sys.executable); sys.exit(sys.version_info < (3, 9))" 2>$null)
      if ($LASTEXITCODE -ne 0 -or $lines.Count -ne 1) { continue }
      $executable = $lines[0].Trim()
      if ([IO.Path]::IsPathRooted($executable) -and (Test-Path -LiteralPath $executable -PathType Leaf)) { return $executable }
    } catch { continue }
  }
  throw 'Python 3.9+ is required (python3 or python)'
}

if ($Stage -ne 'prepare') {
  $setup = Join-Path ([IO.Path]::GetTempPath()) ('openagent-setup-' + [guid]::NewGuid().ToString('N') + '.py')
  try {
    $pythonExe = Resolve-Python
    curl.exe --fail --location --silent --show-error --proto '=https' --proto-redir '=https' "$installBase/scripts/openagent-workbuddy-setup.py" -o $setup
    if ($LASTEXITCODE -ne 0) { throw 'Setup download failed' }
    & $pythonExe -X utf8 -B -c "import ast,sys; from pathlib import Path; ast.parse(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))" $setup
    if ($LASTEXITCODE -ne 0) { throw 'Setup syntax check failed' }
    try {
      $ErrorActionPreference = 'Continue'
      $checkOutput = @(& $pythonExe -X utf8 -B $setup --source $Source --check-config 2>&1)
      $checkCode = $LASTEXITCODE
    } finally {
      $ErrorActionPreference = 'Stop'
    }
    $checkLines = @($checkOutput | ForEach-Object { $_.ToString() })
    $checkLines | Write-Output
    Write-Output ('SETUP_CHECK_EXIT=' + $checkCode)
    $ready = $checkCode -eq 0 -and $checkLines -contains 'CONFIG_READY'
    $needsEdit = $checkCode -eq 1 -and $checkLines.Count -eq 1 -and $checkLines[0] -match '^CONFIG_UPDATE_REQUIRED=.+$'
    if (-not ($ready -or $needsEdit)) { throw 'Setup preflight failed' }
    if ($Stage -eq 'preflight') {
      Write-Output ('SETUP_SCRIPT_READY=' + $setup)
      Write-Output ('PREPARE_SCRIPT_READY=' + $PSCommandPath)
      return
    }
    if ($needsEdit) {
      Remove-Item -LiteralPath $setup -Force
      return
    }
    $SetupScript = $setup
  } catch {
    Remove-Item -LiteralPath $setup -Force -ErrorAction SilentlyContinue
    throw
  }
}

$setup = $SetupScript
if (-not $setup -or -not [IO.Path]::IsPathRooted($setup) -or -not (Test-Path -LiteralPath $setup -PathType Leaf)) { throw 'Downloaded setup not found' }
$setupItem = Get-Item -LiteralPath $setup -Force
if ($setupItem.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Invalid downloaded setup' }
$targetDir = Join-Path $HOME '.workbuddy'
$restartDir = Join-Path ([IO.Path]::GetTempPath()) ('openagent-restart-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $restartDir | Out-Null
try {
  $pythonExe = Resolve-Python
  $result = & $pythonExe -X utf8 -B $setup --source $Source --sync-only
  $code = $LASTEXITCODE
  $result | Write-Output
  if ($code -ne 0 -or $result -notcontains 'PLUGIN_READY') { throw 'Plugin verification failed' }
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
