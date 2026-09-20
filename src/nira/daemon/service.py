from __future__ import annotations

import sys
from pathlib import Path

SYSTEMD_TEMPLATE = """\
[Unit]
Description=Nira Gateway Daemon
After=network.target

[Service]
Type=simple
ExecStart={python} -m nira.daemon
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""

LAUNCHD_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nira.gateway</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>-m</string>
        <string>nira.daemon</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <!-- `nira gateway logs` tells users to read this file, so launchd has to
         actually write it. -->
    <key>StandardOutPath</key>
    <string>{log_dir}/com.nira.gateway.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/com.nira.gateway.err.log</string>
</dict>
</plist>
"""


def generate_systemd_service(output: Path | None = None) -> str:
    content = SYSTEMD_TEMPLATE.format(python=sys.executable)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content)
    return content


def generate_launchd_plist(output: Path | None = None) -> str:
    log_dir = Path.home() / "Library" / "Logs"
    content = LAUNCHD_TEMPLATE.format(python=sys.executable, log_dir=log_dir)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content)
    return content
