#!/usr/bin/env python3
"""Reconnect Linux hosts to SUDA_WIFI and authenticate when required."""
import argparse
import contextlib
import fcntl
import getpass
import http.client
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

import portal


SSID = "SUDA_WIFI"
UNIT = "campus-login.service"
CONFIG = Path("/etc/campus-login/config.json")
STATUS = Path("/run/campus-login/status.json")
LOCK = STATUS.with_name("check.lock")
SERVICES = {
    "campus": ("校园网", ""), "mobile": ("中国移动", "@zgyd"),
    "unicom": ("中国联通", "@cucc"), "telecom": ("中国电信", "@ctc"),
}


def command(*args, timeout=12):
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "LC_ALL": "C"}, check=False,
    )


def nmcli(*args, wait=8):
    result = command("nmcli", "--wait", str(wait), "--terse", "--escape", "no", *args, timeout=wait + 5)
    return result.stdout.strip() if result.returncode == 0 else None


def wifi_device():
    devices = nmcli("-fields", "DEVICE,TYPE,STATE", "device", "status") or ""
    for row in devices.splitlines():
        name, kind, state = row.split(":", 2)
        if kind == "wifi" and not state.startswith(("unmanaged", "unavailable")):
            yield name


def current_ssid(device):
    networks = nmcli("-fields", "IN-USE,SSID", "device", "wifi", "list",
                     "ifname", device, "--rescan", "no") or ""
    return next((row[2:] for row in networks.splitlines() if row.startswith("*:")), None)


def ipv4(device):
    addresses = nmcli("-get-values", "IP4.ADDRESS", "device", "show", device) or ""
    for line in addresses.splitlines():
        try:
            address = ipaddress.IPv4Interface(line).ip
        except ValueError:
            continue
        if not (address.is_link_local or address.is_loopback or address.is_unspecified):
            return str(address)
    return None


def prepare_wifi(connect):
    devices = list(wifi_device())
    if not devices:
        return None, None, "未找到可用的 Wi-Fi 网卡，请确认 Wi-Fi 已开启且由 NetworkManager 管理。"
    device = next((name for name in devices if current_ssid(name) == SSID), None)
    if device is None:
        if not connect:
            return None, None, "未连接 SUDA_WIFI。"
        for candidate in devices:
            if nmcli("device", "wifi", "connect", SSID, "ifname", candidate, wait=25) is not None:
                device = candidate
                break
        if device is None:
            return None, None, "未能连接 SUDA_WIFI，请检查信号和 NetworkManager 状态。"
    deadline = time.monotonic() + (12 if connect else 0)
    while True:
        address = ipv4(device)
        if address and current_ssid(device) == SSID:
            return device, address, None
        if time.monotonic() >= deadline:
            return device, None, "SUDA_WIFI 尚未获得有效的 IPv4 地址。"
        time.sleep(1)


def atomic_json(path, value, mode):
    path.parent.mkdir(mode=0o700 if path == CONFIG else 0o755, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".campus-login-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            os.fchmod(output.fileno(), mode)
            json.dump(value, output, ensure_ascii=False)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_config():
    with CONFIG.open(encoding="utf-8") as source:
        permissions = os.fstat(source.fileno())
        if permissions.st_uid != 0 or permissions.st_mode & 0o077:
            raise ValueError("配置必须由 root 持有且只有 root 可以读取。")
        config = json.load(source)
    if (not isinstance(config, dict) or not isinstance(config.get("username"), str)
            or not config["username"] or not isinstance(config.get("password"), str)
            or not config["password"] or not isinstance(config.get("service"), str)
            or config["service"] not in SERVICES
            or type(config.get("minutes")) is not int or not 1 <= config["minutes"] <= 1440):
        raise ValueError("配置格式无效，请运行 sudo campus-login configure。")
    return config


@contextlib.contextmanager
def exclusive_check():
    LOCK.parent.mkdir(mode=0o755, exist_ok=True)
    LOCK.parent.chmod(0o755)
    with LOCK.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def check(config=None):
    device, address, error = prepare_wifi(connect=config is not None)
    if error:
        result = {"outcome": "wifi_unavailable", "detail": error}
    else:
        credentials = {"password": ""} if config is None else {
            "username": config["username"], "password": config["password"],
            "suffix": SERVICES[config["service"]][1],
        }
        outcome = portal.run(credentials, address)
        result = {"outcome": outcome} if isinstance(outcome, str) else outcome
    return {**result, "device": device, "ipv4": address,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def check_and_record(config):
    with exclusive_check():
        try:
            result = check(config)
        except (OSError, ValueError, http.client.HTTPException, subprocess.TimeoutExpired):
            result = {"outcome": "network_error", "detail": "检查网络或认证网关时出错。",
                      "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        atomic_json(STATUS, result, 0o644)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result["outcome"]


def configure():
    if not sys.stdin.isatty():
        print("请在交互式终端运行配置命令。", file=sys.stderr)
        return 1
    previous = load_config() if CONFIG.exists() else {}
    username = input("校园网账号（留空保留原值）：").strip() or previous.get("username")
    password = getpass.getpass("校园网密码（账号不变时留空保留）：")
    if not password and username == previous.get("username"):
        password = previous.get("password")
    if not username or not password:
        raise ValueError("请填写账号和密码。")
    for number, (_, (label, _)) in enumerate(SERVICES.items(), 1):
        print(f"{number}. {label}")
    choice = input("运营商编号（留空保留原值，初次配置默认 1）：").strip()
    if choice and choice not in ("1", "2", "3", "4"):
        raise ValueError("请选择 1 至 4。")
    service = list(SERVICES)[int(choice) - 1] if choice else previous.get("service", "campus")
    value = input(f"检查间隔，分钟 [{previous.get('minutes', 5)}]：").strip()
    if value and (not value.isascii() or not value.isdecimal() or len(value) > 4):
        raise ValueError("检查间隔须为 1 至 1440 分钟。")
    minutes = int(value) if value else previous.get("minutes", 5)
    if not 1 <= minutes <= 1440:
        raise ValueError("检查间隔须为 1 至 1440 分钟。")
    atomic_json(CONFIG, {"username": username, "password": password, "service": service,
                         "minutes": minutes}, 0o600)
    if command("systemctl", "is-active", "--quiet", UNIT).returncode == 0:
        if command("systemctl", "restart", UNIT, timeout=35).returncode:
            print("配置已保存，但服务重启失败，请检查 systemctl status campus-login。", file=sys.stderr)
            return 1
    print("配置已保存。")
    return 0


def daemon():
    while True:
        config = load_config()
        try:
            outcome = check_and_record(config)
        except BlockingIOError:
            outcome = "busy"
        delay = config["minutes"] * 60
        time.sleep(max(delay, 900) if outcome == "authentication_failed" else delay)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("configure", "check", "probe", "status", "logs", "daemon", "uninstall"))
    action = parser.parse_args().action
    if action in ("configure", "check", "daemon", "uninstall") and os.geteuid() != 0:
        parser.error(f"请用 sudo 执行 campus-login {action}。")
    try:
        if action == "configure":
            return configure()
        if action == "check":
            return 0 if check_and_record(load_config()) in ("online", "restored") else 1
        if action == "probe":
            result = check()
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["outcome"] == "online" else 1
        if action == "status":
            print("服务状态：" + (command("systemctl", "is-active", UNIT).stdout.strip() or "未知"))
            print(STATUS.read_text(encoding="utf-8").strip() if STATUS.exists() else "还没有联网检查记录。")
            return 0
        if action == "logs":
            os.execvp("journalctl", ("journalctl", "-u", UNIT, "-n", "50", "--no-pager"))
        if action == "uninstall":
            os.execv("/usr/local/lib/campus-login/uninstall.sh", ("uninstall.sh",))
        daemon()
    except BlockingIOError:
        print("已有一次联网检查正在运行。", file=sys.stderr)
    except FileNotFoundError:
        print("缺少配置或依赖。初次使用请先运行 sudo campus-login configure。", file=sys.stderr)
    except (EOFError, KeyboardInterrupt):
        print("已取消。", file=sys.stderr)
    except ValueError as error:
        print(str(error) if action == "configure" and not isinstance(error, json.JSONDecodeError)
              else "配置无效，请运行 sudo campus-login configure。", file=sys.stderr)
    except (OSError, http.client.HTTPException, subprocess.TimeoutExpired):
        print("操作失败，请检查系统服务、文件权限和网络。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
