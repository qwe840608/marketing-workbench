"""一個指令跑完全部驗收，只輸出精簡結果；詳細輸出寫到 .runtime/verify/<步驟>.log。

用法（在專案根目錄）：
    python scripts/verify_all.py                     # 全部驗收
    python scripts/verify_all.py --data-baseline F   # 另與 F 比對 data/ 檔案清單
    python scripts/verify_all.py snapshot-data F     # 只把目前 data/ 清單寫到 F（開工前先拍）
    python scripts/verify_all.py --only pytest,check_publish   # 只跑指定步驟（開發中用）
    python scripts/verify_all.py --jobs 1            # 全部依序執行（排查互相干擾時用）

全部通過時最後一行是 ALL PASS，exit 0；否則列出失敗步驟與日誌位置，exit 1。
ruff、tsc、build 先依序執行；其餘步驟（pytest、前端測試、各隔離介面檢查）平行執行，
每支介面檢查都有自己的隨機埠、暫存資料庫與輸出資料夾。平行步驟結束後比對 .runtime 與
.runtime/tmp，確認整輪驗收沒有留下暫存（runtime-leftovers）。用 --only 時改成最後單獨執行
完整的 runtime-clean（scripts/test_runtime_clean.py，會重跑兩支代表性檢查並比對暫存）。
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOGS = REPO / ".runtime" / "verify"
DIST = REPO / ".runtime" / "verify-dist"
SUPPLEMENTARY = ["ui_dashboard"]
# 最耗時的兩支介面檢查依螢幕寬度拆成兩個行程平行跑（各自的埠、資料庫與輸出資料夾），
# 斷言不變；--only 寫原名會兩個寬度都跑。
SPLIT = {"check_all_features": ("1440", "390"), "check_publish": ("1440", "390")}
# 預設在背景跑、不霸佔電腦：同時 4 個步驟、pytest 6 個行程，並降低優先權。
# 離開電腦時可用 --jobs 8 換速度（pytest 隨之 12 個行程）；auto（等於核心數）會和瀏覽器檢查搶 CPU。
DEFAULT_JOBS = 4


def pytest_workers(jobs):
    return str(max(2, jobs * 3 // 2))


def lower_priority():
    # 子行程（pytest、uvicorn、Chromium、node）會繼承低於標準的優先權，前景的程式不會被拖慢。
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        below_normal = 0x4000
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        # 沒宣告型別時 GetCurrentProcess 的虛擬控制代碼會被截成 int，設定靜默失敗。
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.SetPriorityClass.restype = wintypes.BOOL
        if not kernel.SetPriorityClass(kernel.GetCurrentProcess(), below_normal):
            print(f"注意：無法降低優先權（錯誤 {ctypes.get_last_error()}），照常執行", flush=True)
    else:
        os.nice(10)
# 先跑的步驟：後面的介面檢查都依賴 build 產出的前端。
SERIAL = ("ruff", "tsc", "build")
# 耗時長的先排進平行佇列，避免最後只剩一支長檢查在跑。
# pytest 最久又最吃 CPU，第一個開始，和瀏覽器檢查（多半在等畫面）重疊。
SLOW_FIRST = ("pytest", "check_all_features-390", "check_all_features-1440", "check_publish-390",
              "check_publish-1440", "check_ideation_fixes", "check_ui_scale", "node-test")
# --only 時最後才跑、而且必須單獨跑：它比對 .runtime/tmp 是否清空，和其他檢查並行會互相干擾。
# 完整驗收時改由 verify_all 比對整輪的暫存，它只跑單元測試，可以和其他步驟並行。
FINAL = ("runtime-clean",)
RUNTIME_GUARD_ENV = "VERIFY_ALL_RUNTIME_GUARD"
RUNTIME_OUTPUTS = {"tmp", "check-output", "agentdesk-node", "verify", "verify-dist"}
# frontend/tests 有幾支測試會自己建置前端再跑這些介面檢查；verify_all 已直接跑同一批檢查時，
# 讓它們略過，避免同一份檢查跑兩次、多建置五次前端。
WRAPPED_CHECKS = ("check_ai_resilience_frontend", "check_comment_sync_frontend",
                  "check_dm_backfill_frontend", "check_followers_frontend", "check_polish_frontend")
# 不可進版控的字串：本機使用者目錄、真實 Tailscale 網址、ngrok 固定網域、已移除功能的舊名稱。
# 拆開寫，避免本檔自己被禁止字串掃描命中。
BANNED = "|".join(
    [
        r"[a-z]:[\/]+" + "users" + r"[\/]+",
        r"\.tail[0-9a-f]{4,}\.ts\.net",
        r"ngrok-free\.dev",
        "示範" + "資料",
    ]
)
DATA_EXCLUDE = ("data/db/", "data/logs/", "data/manual-backups/")


def tool(name):
    return shutil.which(name) or name


def data_listing():
    root = REPO / "data"
    if not root.exists():
        return []
    rows = []
    for path in root.rglob("*"):
        if path.is_file():
            rel = path.relative_to(REPO).as_posix()
            if not rel.startswith(DATA_EXCLUDE):
                rows.append(rel)
    return sorted(rows)


def browser_checks():
    names = sorted(
        p.stem for p in (REPO / "scripts").glob("check_*.py") if not p.stem.endswith("_live")
    )
    return names + SUPPLEMENTARY


def steps(basetemp, jobs):
    backend, frontend = REPO / "backend", REPO / "frontend"
    uv, npm, npx, node = tool("uv"), tool("npm"), tool("npx"), tool("node")
    node_tests = sorted(str(p) for p in (REPO / "scripts").glob("*.test.mjs"))
    result = [
        ("ruff", [uv, "run", "ruff", "check", "."], backend),
        ("pytest", [uv, "run", "pytest", "-q", "-n", pytest_workers(jobs), "-p", "no:cacheprovider",
                    "--basetemp", str(basetemp), "-o", "tmp_path_retention_policy=none"], backend),
        ("tsc", [npx, "tsc", "--noEmit", "-p", "."], frontend),
        ("frontend-test", [npm, "test"], frontend),
        ("node-test", [node, "--test", *node_tests], REPO),
        ("build", [npm, "run", "build", "--", "--outDir", str(DIST)], frontend),
    ]
    for name in browser_checks():
        command = [uv, "run", "python", str(REPO / "scripts" / f"{name}.py")]
        for width in SPLIT.get(name, (None,)):
            if width:
                result.append((f"{name}-{width}", command, backend, {"MWB_CHECK_VIEWPORT": width}))
            else:
                result.append((name, command, backend))
    clean = str(REPO / "scripts" / "test_runtime_clean.py")
    result.append(("runtime-clean", [uv, "run", "python", clean], backend))
    return result


def runtime_items():
    runtime = REPO / ".runtime"
    tmp = runtime / "tmp"
    return ({p.name for p in runtime.iterdir()},
            {p.name for p in tmp.iterdir()} if tmp.is_dir() else set())


def runtime_leftovers(before):
    # 只看這次新增的項目：長期使用的 checkout 可能留有舊暫存，不是本次驗收的責任。
    top, tmp = runtime_items()
    # 介面檢查刻意留下截圖（*-screens）與工具清單（*-tools.json）供人工查看；全新 checkout（CI）
    # 一開始沒有這些項目，不排除的話每次都會被當成暫存殘留。
    kept = {n for n in top if n.endswith(("-screens", "-tools.json"))} | RUNTIME_OUTPUTS
    new = sorted(top - before[0] - kept) + sorted(f"tmp/{n}" for n in tmp - before[1])
    return [("runtime-leftovers", new[:5])] if new else []


def static_checks(baseline):
    failures = []
    banned = subprocess.run(["git", "grep", "-n", "-I", "-i", "-E", BANNED], cwd=REPO,
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    # git grep：0＝有命中、1＝沒有命中；其他代表掃描本身失敗，不能當成通過。
    if banned.returncode not in (0, 1):
        detail = f"git grep 失敗（exit {banned.returncode}）：{banned.stderr[:200]}"
        failures.append(("banned-strings", [detail]))
    elif banned.stdout.strip():
        failures.append(("banned-strings", banned.stdout.strip().splitlines()[:5]))
    hexes = []
    sheets = [*(REPO / "frontend/src").glob("*.css"), *(REPO / "frontend/src/pages").glob("*.css")]
    for css in sheets:
        for number, line in enumerate(css.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"\s*(:root|--)", line):
                continue
            if re.search(r"#[0-9a-fA-F]{3,8}\b", line):
                hexes.append(f"{css.relative_to(REPO).as_posix()}:{number}")
    if hexes:
        failures.append(("hex-colors", hexes[:5]))
    failures.extend(data_check(baseline))
    return failures


def data_check(baseline):
    failures = []
    if baseline:
        before = [line for line in Path(baseline).read_text(encoding="utf-8").splitlines() if line]
        after = data_listing()
        if before != after:
            added = sorted(set(after) - set(before))[:5]
            removed = sorted(set(before) - set(after))[:5]
            failures.append(("data-diff", [f"新增 {added}", f"消失 {removed}"]))
    return failures


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", default="verify", choices=["verify", "snapshot-data"])
    parser.add_argument("path", nargs="?")
    parser.add_argument("--data-baseline")
    parser.add_argument("--only", help="逗號分隔的步驟名稱")
    default_temp = Path(tempfile.gettempdir()) / "codex-pytest" / "verify"
    parser.add_argument("--basetemp", default=str(default_temp))
    parser.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                        help="平行執行的步驟數（1＝依序；8＝較快但會占滿 CPU）")
    args = parser.parse_args()
    if args.command == "snapshot-data":
        if not args.path:
            parser.error("snapshot-data 需要輸出檔案路徑")
        Path(args.path).write_text("\n".join(data_listing()) + "\n", encoding="utf-8")
        print(f"data 清單 {len(data_listing())} 筆 → {args.path}")
        return 0

    lower_priority()
    LOGS.mkdir(parents=True, exist_ok=True)
    # pytest 只建立 --basetemp 本身，上層資料夾在乾淨的機器（例如 CI）上要先建好。
    Path(args.basetemp).parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "FRONTEND_DIST_DIR": str(DIST), "PYTHONIOENCODING": "utf-8"}
    selected = None
    if args.only:
        selected = {name.strip() for name in args.only.split(",") if name.strip()}
        for name in set(selected) & SPLIT.keys():
            selected.remove(name)
            selected.update(f"{name}-{width}" for width in SPLIT[name])
    all_steps = steps(args.basetemp, args.jobs)
    if selected is not None:
        # 打錯步驟名稱時什麼都不跑卻印 ALL PASS，會被誤認為驗收通過。
        unknown = sorted(selected - {step[0] for step in all_steps})
        if not selected or unknown:
            parser.error("未知的步驟：" + ", ".join(unknown or ["（空白）"])
                         + "；可用：" + ", ".join(step[0] for step in all_steps))
        uses_dist = any(n.startswith("check_") or n in (*SUPPLEMENTARY, *FINAL) for n in selected)
        if "build" not in selected and uses_dist:
            print(f"注意：未選 build，介面檢查使用既有的 {DIST.relative_to(REPO).as_posix()}；"
                  "前端改過時請加上 build。", flush=True)
    failed, started = [], time.time()
    chosen = [step for step in all_steps if not selected or step[0] in selected]
    if set(WRAPPED_CHECKS) <= {step[0] for step in chosen}:
        env["VERIFY_ALL_RUNS_BROWSER_CHECKS"] = "1"

    def run(step):
        name, command, cwd, *extra = step
        log = LOGS / f"{name}.log"
        begin = time.time()
        with log.open("w", encoding="utf-8") as stream:
            step_env = {**env, **(extra[0] if extra else {})}
            code = subprocess.run(command, cwd=cwd, env=step_env, stdout=stream,
                                  stderr=subprocess.STDOUT).returncode
        return name, code, time.time() - begin, log

    def report(name, code, seconds, log):
        status = "PASS" if code == 0 else "FAIL"
        where = "" if code == 0 else f" → {log.relative_to(REPO).as_posix()}"
        print(f"{status} {name} ({seconds:.0f}s){where}", flush=True)
        if code:
            failed.append(name)

    for step in chosen:
        if step[0] in SERIAL:
            report(*run(step))
    # 完整驗收：runtime-clean 與其他步驟並行，暫存改由這裡對整輪比對。
    guard = selected is None
    final = () if guard else FINAL
    if guard:
        env[RUNTIME_GUARD_ENV] = "1"
    before = runtime_items()
    if "build" in failed:
        print("FAIL 前端建置失敗，略過其餘步驟")
    else:
        rest = sorted((s for s in chosen if s[0] not in SERIAL + final),
                      key=lambda s: SLOW_FIRST.index(s[0]) if s[0] in SLOW_FIRST else len(SLOW_FIRST))
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            for future in as_completed([pool.submit(run, step) for step in rest]):
                report(*future.result())
        for step in chosen:
            if step[0] in final:
                report(*run(step))
        if guard:
            for name, details in runtime_leftovers(before):
                print(f"FAIL {name}: " + "；".join(details))
                failed.append(name)
    checks = static_checks(args.data_baseline) if not selected else data_check(args.data_baseline)
    for name, details in checks:
        print(f"FAIL {name}: " + "；".join(details))
        failed.append(name)
    total = time.time() - started
    if failed:
        print(f"FAILED {len(failed)}: {', '.join(failed)} ({total / 60:.1f} min)")
        return 1
    print(f"ALL PASS ({total / 60:.1f} min)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
