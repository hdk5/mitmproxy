param(
    [ValidateRange(1, 65535)]
    [int]$OriginPort = 18090,

    [ValidateRange(1, 65535)]
    [int]$ProxyPort = 18091,

    [ValidateRange(1, 30)]
    [double]$BlockingSeconds = 3,

    [ValidateRange(0.1, 10)]
    [double]$FastLimitSeconds = 1,

    [string]$CurlPath = "curl.exe"
)

$ErrorActionPreference = "Stop"

$OriginUrl = "http://127.0.0.1:$OriginPort"
$ProxyUrl = "http://127.0.0.1:$ProxyPort"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$PythonPath = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
$MitmdumpPath = Join-Path $RepositoryRoot ".venv\Scripts\mitmdump.exe"
$OriginProcess = $null
$ProxyProcess = $null
$SlowProcess = $null
$ExitCode = 1

$TempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$TempDirectory = Join-Path `
    $TempRoot `
    ("mitmproxy-request-stream-" + [guid]::NewGuid().ToString("N"))
[IO.Directory]::CreateDirectory($TempDirectory) | Out-Null

$MarkerPath = Join-Path $TempDirectory "blocking.marker"
$PayloadPath = Join-Path $TempDirectory "payload.bin"
$OriginStdout = Join-Path $TempDirectory "origin.stdout.log"
$OriginStderr = Join-Path $TempDirectory "origin.stderr.log"
$ProxyStdout = Join-Path $TempDirectory "proxy.stdout.log"
$ProxyStderr = Join-Path $TempDirectory "proxy.stderr.log"

$ProxyVariables = @("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
$PreviousProxyEnvironment = @{}
foreach ($Name in $ProxyVariables) {
    $PreviousProxyEnvironment[$Name] =
        [Environment]::GetEnvironmentVariable($Name, "Process")
    [Environment]::SetEnvironmentVariable($Name, "", "Process")
}

$PreviousMarker = $env:BENCH_REQUEST_STREAM_MARKER
$PreviousDelay = $env:BENCH_REQUEST_STREAM_DELAY
$env:BENCH_REQUEST_STREAM_MARKER = $MarkerPath
$env:BENCH_REQUEST_STREAM_DELAY = $BlockingSeconds.ToString(
    [Globalization.CultureInfo]::InvariantCulture
)

function Wait-TcpPort {
    param(
        [Parameter(Mandatory)]
        [int]$Port,

        [int]$TimeoutSeconds = 15
    )

    $Stopwatch = [Diagnostics.Stopwatch]::StartNew()
    while ($Stopwatch.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        $Client = [Net.Sockets.TcpClient]::new()
        try {
            $Connect = $Client.ConnectAsync("127.0.0.1", $Port)
            if ($Connect.Wait(250) -and $Client.Connected) {
                return
            }
        }
        catch {
            # The listener may still be starting.
        }
        finally {
            $Client.Dispose()
        }
        Start-Sleep -Milliseconds 100
    }
    throw "Timed out waiting for TCP port $Port."
}

function Wait-ForMarker {
    param([int]$TimeoutSeconds = 15)

    $Stopwatch = [Diagnostics.Stopwatch]::StartNew()
    while ($Stopwatch.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        if (Test-Path -LiteralPath $MarkerPath) {
            return
        }
        if ($SlowProcess.HasExited) {
            throw "The slow curl exited before the transformer started blocking."
        }
        Start-Sleep -Milliseconds 50
    }
    throw "Timed out waiting for the request transformer to block."
}

function Write-ProcessLogs {
    foreach ($LogPath in @(
        $OriginStdout,
        $OriginStderr,
        $ProxyStdout,
        $ProxyStderr
    )) {
        if ((Test-Path -LiteralPath $LogPath) -and
            (Get-Item -LiteralPath $LogPath).Length -gt 0) {
            Write-Host "--- $LogPath"
            Get-Content -LiteralPath $LogPath
        }
    }
}

function Stop-ProcessTree {
    param([Diagnostics.Process]$Process)

    if ($null -ne $Process -and -not $Process.HasExited) {
        # The Windows virtual-environment launchers create a child Python
        # process. Kill the exact process tree so the benchmark leaves no
        # listeners behind.
        & taskkill.exe /PID $Process.Id /T /F 2>&1 | Out-Null
    }
}

try {
    if (-not (Get-Command $CurlPath -ErrorAction SilentlyContinue)) {
        throw "Unable to find curl at '$CurlPath'."
    }
    if (-not (Test-Path -LiteralPath $PythonPath)) {
        throw "Unable to find '$PythonPath'. Run 'uv sync' first."
    }
    if (-not (Test-Path -LiteralPath $MitmdumpPath)) {
        throw "Unable to find '$MitmdumpPath'. Run 'uv sync' first."
    }

    [byte[]]$Payload = [byte[]]::new(64 * 1024)
    for ($Index = 0; $Index -lt $Payload.Length; $Index++) {
        $Payload[$Index] = [byte][char]"x"
    }
    [IO.File]::WriteAllBytes($PayloadPath, $Payload)

    $OriginProcess = Start-Process `
        -FilePath $PythonPath `
        -ArgumentList @("origin.py", "--port", $OriginPort) `
        -WorkingDirectory $PSScriptRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $OriginStdout `
        -RedirectStandardError $OriginStderr `
        -PassThru
    Wait-TcpPort -Port $OriginPort

    $ProxyProcess = Start-Process `
        -FilePath $MitmdumpPath `
        -ArgumentList @(
            "--quiet",
            "--listen-host", "127.0.0.1",
            "--listen-port", $ProxyPort,
            "--scripts", "addon.py"
        ) `
        -WorkingDirectory $PSScriptRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $ProxyStdout `
        -RedirectStandardError $ProxyStderr `
        -PassThru
    Wait-TcpPort -Port $ProxyPort

    # Warm up curl and verify that traffic traverses the proxy.
    & $CurlPath `
        --silent `
        --show-error `
        --fail `
        --max-time 10 `
        --output NUL `
        --http1.1 `
        --proxy $ProxyUrl `
        --url "$OriginUrl/fast"
    if ($LASTEXITCODE -ne 0) {
        throw "Proxy preflight failed with curl exit code $LASTEXITCODE."
    }

    $SlowStopwatch = [Diagnostics.Stopwatch]::StartNew()
    $SlowProcess = Start-Process `
        -FilePath $CurlPath `
        -ArgumentList @(
            "--silent",
            "--show-error",
            "--fail",
            "--max-time", ($BlockingSeconds + 10),
            "--output", "NUL",
            "--http1.1",
            "--proxy", $ProxyUrl,
            "--header", "Expect:",
            "--data-binary", "@$PayloadPath",
            "--url", "$OriginUrl/slow"
        ) `
        -WindowStyle Hidden `
        -PassThru

    Wait-ForMarker

    $FastStopwatch = [Diagnostics.Stopwatch]::StartNew()
    & $CurlPath `
        --silent `
        --show-error `
        --fail `
        --max-time ($FastLimitSeconds + 5) `
        --output NUL `
        --http1.1 `
        --proxy $ProxyUrl `
        --url "$OriginUrl/fast"
    $FastExitCode = $LASTEXITCODE
    $FastStopwatch.Stop()

    $SlowTimeoutMilliseconds = [int](($BlockingSeconds + 15) * 1000)
    if (-not $SlowProcess.WaitForExit($SlowTimeoutMilliseconds)) {
        throw "The slow curl did not finish within the timeout."
    }
    $SlowStopwatch.Stop()

    $Measurements = @(
        [pscustomobject]@{
            Request = "Blocking POST"
            Seconds = [math]::Round($SlowStopwatch.Elapsed.TotalSeconds, 3)
            ExitCode = $SlowProcess.ExitCode
        },
        [pscustomobject]@{
            Request = "Unrelated fast GET"
            Seconds = [math]::Round($FastStopwatch.Elapsed.TotalSeconds, 3)
            ExitCode = $FastExitCode
        }
    )

    Write-Host ""
    $Measurements | Format-Table Request, Seconds, ExitCode -AutoSize

    $Passed = (
        $SlowProcess.ExitCode -eq 0 -and
        $FastExitCode -eq 0 -and
        $FastStopwatch.Elapsed.TotalSeconds -lt $FastLimitSeconds
    )

    if ($Passed) {
        Write-Host (
            "PASS: the blocking request transformer did not stall the " +
            "unrelated request."
        ) -ForegroundColor Green
        $ExitCode = 0
    }
    else {
        Write-Host (
            "FAIL: the unrelated request took {0:N3}s (limit: {1:N3}s)." -f
            $FastStopwatch.Elapsed.TotalSeconds,
            $FastLimitSeconds
        ) -ForegroundColor Red
    }
}
catch {
    Write-Host "BENCHMARK ERROR: $_" -ForegroundColor Red
    Write-ProcessLogs
}
finally {
    foreach ($Process in @($SlowProcess, $ProxyProcess, $OriginProcess)) {
        Stop-ProcessTree -Process $Process
    }

    foreach ($Name in $ProxyVariables) {
        [Environment]::SetEnvironmentVariable(
            $Name,
            $PreviousProxyEnvironment[$Name],
            "Process"
        )
    }
    $env:BENCH_REQUEST_STREAM_MARKER = $PreviousMarker
    $env:BENCH_REQUEST_STREAM_DELAY = $PreviousDelay

    $ResolvedTempDirectory = [IO.Path]::GetFullPath($TempDirectory)
    if ($ResolvedTempDirectory.StartsWith($TempRoot)) {
        Remove-Item -LiteralPath $ResolvedTempDirectory -Recurse -Force
    }
}

exit $ExitCode
