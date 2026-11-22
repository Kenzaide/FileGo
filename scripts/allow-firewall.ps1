# Let other devices on a PRIVATE network reach FileGo (TCP port 5000). Run as administrator.
param([int]$Port = 5000)
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'This needs administrator rights. Use allow-firewall.bat, which asks for them.' -ForegroundColor Red
    exit 1
}
$name = "FileGo (TCP $Port)"
if (Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue) { Remove-NetFirewallRule -DisplayName $name }
New-NetFirewallRule -DisplayName $name -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Private | Out-Null
Write-Host "Rule added: devices on a Private network can reach port $Port." -ForegroundColor Green
Write-Host ''
Write-Host 'Your current network connections (the hotspot must say Private):'
Get-NetConnectionProfile | Format-Table Name, InterfaceAlias, NetworkCategory -AutoSize
Write-Host 'To switch a connection to Private, run (replace the name):'
Write-Host '  Set-NetConnectionProfile -Name "NetworkName" -NetworkCategory Private'
