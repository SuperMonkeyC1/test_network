import socket
import subprocess
import datetime
import sys
import pytz
import os
import time
import yaml
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed


# =====================================================
# 基础工具
# =====================================================

def load_config():
    """读取 exe 或脚本同目录下的 config.yaml"""
    base_dir = (
        os.path.dirname(sys.executable)
        if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__))
    )
    path = os.path.join(base_dir, "config.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def now_str(tz_name):
    tz = pytz.timezone(tz_name)
    return datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


def expand_network(cidr):
    net = ipaddress.ip_network(cidr, strict=False)
    return [str(ip) for ip in net.hosts()]


def show_progress(current, total):
    percent = (current / total) * 100
    bar_len = 30
    filled = int(bar_len * current // total)
    bar = "█" * filled + "-" * (bar_len - filled)
    print(f"\r进度 [{bar}] {percent:5.1f}%", end="", flush=True)


def get_network_log(log_dir, cidr):
    safe = cidr.replace("/", "_")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, f"net_{safe}.log")


# =====================================================
# 启动前预检查
# =====================================================

def precheck_networks(networks, ports, rate_limit, max_hosts, estimate):
    total_hosts = 0

    for cidr in networks:
        count = len(list(ipaddress.ip_network(cidr, strict=False).hosts()))
        if count > max_hosts:
            raise RuntimeError(
                f"网段 {cidr} 主机数 {count} 超过限制 {max_hosts}，已拒绝扫描"
            )
        total_hosts += count

    if estimate:
        total_tasks = total_hosts * len(ports)
        est_time = total_tasks * rate_limit
        print("\n====== 扫描预估 ======")
        print(f"目标 IP 数量: {total_hosts}")
        print(f"探测端口数: {len(ports)}")
        print(f"总连接次数: {total_tasks}")
        print(f"预计耗时:   {est_time:.1f}s (~{est_time / 60:.1f}min)")
        print("=====================\n")


# =====================================================
# Ping 模块（多线程）
# =====================================================

def ping_once(ip, timeout):
    cmd = ["ping", "-n", "1", "-w", str(timeout), ip]
    start = time.time()
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if r.returncode == 0:
        return True, (time.time() - start) * 1000
    return False, None


def ping_worker(ip, cfg):
    for _ in range(cfg["retry"] + 1):
        ok, cost = ping_once(ip, cfg["timeout"])
        time.sleep(cfg["rate_limit"])
        if ok:
            return ip, cost
    return None


def ping_scan_network(cidr, cfg, log_dir, timezone):
    hosts = expand_network(cidr)
    alive = []
    log_file = get_network_log(log_dir, cidr)

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n===== PING SCAN {cidr} =====\n")

        with ThreadPoolExecutor(max_workers=cfg["threads"]) as pool:
            futures = [pool.submit(ping_worker, ip, cfg) for ip in hosts]

            done = 0
            for fu in as_completed(futures):
                done += 1
                show_progress(done, len(hosts))

                res = fu.result()
                if res:
                    ip, cost = res
                    alive.append(ip)
                    f.write(f"[{now_str(timezone)}] PING {ip} {cost:.1f} ms\n")

        f.write(f"===== END PING {cidr} =====\n")
        print()

    return alive


# =====================================================
# TCP 模块
# =====================================================

def tcp_connect_once(host, port, timeout):
    start = time.time()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return True, (time.time() - start) * 1000
    except Exception:
        return False, None
    finally:
        sock.close()


def tcp_with_retry(host, port, cfg):
    for _ in range(cfg["retry"] + 1):
        ok, cost = tcp_connect_once(host, port, cfg["timeout"])
        time.sleep(cfg["rate_limit"])
        if ok:
            return True, cost
    return False, None


def build_port_list(cfg):
    mode = cfg.get("mode", "list")

    if mode == "list":
        return cfg.get("ports", [])

    if mode == "range":
        r = cfg.get("port_range", {})
        return list(range(int(r["start"]), int(r["end"]) + 1))

    if mode == "full":
        cfg["retry"] = 0
        cfg["rate_limit"] = max(cfg["rate_limit"], 0.1)
        return list(range(1, 65536))

    raise ValueError(f"未知 tcp_scan.mode: {mode}")


# =====================================================
# 主流程
# =====================================================

def main():
    cfg = load_config()

    log_dir = cfg["target"].get("log_dir", "./logs")
    timezone = cfg["target"].get("timezone", "Asia/Bangkok")

    ping_cfg = cfg["ping_scan"]
    tcp_cfg = cfg["tcp_scan"]
    scan_cfg = cfg.get("scan", {})

    ports = build_port_list(tcp_cfg)
    port_stats = {p: {"total": 0, "success": 0} for p in ports}

    precheck_networks(
        ping_cfg["networks"],
        ports,
        tcp_cfg["rate_limit"],
        scan_cfg.get("max_hosts", 1024),
        scan_cfg.get("estimate_time", True),
    )

    alive_ips = []

    # ---- Ping 扫描 ----
    for cidr in ping_cfg["networks"]:
        print(f"\n开始 Ping 扫描网段: {cidr}")
        alive = ping_scan_network(cidr, ping_cfg, log_dir, timezone)
        alive_ips.extend(alive)

    print(f"\n发现存活主机: {len(alive_ips)}")

    # ---- TCP 扫描 ----
    if tcp_cfg["enable"]:
        print("\n开始 TCP 探测")
        for ip in alive_ips:
            for port in ports:
                port_stats[port]["total"] += 1
                ok, cost = tcp_with_retry(ip, port, tcp_cfg)
                if ok:
                    port_stats[port]["success"] += 1
                    print(f"[TCP OK] {ip}:{port} {cost:.1f} ms")

    # ---- 汇总 ----
    summary = os.path.join(log_dir, "summary.log")
    with open(summary, "a", encoding="utf-8") as f:
        f.write(f"\n===== SUMMARY {now_str(timezone)} =====\n")
        f.write(f"ALIVE HOSTS: {len(alive_ips)}\n")
        for p, s in port_stats.items():
            rate = (s["success"] / s["total"] * 100) if s["total"] else 0
            f.write(f"PORT {p}: {s['success']}/{s['total']} ({rate:.1f}%)\n")

    print("\nNetProbe 扫描完成")


if __name__ == "__main__":
    main()
