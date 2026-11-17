param([int]$ComfyPort = 8188)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$result = [ordered]@{ hostname = $env:COMPUTERNAME; ssh_service = $null; wsl = @(); gpu = @(); comfy = $null }
try { $result.ssh_service = (Get-Service sshd).Status.ToString() } catch { $result.ssh_service = 'not_found' }
try { $result.wsl = @(& wsl.exe --list --verbose 2>&1 | ForEach-Object { "$_" -replace "`0", '' }) } catch { $result.wsl = @('unavailable') }
try { $result.gpu = @(Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, AdapterRAM) } catch { $result.gpu = @() }
try {
    $stats = Invoke-RestMethod -Uri "http://127.0.0.1:$ComfyPort/system_stats" -TimeoutSec 5
    $info = Invoke-RestMethod -Uri "http://127.0.0.1:$ComfyPort/object_info" -TimeoutSec 15
    $models = [ordered]@{}
    foreach ($node in @('UNETLoader', 'CLIPLoader', 'DualCLIPLoader', 'VAELoader', 'LoraLoaderModelOnly', 'CheckpointLoaderSimple')) {
        if ($info.PSObject.Properties.Name -contains $node) { $models[$node] = $info.$node.input.required }
    }
    $result.comfy = @{ reachable = $true; port = $ComfyPort; system = $stats; node_names = @($info.PSObject.Properties.Name); loaders = $models }
} catch { $result.comfy = @{ reachable = $false; port = $ComfyPort; reason = 'local_api_unavailable' } }
$result | ConvertTo-Json -Depth 18 -Compress
