import subprocess
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


def now_str(timezone):
    tz = pytz.timezone(timezone)
    return datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


def parse_rtt(line):
    """
    从 ping 输出中提取 RTT（ms）
    兼容中英文 Windows
    """
    line_l = line.lower()

    if "time=" in line_l:
        try:
            return float(line_l.split("time=")[1].split("ms")[0])
        except Exception:
            return None

    if "时间=" in line:
        try:
            return float(line.split("时间=")[1].split("ms")[0])
        except Exception:
            return None

    return None


def main():
    config = load_config()

    # ---------- 通用目标配置 ----------
    target_cfg = config.get("target", {})
    host = target_cfg.get("host", "8.8.8.8")
    timezone = target_cfg.get("timezone", "UTC")

    log_dir = target_cfg.get("log_dir", "./logs")

    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"ping_{host}.log")

    # ---------- Ping 配置 ----------
    ping_cfg = config.get("ping", {})
    if not ping_cfg.get("enable", False):
        print("Ping 测试未启用（ping.enable = false）")
        return

    interval = int(ping_cfg.get("interval", 1))

    # ---------- 统计变量 ----------
    total_count = 0
    success_count = 0
    fail_count = 0
    cost_list = []

    print("开始 Ping 测试")
    print(f"目标地址：{host}")
    print(f"日志文件：{log_file}")
    print(f"时区：{timezone}")
    print("按 Ctrl+C 停止\n")

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("\n")
            f.write(f"===== START {now_str(timezone)} ({timezone}) =====\n")
            f.flush()

            while True:
                total_count += 1

                proc = subprocess.Popen(
                    ["ping", host, "-n", "1"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True
                )

                lines = []
                rtt = None
                failed = False

                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    if line.lower().startswith("pinging"):
                        continue

                    lines.append(line)

                    # 失败判定
                    if "timed out" in line.lower() or "超时" in line:
                        failed = True

                    # RTT 解析
                    rtt_val = parse_rtt(line)
                    if rtt_val is not None:
                        rtt = rtt_val

                if rtt is not None:
                    cost_list.append(rtt)

                if failed or rtt is None:
                    fail_count += 1
                else:
                    success_count += 1

                if lines:
                    merged = " | ".join(lines)
                    log_line = f"[{now_str(timezone)}] {merged}"
                    print(log_line)
                    f.write(log_line + "\n")

                f.flush()
                time.sleep(interval)

    except KeyboardInterrupt:
        print("\n检测到手动中断")

    except Exception as e:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{now_str(timezone)}] [ERROR] {e}\n")

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
            f.write(f"===== END   {now_str(timezone)} ({timezone}) =====\n")

        print("日志已安全保存，脚本结束")


if __name__ == "__main__":
    main()
