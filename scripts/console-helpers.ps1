function Disable-QuickEdit {
    # A click inside a QuickEdit console starts a selection that blocks the next console write,
    # freezing the paper loop. Disable QuickEdit for this console window only.
    try {
        if (-not ('ForexConsole.Mode' -as [type])) {
            Add-Type -Namespace ForexConsole -Name Mode -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern IntPtr GetStdHandle(int handle);
[DllImport("kernel32.dll")] public static extern bool GetConsoleMode(IntPtr handle, out uint mode);
[DllImport("kernel32.dll")] public static extern bool SetConsoleMode(IntPtr handle, uint mode);
'@
        }
        $inputHandle = [ForexConsole.Mode]::GetStdHandle(-10)
        [uint32]$mode = 0
        if (-not [ForexConsole.Mode]::GetConsoleMode($inputHandle, [ref]$mode) -or
                -not [ForexConsole.Mode]::SetConsoleMode($inputHandle, [uint32](($mode -band 0xFFBF) -bor 0x80))) {
            Write-Warning 'Could not disable console QuickEdit; avoid clicking inside this window.'
        }
    } catch {
        Write-Warning 'Could not disable console QuickEdit; avoid clicking inside this window.'
    }
}
