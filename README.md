# Campus Login for Linux

苏州大学 Linux 校园网自动联网工具。通过 NetworkManager 连接或重连 SUDA_WIFI，检测到学校认证页时使用已保存的账号登录。systemd 服务开机运行，SSH 断开后仍可继续检查。

## 环境要求

Linux、systemd、运行中的 NetworkManager、可用的 Wi-Fi 网卡、Python 3.8+、nmcli、curl 和 sudo 权限。保持 Wi-Fi 开启，并确保服务器在 SUDA_WIFI 信号范围内。

## 安装

```sh
tar -xzf campus-login-linux.tar.gz
cd campus-login-linux
sudo ./install.sh
```

首次安装时输入学号、密码、运营商和检查间隔。支持校园网、中国移动、中国联通和中国电信。密码输入时隐藏。安装后服务会立即检查，并在开机时启动。若当前 SSH 恰好走 Wi-Fi，切换到 SUDA_WIFI 时 SSH 可能断开。

## 修改账号和设置

```sh
sudo campus-login configure
```

账号不变时，密码留空可保留原密码。账号改变后需重新输入密码。保存后，正在运行的服务会重启并按新配置立即检查。检查间隔可设为 1 至 1440 分钟。收到网关明确拒绝后，后台至少等待 15 分钟再试，修改配置后可立即使用新账号。

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `campus-login status` | 查看服务状态和最近的检查结果，时间为 UTC |
| `campus-login probe` | 只读检查当前连接与认证状态 |
| `sudo campus-login check` | 立即检查并尝试恢复联网 |
| `sudo campus-login logs` | 查看最近 50 条服务日志 |
| `sudo systemctl stop campus-login` | 停止自动检查 |
| `sudo systemctl start campus-login` | 启动自动检查 |

程序通过当前 Wi-Fi 的 IPv4 地址发出检查和认证请求，并校验认证页回报的地址。密码保存在 root 专用目录下的 `/etc/campus-login/config.json`，文件权限为 `600`。源码、安装包和状态日志均不包含保存的密码。学校网关使用 HTTP 完成认证。

## 卸载

```sh
sudo campus-login uninstall
```

可选择同时清除本机保存的校园网账号和密码。
