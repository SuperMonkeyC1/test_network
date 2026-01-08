import socket
import datetime
import sys
import pytz
import os
import time
import yaml


def load_config():
    """读取 exe 或脚本同目录下的 config.yaml"""
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    config_path = os.path.join(base_dir, "config.yaml")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_time(tz_name):
    """获取指定时区时间"""
    tz = pytz.timezone(tz_name)
    return datetime.datetime.now(tz)


def tcp_connect_test(host, port, timeout):
    """
    TCP 端口连通性测试

    Args:
        host (str): 目标地址
        port (int): 端口号
        timeout (int): 超时时间（秒）

    Returns:
        tuple(bool, float | None, str):
            是否成功, 耗时(ms), 错误信息
    """
    start = time.time()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)

    try:
        sock.connect((host, port))
        elapsed = (time.time() - start) * 1000
        return True, elapsed, ""
    except Exception as e:
        return False, None, str(e)
    finally:
        sock.close()


def main():
    config = load_config()

    # ===== 通用目标配置 =====
    target_cfg = config.get("target", {})
    host = target_cfg.get("host")
    log_dir = target_cfg.get("log_dir", "./logs")
    timezone = target_cfg.get("timezone", "Asia/Bangkok")

    # ===== TCP 配置 =====
    tcp_cfg = config.get("tcp", {})
    if not tcp_cfg.get("enable", False):
        print("TCP 检测未启用（tcp.enable=false），程序退出")
        return

    port = int(tcp_cfg.get("port", 80))
    timeout = int(tcp_cfg.get("timeout", 3))
    interval = int(tcp_cfg.get("interval", 2))

    if not host:
        raise ValueError("target.host 未配置")

    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"tcp_{host}_{port}.log")

    def now_str():
        return get_time(timezone).strftime("%Y-%m-%d %H:%M:%S")

    # ===== 统计变量 =====
    total_count = 0
    success_count = 0
    fail_count = 0
    cost_list = []

    print(f"开始 TCP 检测：{host}:{port}")
    print(f"超时：{timeout}s，间隔：{interval}s")
    print(f"日志文件：{log_file}")
    print(f"时区：{timezone}")
    print("按 Ctrl+C 停止\n")

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("\n")
            f.write(f"===== START {now_str()} ({timezone}) =====\n")
            f.flush()

            while True:
                total_count += 1
                ok, cost, err = tcp_connect_test(host, port, timeout)

                if ok:
                    success_count += 1
                    cost_list.append(cost)
                    log_line = f"[{now_str()}] CONNECT {host}:{port} OK | {cost:.1f} ms"
                else:
                    fail_count += 1
                    log_line = f"[{now_str()}] CONNECT {host}:{port} FAIL | {err}"

                print(log_line)
                f.write(log_line + "\n")
                f.flush()

                time.sleep(interval)

    except KeyboardInterrupt:
        print("\n检测到手动中断")

    except Exception as e:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{now_str()}] [ERROR] {e}\n")

    finally:
        avg_cost = sum(cost_list) / len(cost_list) if cost_list else 0
        min_cost = min(cost_list) if cost_list else 0
        max_cost = max(cost_list) if cost_list else 0

        with open(log_file, "a", encoding="utf-8") as f:
            f.write("===== SUMMARY =====\n")
            f.write(f"TOTAL:   {total_count}\n")
            f.write(f"SUCCESS: {success_count}\n")
            f.write(f"FAIL:    {fail_count}\n")
            f.write(f"AVG RTT: {avg_cost:.1f} ms\n")
            f.write(f"MIN RTT: {min_cost:.1f} ms\n")
            f.write(f"MAX RTT: {max_cost:.1f} ms\n")
            f.write(f"===== END   {now_str()} ({timezone})  =====\n")

        print("日志已安全保存，脚本结束")


if __name__ == "__main__":
    main()
