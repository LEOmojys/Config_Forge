param(
    [switch]$Install,
    [switch]$NoBrowser,
    [switch]$CheckOnly,
    [string]$PythonPath = $env:PYTHON,
    [string]$BackendHost = "0.0.0.0",
    [int]$BackendPort = 8000,
    [string]$FrontendHost = "0.0.0.0",
    [int]$FrontendPort = 3000
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$FrontendDir = Join-Path $Root "frontend"
$Requirements = Join-Path $Root "backend\requirements.txt"

function Write-Step {
    param([string]$Message)
    Write-Host "[ConfigForge] $Message" -ForegroundColor Cyan
}

function Resolve-Tool {
    param(
        [string[]]$Names,
        [string]$FriendlyName
    )

    foreach ($name in $Names) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) {
            return $cmd.Source
        }
    }

    throw "$FriendlyName is not installed or not available in PATH."
}

function Test-Port {
    param([int]$Port)

    $client = $null
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $result = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $connected = $result.AsyncWaitHandle.WaitOne(250, $false)
        if ($connected -and $client.Connected) {
            $client.EndConnect($result)
            return $true
        }
        return $false
    } catch {
        return $false
    } finally {
        if ($client) {
            $client.Close()
        }
    }
}

function Wait-Port {
    param(
        [int]$Port,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Port -Port $Port) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Escape-ForPowerShellSingleQuote {
    param([string]$Value)
    return $Value.Replace("'", "''")
}

Set-Location -LiteralPath $Root

Write-Step "Project root: $Root"

if (-not (Test-Path $FrontendDir)) {
    throw "Missing frontend directory: $FrontendDir"
}
if (-not (Test-Path $Requirements)) {
    throw "Missing backend requirements file: $Requirements"
}

if ($PythonPath) {
    $pythonCmd = Get-Command $PythonPath -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $Python = $pythonCmd.Source
    } elseif (Test-Path $PythonPath) {
        $Python = (Resolve-Path $PythonPath).Path
    } else {
        throw "PythonPath does not exist or is not executable: $PythonPath"
    }
} else {
    $Python = Resolve-Tool -Names @("python.exe", "python") -FriendlyName "Python"
}
$Npm = Resolve-Tool -Names @("npm.cmd", "npm") -FriendlyName "npm"
$PowerShell = Resolve-Tool -Names @("powershell.exe", "powershell") -FriendlyName "PowerShell"

Write-Step "Python: $Python"
Write-Step "npm: $Npm"

if ($CheckOnly) {
    Write-Step "Check-only mode: prerequisites found. No servers will be started."
    exit 0
}

if ($Install) {
    Write-Step "Installing backend dependencies..."
    & $Python -m pip install -r $Requirements
    if ($LASTEXITCODE -ne 0) {
        throw "Backend dependency installation failed."
    }

    Write-Step "Installing frontend dependencies..."
    Push-Location -LiteralPath $FrontendDir
    try {
        & $Npm install
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend dependency installation failed."
        }
    } finally {
        Pop-Location
    }
} else {
    Write-Step "Checking backend runtime dependencies..."
    & $Python -c "import fastapi, uvicorn" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Step "Backend dependencies are missing. Installing from backend/requirements.txt..."
        & $Python -m pip install -r $Requirements
        if ($LASTEXITCODE -ne 0) {
            throw "Backend dependency installation failed."
        }
    }

    $NodeModules = Join-Path $FrontendDir "node_modules"
    if (-not (Test-Path $NodeModules)) {
        Write-Step "frontend/node_modules is missing. Running npm install..."
        Push-Location -LiteralPath $FrontendDir
        try {
            & $Npm install
            if ($LASTEXITCODE -ne 0) {
                throw "Frontend dependency installation failed."
            }
        } finally {
            Pop-Location
        }
    }
}

$BackendAlreadyRunning = Test-Port -Port $BackendPort
$FrontendAlreadyRunning = Test-Port -Port $FrontendPort

if ($BackendAlreadyRunning) {
    Write-Step "Backend port $BackendPort is already in use. Reusing the running service."
} else {
    Write-Step "Starting backend on http://localhost:$BackendPort ..."
    $rootArg = Escape-ForPowerShellSingleQuote $Root
    $pythonArg = Escape-ForPowerShellSingleQuote $Python
    $backendCommand = @"
`$Host.UI.RawUI.WindowTitle = 'ConfigForge Backend :$BackendPort'
Set-Location -LiteralPath '$rootArg'
& '$pythonArg' -m uvicorn backend.api.app:app --host $BackendHost --port $BackendPort --reload
"@
    Start-Process -FilePath $PowerShell -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $backendCommand)
}

if ($FrontendAlreadyRunning) {
    Write-Step "Frontend port $FrontendPort is already in use. Reusing the running service."
} else {
    Write-Step "Starting frontend on http://localhost:$FrontendPort ..."
    $frontendArg = Escape-ForPowerShellSingleQuote $FrontendDir
    $npmArg = Escape-ForPowerShellSingleQuote $Npm
    $frontendCommand = @"
`$Host.UI.RawUI.WindowTitle = 'ConfigForge Frontend :$FrontendPort'
Set-Location -LiteralPath '$frontendArg'
& '$npmArg' run dev -- --host $FrontendHost --port $FrontendPort
"@
    Start-Process -FilePath $PowerShell -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $frontendCommand)
}

Write-Step "Waiting for services..."
$backendReady = Wait-Port -Port $BackendPort -TimeoutSeconds 30
$frontendReady = Wait-Port -Port $FrontendPort -TimeoutSeconds 45

if (-not $backendReady) {
    Write-Warning "Backend did not become ready on port $BackendPort within timeout. Check the backend window."
}
if (-not $frontendReady) {
    Write-Warning "Frontend did not become ready on port $FrontendPort within timeout. Check the frontend window."
}

$Url = "http://localhost:$FrontendPort"
if ($frontendReady -and -not $NoBrowser) {
    Write-Step "Opening $Url"
    Start-Process $Url
}

Write-Step "Done. Backend: http://localhost:$BackendPort, Frontend: $Url"
