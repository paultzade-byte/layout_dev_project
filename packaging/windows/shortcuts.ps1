# Ярлики оптимізатора і статистики: робочий стіл + меню «Пуск» (тека ukr-layout).
# Запускається з «Створити ярлики.bat» / «Видалити ярлики.bat» поруч з exe.
# Ярлик веде на exe в цій теці: перенесли теку — запустіть створення ще раз.
param([switch]$Remove)

$dir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$desk  = [Environment]::GetFolderPath('Desktop')
$menu  = Join-Path ([Environment]::GetFolderPath('Programs')) 'ukr-layout'
$apps  = @(
    @{ Name = 'Оптимізатор розкладки'; Exe = 'ukr-layout.exe'; Note = 'Оптимізатор української розкладки' },
    @{ Name = 'Статистика текстів';    Exe = 'ukr-stats.exe';  Note = 'Частоти літер і n-грам ваших текстів' }
)

if ($Remove) {
    foreach ($a in $apps) { Remove-Item -LiteralPath (Join-Path $desk "$($a.Name).lnk") -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $menu -Recurse -ErrorAction SilentlyContinue
    Write-Host 'Ярлики видалено.'
    exit 0
}

New-Item -ItemType Directory -Force -Path $menu | Out-Null
$shell = New-Object -ComObject WScript.Shell
foreach ($a in $apps) {
    $exe = Join-Path $dir $a.Exe
    if (-not (Test-Path -LiteralPath $exe)) { Write-Host "Немає $exe — пропускаю."; continue }
    foreach ($where in @($desk, $menu)) {
        $lnk = $shell.CreateShortcut((Join-Path $where "$($a.Name).lnk"))
        $lnk.TargetPath       = $exe
        $lnk.WorkingDirectory = $dir
        $lnk.IconLocation     = "$exe,0"
        $lnk.Description      = $a.Note
        $lnk.Save()
    }
}
Write-Host 'Готово: ярлики на робочому столі і в меню «Пуск» -> ukr-layout.'
