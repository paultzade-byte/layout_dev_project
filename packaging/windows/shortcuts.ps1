# Ярлики оптимізатора і статистики: робочий стіл + меню «Пуск» (тека ukr-layout).
# Запускається з «Створити ярлики.bat» / «Видалити ярлики.bat» поруч з exe.
# Ярлик веде на exe в цій теці: перенесли теку — запустіть створення ще раз.
#
# Не WScript.Shell: він працює в ANSI-кодуванні, і на некириличному Windows
# кирилиця в назві ярлика чи в шляху до теки («Завантаження») ламає його.
# Тут — Unicode-інтерфейс оболонки IShellLinkW.
param([switch]$Remove)

$dir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$desk = [Environment]::GetFolderPath('Desktop')
$menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'ukr-layout'
$apps = @(
    @{ Name = 'Оптимізатор розкладки'; Exe = 'ukr-layout.exe'; Note = 'Оптимізатор української розкладки' },
    @{ Name = 'Статистика текстів';    Exe = 'ukr-stats.exe';  Note = 'Частоти літер і n-грам ваших текстів' }
)

if ($Remove) {
    foreach ($a in $apps) { Remove-Item -LiteralPath (Join-Path $desk "$($a.Name).lnk") -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $menu -Recurse -ErrorAction SilentlyContinue
    Write-Host 'Ярлики видалено.'
    exit 0
}

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;
namespace UkrLayout {
    [ComImport, Guid("00021401-0000-0000-C000-000000000046")] class ShellLink {}
    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("000214F9-0000-0000-C000-000000000046")]
    interface IShellLinkW {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder f, int cch, IntPtr pfd, uint flags);
        void GetIDList(out IntPtr ppidl);
        void SetIDList(IntPtr pidl);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int cch);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string s);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int cch);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string s);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int cch);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string s);
        void GetHotkey(out short key);
        void SetHotkey(short key);
        void GetShowCmd(out int cmd);
        void SetShowCmd(int cmd);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int cch, out int i);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string s, int i);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string s, uint reserved);
        void Resolve(IntPtr hwnd, uint flags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string s);
    }
    public static class Lnk {
        public static void Save(string lnk, string target, string workdir, string note) {
            var link = (IShellLinkW)new ShellLink();
            link.SetPath(target);
            link.SetWorkingDirectory(workdir);
            link.SetIconLocation(target, 0);
            link.SetDescription(note);
            ((IPersistFile)link).Save(lnk, true);
        }
    }
}
"@

New-Item -ItemType Directory -Force -Path $menu | Out-Null
foreach ($a in $apps) {
    $exe = Join-Path $dir $a.Exe
    if (-not (Test-Path -LiteralPath $exe)) { Write-Host "Немає $exe — пропускаю."; continue }
    foreach ($where in @($desk, $menu)) {
        [UkrLayout.Lnk]::Save((Join-Path $where "$($a.Name).lnk"), $exe, $dir, $a.Note)
    }
}
Write-Host 'Готово: ярлики на робочому столі і в меню «Пуск» -> ukr-layout.'
