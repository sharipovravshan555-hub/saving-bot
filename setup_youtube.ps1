$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectDir ".venv\Scripts\python.exe"
$providerDir = Join-Path $projectDir "vendor\bgutil-ytdlp-pot-provider"
$serverDir = Join-Path $providerDir "server"
$localhostPatch = Join-Path $projectDir "bgutil-localhost.patch"

if (-not (Test-Path -LiteralPath $venvPython)) {
    python -m venv (Join-Path $projectDir ".venv")
}

& $venvPython -m pip install -r (Join-Path $projectDir "requirements.txt")

if (-not (Test-Path -LiteralPath $providerDir)) {
    git clone --single-branch --branch 1.3.1 `
        https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git `
        $providerDir
}

$providerSource = Join-Path $serverDir "src\main.ts"
if (-not (Select-String -LiteralPath $providerSource -Pattern 'host: "127.0.0.1"' -Quiet)) {
    & git -C $providerDir apply $localhostPatch
    if ($LASTEXITCODE -ne 0) {
        throw "Could not restrict the PO-token server to localhost."
    }
}

Push-Location $serverDir
try {
    & npm.cmd ci
    & npx.cmd tsc
} finally {
    Pop-Location
}

Write-Host "Cookie-free YouTube support is ready."
