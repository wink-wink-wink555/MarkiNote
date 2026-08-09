[CmdletBinding()]
param(
    [Parameter()]
    [string]$Source = "lib",

    [Parameter()]
    [string]$BaseUrl = "http://127.0.0.1:8080",

    [Parameter()]
    [string]$AccessToken = $env:MARKINOTE_ACCESS_TOKEN,

    [Parameter()]
    [switch]$SkipExisting,

    [Parameter()]
    [ValidateRange(110, 5000)]
    [int]$RequestDelayMilliseconds = 125
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$resolvedSource = (Resolve-Path -LiteralPath $Source).Path
$supportedExtensions = @(".md", ".markdown", ".txt")
$files = @(
    Get-ChildItem -LiteralPath $resolvedSource -Recurse -File |
        Where-Object { $supportedExtensions -contains $_.Extension.ToLowerInvariant() } |
        Sort-Object FullName
)

if ($files.Count -eq 0) {
    Write-Output "No supported documents were found under $resolvedSource."
    exit 0
}

Add-Type -AssemblyName System.Net.Http
$client = [System.Net.Http.HttpClient]::new()
$client.Timeout = [TimeSpan]::FromMinutes(2)
$apiRoot = $BaseUrl.TrimEnd("/")
$strictUtf8 = [Text.UTF8Encoding]::new($false, $true)
if ($AccessToken) {
    $client.DefaultRequestHeaders.Authorization =
        [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $AccessToken)
}

function Invoke-JsonPost {
    param(
        [Parameter(Mandatory)]
        [string]$Path,

        [Parameter(Mandatory)]
        [hashtable]$Body,

        [Parameter(Mandatory)]
        [string]$Description
    )

    $json = $Body | ConvertTo-Json -Compress
    for ($attempt = 1; $attempt -le 6; $attempt += 1) {
        Start-Sleep -Milliseconds $RequestDelayMilliseconds
        $content = [System.Net.Http.StringContent]::new($json, [Text.Encoding]::UTF8, "application/json")
        try {
            $response = $client.PostAsync("$apiRoot$Path", $content).GetAwaiter().GetResult()
            try {
                if ([int]$response.StatusCode -eq 429) {
                    Start-Sleep -Milliseconds (750 * $attempt)
                    continue
                }
                if (-not $response.IsSuccessStatusCode) {
                    $responseBody = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
                    throw "$Description failed ($([int]$response.StatusCode)): $responseBody"
                }
                return
            } finally {
                $response.Dispose()
            }
        } finally {
            $content.Dispose()
        }
    }
    throw "$Description remained rate-limited after six attempts."
}

try {
    $candidates = foreach ($file in $files) {
        $relativePath = $file.FullName.Substring($resolvedSource.Length + 1).Replace("\", "/")
        try {
            $text = $strictUtf8.GetString([System.IO.File]::ReadAllBytes($file.FullName))
        } catch {
            throw "'$relativePath' is not valid UTF-8 and cannot be imported as a MarkiNote text document."
        }
        [pscustomobject]@{
            File = $file
            RelativePath = $relativePath
            ParentPath = [System.IO.Path]::GetDirectoryName($relativePath).Replace("\", "/")
            Content = $text
        }
    }

    $existing = [System.Collections.Generic.List[string]]::new()
    foreach ($candidate in $candidates) {
        $encodedPath = [Uri]::EscapeDataString($candidate.RelativePath)
        $response = $null
        for ($attempt = 1; $attempt -le 6; $attempt += 1) {
            Start-Sleep -Milliseconds $RequestDelayMilliseconds
            $response = $client.GetAsync("$apiRoot/api/v1/documents/content?path=$encodedPath").GetAwaiter().GetResult()
            if ([int]$response.StatusCode -ne 429) {
                break
            }
            $response.Dispose()
            $response = $null
            Start-Sleep -Milliseconds (750 * $attempt)
        }
        if ($null -eq $response) {
            throw "Preflight remained rate-limited for '$($candidate.RelativePath)' after six attempts."
        }
        try {
            if ($response.IsSuccessStatusCode) {
                $existing.Add($candidate.RelativePath)
            } elseif ([int]$response.StatusCode -ne 404) {
                $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
                throw "Preflight failed for '$($candidate.RelativePath)' ($([int]$response.StatusCode)): $body"
            }
        } finally {
            $response.Dispose()
        }
    }

    if ($existing.Count -gt 0 -and -not $SkipExisting) {
        $preview = ($existing | Select-Object -First 8) -join [Environment]::NewLine
        throw "Import stopped before writing because $($existing.Count) destination path(s) already exist. Re-run with -SkipExisting to import only missing documents.$([Environment]::NewLine)$preview"
    }

    $pending = if ($SkipExisting) {
        @($candidates | Where-Object { $existing -notcontains $_.RelativePath })
    } else {
        @($candidates)
    }

    $folderResponse = $client.GetAsync("$apiRoot/api/v1/documents/folders").GetAwaiter().GetResult()
    try {
        if (-not $folderResponse.IsSuccessStatusCode) {
            $body = $folderResponse.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            throw "Unable to inspect destination folders ($([int]$folderResponse.StatusCode)): $body"
        }
        $folderPayload = $folderResponse.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
    } finally {
        $folderResponse.Dispose()
    }

    $knownFolders = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $knownFolders.Add("") | Out-Null
    foreach ($folder in $folderPayload.folders) {
        $knownFolders.Add([string]$folder.path) | Out-Null
    }
    $requiredFolders = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($candidate in $pending) {
        $parts = @($candidate.ParentPath -split "/" | Where-Object { $_ })
        for ($index = 1; $index -le $parts.Count; $index += 1) {
            $requiredFolders.Add(($parts[0..($index - 1)] -join "/")) | Out-Null
        }
    }
    $orderedFolders = @(
        $requiredFolders |
            Sort-Object @{ Expression = { ($_ -split "/").Count } }, @{ Expression = { $_ } }
    )
    foreach ($folderPath in $orderedFolders) {
        if ($knownFolders.Contains($folderPath)) {
            continue
        }
        $separator = $folderPath.LastIndexOf("/")
        $parentPath = if ($separator -ge 0) { $folderPath.Substring(0, $separator) } else { "" }
        $folderName = if ($separator -ge 0) { $folderPath.Substring($separator + 1) } else { $folderPath }
        Invoke-JsonPost -Path "/api/v1/documents/folders" `
            -Body @{ path = $parentPath; name = $folderName } `
            -Description "Creating folder '$folderPath'"
        $knownFolders.Add($folderPath) | Out-Null
    }

    $completed = 0
    foreach ($candidate in $pending) {
        Invoke-JsonPost -Path "/api/v1/documents/files" `
            -Body @{ path = $candidate.ParentPath; name = $candidate.File.Name; content = $candidate.Content } `
            -Description "Importing '$($candidate.RelativePath)'"

        $completed += 1
        Write-Progress -Activity "Importing MarkiNote library" -Status $candidate.RelativePath `
            -PercentComplete (($completed / [Math]::Max(1, $pending.Count)) * 100)
    }

    Write-Progress -Activity "Importing MarkiNote library" -Completed
    Write-Output "Imported $completed document(s); skipped $($existing.Count) existing path(s)."
} finally {
    $client.Dispose()
}
