#!/bin/sh
set -eu
[ "$(id -u)" -eq 0 ] || { echo "请使用 sudo campus-login uninstall" >&2; exit 1; }
printf '同时删除账号和密码？[y/N] '
read -r answer
systemctl disable --now campus-login.service
rm -f /etc/systemd/system/campus-login.service /usr/local/bin/campus-login
rm -f /usr/local/lib/campus-login/campus_login.py /usr/local/lib/campus-login/portal.py /usr/local/lib/campus-login/uninstall.sh
rm -f /run/campus-login/status.json /run/campus-login/check.lock
rmdir /run/campus-login 2>/dev/null || true
if [ "$answer" = y ] || [ "$answer" = Y ]; then
    rm -f /etc/campus-login/config.json
    rmdir /etc/campus-login 2>/dev/null || true
fi
systemctl daemon-reload
