#!/bin/sh
set -eu
cd "$(dirname "$0")"
[ "$(id -u)" -eq 0 ] || { echo "请使用 sudo ./install.sh" >&2; exit 1; }
for dependency in python3 curl nmcli systemctl; do
    command -v "$dependency" >/dev/null || { echo "缺少 $dependency" >&2; exit 1; }
done
systemctl is-active --quiet NetworkManager.service || { echo "请先启动 NetworkManager。" >&2; exit 1; }
if [ ! -f /etc/campus-login/config.json ]; then
    python3 ./campus_login.py configure
fi
install -d -m 0755 /usr/local/lib/campus-login /usr/local/bin
install -m 0755 campus_login.py /usr/local/lib/campus-login/campus_login.py
install -m 0644 portal.py /usr/local/lib/campus-login/portal.py
install -m 0755 uninstall.sh /usr/local/lib/campus-login/uninstall.sh
ln -sfn /usr/local/lib/campus-login/campus_login.py /usr/local/bin/campus-login
install -m 0644 campus-login.service /etc/systemd/system/campus-login.service
systemctl daemon-reload
systemctl enable campus-login.service
systemctl restart campus-login.service
