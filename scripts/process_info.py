"""Read-only Windows process metadata when WMI/CIM is unavailable."""

import argparse
import json
import subprocess
import sys

import psutil


def process_info(pid=None):
    processes = [psutil.Process(pid)] if pid else psutil.process_iter()
    result = []
    for process in processes:
        try:
            result.append(
                {
                    "ProcessId": process.pid,
                    "Name": process.name(),
                    "ParentProcessId": process.ppid(),
                    "CreationDate": process.create_time(),
                    "CommandLine": subprocess.list2cmdline(process.cmdline()) if pid else "",
                }
            )
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            if pid:
                raise
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int)
    args = parser.parse_args()
    try:
        print(json.dumps(process_info(args.pid)))
    except psutil.NoSuchProcess:
        print("[]")
    except psutil.AccessDenied:
        print("無法核對程序身分；未停止任何程序。", file=sys.stderr)
        sys.exit(1)
