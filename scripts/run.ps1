# run.ps1 -Exe <victory.exe> -Game <your own copy's executable> [-Console series-s] [-MipDrop 3]
# Starts the title on Windows with the settings measured in RESULTS.md (the same values as settings.env).
# NOT TESTED ON WINDOWS BY US: every measurement of this repository was made under Linux/Wine.
# A setting already present in your environment is kept (set it before calling to override a value).
# Run it from a normal PowerShell window, not as administrator.
param(
    [Parameter(Mandatory)][string]$Exe,
    [Parameter(Mandatory)][string]$Game,
    [ValidateSet('series-s', 'series-x')][string]$Console = 'series-s',
    [ValidateRange(0, 3)][int]$MipDrop = 3,
    [string]$Log = 'warn'
)
$settings = [ordered]@{
    # Memory placement: the three settings behind the step from about 280 to about 100 ms per frame on a 6 GB card.
    # On a card with 8 GB or more, try -MipDrop 2 (sharper textures) first.
    VICTORY_CARD_BUFFERS_MB     = '1024'
    VICTORY_CARD_WINDOWS_MB     = '768'
    VICTORY_TEXTURE_MIP_DROP    = "$MipDrop"
    VICTORY_LEVELS_ON_DEMAND    = '0'
    VICTORY_CARD_BUFFERS_MIN_KB = '64'
    # The fork's stand-in for ray-traced light (a skip: lighting is approximate).
    VICTORY_AMBIENT             = '0.8'
    VICTORY_AMBIENT_AIR         = '1.5'
    # The fork's launcher settings (speed).
    VICTORY_TEXTURE_NO_WAIT     = '1'
    VICTORY_RELAY               = '2'
    VICTORY_RELAY_COPY          = '1'
    VICTORY_WIDE_BACK           = '1'
    VICTORY_CARD_REHASH_RUNS    = '1'
    VICTORY_JOIN_COPIES         = '1'
    VICTORY_INDIRECT_WINDOW     = '1'
    VICTORY_INDIRECT_BATCH      = '2'
    VICTORY_CARD_STEPS          = '2'
    VICTORY_MAP_THREADS         = '1'
    VICTORY_CARD_AWAKE          = '1'
    VICTORY_SHOW_AFTER          = '1'
    VICTORY_UPLOAD_AHEAD        = '1'
    VICTORY_THIN                = '1'
    VICTORY_JOIN_PARTS          = '8'
    VICTORY_LOG                 = $Log
}
if (-not (Test-Path $Exe))  { Write-Host "No $Exe. Build it first (README.md, Windows)."; exit 2 }
if (-not (Test-Path $Game)) { Write-Host "No $Game. Pass the executable of your own copy of the title."; exit 2 }
foreach ($k in $settings.Keys) {
    if (-not (Test-Path "Env:$k")) { Set-Item "Env:$k" $settings[$k] }
}
$Exe = (Resolve-Path $Exe).Path
$Game = (Resolve-Path $Game).Path
Push-Location (Split-Path $Exe)
try { & $Exe run $Game --execute --console $Console } finally { Pop-Location }
exit $LASTEXITCODE
