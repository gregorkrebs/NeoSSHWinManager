"""
filebrowser – the standalone SFTP/FTP file manager window.

Layers, bottom-up:
    model      pure data + decision logic (entries, paths, conflicts, sync diff)
    commands   remote shell command builders (Linux sh / Windows PowerShell)
    fs         file systems: local disk, SFTP (paramiko), FTP/FTPS (ftplib)
    transfers  transfer queue with parallel slots, rate limits, resume, log
    settings   per-user browser settings (stored encrypted in the app DB)
    ui         Qt widgets: window, panes, trees, dialogs

Nothing below `ui` imports Qt widgets, so the logic stays unit-testable.
"""
