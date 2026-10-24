"""Scan a git repository that is about to be published for secrets and private data.

Run from the private repository root, pointing at the public copy:
    uv run --project backend python scripts/release_scan.py ../marketing-workbench

Every blob reachable from any ref is scanned (the whole history, not only the working tree),
plus commit and tag metadata (author/committer names and e-mails, messages).
Checks: credential formats, private keys, password hashes, local Windows user directories,
real Tailscale hosts, real ngrok hosts, phone numbers, e-mail addresses, the secret values and
private hostnames in the private .env, private terms from RELEASE_PRIVATE_TERMS in .env
(comma separated, for example your legal name or old account names), and, when the production
database is readable, the real platform account IDs, notification group IDs, contact and
connected-account names and recent comment lines it holds (opened read-only).

RELEASE_PUBLIC_TERMS (comma separated) lists what is published on purpose, such as the contact
address or the brand handle; those are not reported.

Prints only the kind of finding, how many, and which paths. It never prints matched values.
Exit code 1 when anything that must not be published is found, when an e-mail address is not
confirmed public, or when the private terms or the database comparison were skipped
(pass --allow-skip to accept a skipped comparison knowingly).
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]

ENV_NAME = rb"[A-Z][A-Z0-9_]*(?:SECRET|TOKEN|KEY|PASSWORD)[A-Z0-9_]*"
# 金鑰與權杖格式；只比對格式，不判斷真假，命中就要人工確認。
SECRET_PATTERNS = {
    "meta_token": rb"EAA[A-Za-z0-9]{40,}",
    "google_oauth_token": rb"ya29\.[A-Za-z0-9_-]{20,}",
    "google_api_key": rb"AIza[0-9A-Za-z_-]{35}",
    "google_client_secret": rb"GOCSPX-[A-Za-z0-9_-]{20,}",
    "google_client_id": rb"[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com",
    # 前面不能接英數字，避免把 task-xxxx、risk-xxxx 之類的識別字誤判成金鑰。
    "openai_key": rb"(?<![A-Za-z0-9])sk-(?:proj-)?[A-Za-z0-9_-]{20,}",
    "anthropic_key": rb"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_-]{20,}",
    "github_token": rb"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{30,}",
    "tiktok_token": rb"act\.[A-Za-z0-9!*_-]{30,}",
    "private_key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    # 完整的 PHC 雜湊字串；只寫前綴的程式碼（例如 startswith("$argon2id$")）不算。
    "password_hash": rb"\$argon2(?:id|i|d)\$v=\d+\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/]{8,}",
    # 名稱含 SECRET／TOKEN／KEY／PASSWORD 的設定行：.env 與 shell 的 NAME=值（等號兩邊不留空白，
    # 才不會把程式裡 NAME_KEY = "..." 這類常數當成秘密），以及 PowerShell 的 $env:NAME = 值。
    # 值是 <佔位>、$變數 或 %變數% 時不算。
    "env_secret_value": (
        rb"(?m)^[ \t]*(?:(?:export[ \t]+)?" + ENV_NAME
        + rb"=|\$env:" + ENV_NAME + rb"[ \t]*=[ \t]*)"
        rb"(?![\"']?[<$%{])\S{8,}"
    ),
}
PRIVATE_PATTERNS = {
    "windows_user_dir": rb"(?i)[a-z]:[\\/]+users[\\/]+[^\\/\s\"']+",
    "tailscale_host": rb"(?i)(?<![a-z0-9.-])[a-z0-9-]+\.[a-z0-9-]+\.ts\.net",
    "ngrok_host": rb"(?i)(?<![a-z0-9-])(?!example\b)[a-z0-9-]+\.ngrok(?:-free)?\.(?:app|io|dev)",
}
# 命中後再排除的示範值：網址裡含 example 標籤的一律視為文件範例。
SAFE_MATCH = {"tailscale_host": re.compile(rb"(?i)(?:^|\.)example\.")}
PHONE = re.compile(rb"(?<![0-9A-Za-z])09\d{2}-?\d{3}-?\d{3}(?![0-9A-Za-z])")
# 測試資料刻意使用的假號碼。
FAKE_PHONES = {b"0912345678", b"0912-345-678", b"0912-000-123"}
EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 比對整個網域或其子網域；只看字尾會讓 evil-example.com 之類的網域混過去。
SAFE_EMAIL_DOMAINS = (b"example.com", b"example.test", b"example.org", b"users.noreply.github.com",
                      b"anthropic.com", b"example.ts.net", b"example.ngrok.app")
NOREPLY = b"@users.noreply.github.com"
SECRET_NAME = re.compile(r"SECRET|TOKEN|KEY|PASSWORD")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def safe_domain(domain):
    domain = domain.lower()
    return any(domain == safe or domain.endswith(b"." + safe) for safe in SAFE_EMAIL_DOMAINS)


def read_env_file(path):
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        name, sep, value = line.partition("=")
        if sep and not name.lstrip().startswith("#"):
            values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def env_values():
    return read_env_file(REPO / ".env")


def private_hosts(value):
    """Hostnames inside a URL value or a JSON host list, without local or example hosts."""
    candidates = []
    try:
        parsed = json.loads(value)
    except ValueError:
        parsed = None
    if isinstance(parsed, list):
        candidates = [str(item) for item in parsed]
    else:
        candidates = re.findall(r"https?://[^\s,\"']+", value)
    hosts = set()
    for item in candidates:
        host = (urlsplit(item).hostname if "://" in item else item.split(":")[0]).lower()
        if (not host or host in LOCAL_HOSTS or re.fullmatch(r"[0-9.]+", host)
                or "." not in host or safe_domain(host.encode())):
            continue
        hosts.add(host)
    return hosts


def env_needles(env):
    """Secret values and private hostnames from the private .env. Never printed."""
    # .env.example 會公開；和範例相同的值本來就不是秘密。
    example = read_env_file(REPO / ".env.example")
    needles = defaultdict(set)
    for name, value in env.items():
        if not value or value == example.get(name):
            continue
        if (SECRET_NAME.search(name) and len(value) >= 8 and not value.isdigit()
                and value.lower() not in {"true", "false"}):
            needles["env_secret"].add(value.encode())
        if name.endswith(("_URL", "_ORIGIN", "_HOSTS", "_HOST")) or name == "ALLOWED_HOSTS":
            for host in private_hosts(value):
                needles["env_private_host"].add(host.encode())
    return needles


def database_path(env):
    database = env.get("DATABASE_PATH") or str(REPO / "data" / "db" / "mwb.db")
    path = Path(database)
    return path if path.is_absolute() else REPO / path


def add_name(needles, kind, value):
    """Display names are short and common; only distinctive ones are compared."""
    text = str(value or "").strip()
    ascii_only = text.isascii()
    if len(text) >= (6 if ascii_only else 3):
        needles[kind].add(text.encode())


def production_needles(env):
    """Real identifiers from the production database (read-only). Empty when it is not readable."""
    path = database_path(env)
    if not path.exists():
        return {}, "找不到資料庫"
    needles = defaultdict(set)
    try:
        db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}, "無法開啟資料庫"
    try:
        for (external,) in db.execute("select external_id from accounts"):
            if external and len(str(external)) >= 6:
                needles["real_account_id"].add(str(external).encode())
        for (value,) in db.execute(
            "select value_json from settings where key like 'notification.policy.%'"
        ):
            group = re.search(r'"group_id"\s*:\s*"([^"]{8,})"', value or "")
            if group:
                needles["real_line_group_id"].add(group.group(1).encode())
        for (value,) in db.execute(
            "select value_json from settings where key = 'notification.discovered_groups'"
        ):
            try:
                groups = json.loads(value or "{}")
            except ValueError:
                groups = {}
            for group_id in groups if isinstance(groups, dict) else []:
                if len(str(group_id)) >= 8:
                    needles["real_line_group_id"].add(str(group_id).encode())
        # 只取最近的聯絡人：每個名稱都要和每個檔案版本比對，數量太多會讓掃描慢到不能用。
        for (name,) in db.execute(
            "select display_name from contacts order by id desc limit 500"
        ):
            add_name(needles, "real_contact_name", name)
        for account_name, ig_username in db.execute(
            "select account_name, ig_username from oauth_connections"
        ):
            add_name(needles, "real_connected_account", account_name)
            add_name(needles, "real_connected_account", ig_username)
        for (text,) in db.execute(
            "select text from messages where length(text) > 12 order by id desc limit 200"
        ):
            for line in (text or "").splitlines():
                line = line.strip()
                if len(line) >= 12:
                    needles["real_comment_text"].add(line[:40].encode())
    except sqlite3.Error:
        # 結構不同或被鎖住時不印錯誤內容（可能含路徑），只回報略過。
        return {}, "資料庫讀取失敗"
    finally:
        db.close()
    return needles, None


def blobs(target):
    listing = subprocess.run(
        ["git", "-C", str(target), "rev-list", "--all", "--objects"],
        capture_output=True, check=True,
    ).stdout.decode("utf-8", "replace").splitlines()
    paths = defaultdict(set)
    for line in listing:
        sha, _, name = line.partition(" ")
        if name:
            paths[sha].add(name)
    reader = subprocess.Popen(
        ["git", "-C", str(target), "cat-file", "--batch"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    )
    try:
        for sha, names in paths.items():
            reader.stdin.write(sha.encode() + b"\n")
            reader.stdin.flush()
            header = reader.stdout.readline().split()
            if len(header) < 3:
                continue
            data = reader.stdout.read(int(header[2]))
            reader.stdout.read(1)
            if header[1] == b"blob":
                yield names, data
    finally:
        reader.stdin.close()
        reader.wait()


def metadata(target):
    """Commit and tag metadata: yields (label, author/tagger e-mails, text to scan)."""
    log = subprocess.run(
        ["git", "-C", str(target), "log", "--all",
         "--format=%x1e%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%B"],
        capture_output=True, check=True,
    ).stdout
    for record in log.split(b"\x1e"):
        if not record.strip():
            continue
        sha, author, author_email, committer, committer_email, body = (
            record.split(b"\x1f", 5) + [b""] * 6)[:6]
        yield (f"commit {sha.decode()[:10]}", [author_email, committer_email],
               b"\n".join([author, author_email, committer, committer_email, body]))
    tags = subprocess.run(
        ["git", "-C", str(target), "for-each-ref", "refs/tags",
         "--format=%1e%(refname:short)%1f%(taggername)%1f%(taggeremail)%1f%(contents)"],
        capture_output=True, check=True,
    ).stdout
    for record in tags.split(b"\x1e"):
        if not record.strip():
            continue
        name, tagger, tagger_email, contents = (record.split(b"\x1f", 3) + [b""] * 4)[:4]
        emails = [tagger_email.strip(b"<>")] if tagger_email.strip(b"<>") else []
        yield (f"tag {name.decode('utf-8', 'replace')}", emails,
               b"\n".join([name, tagger, tagger_email, contents]))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="開源前掃描金鑰與私人資料（只列位置，不印數值）")
    parser.add_argument("target", help="要公開的 git repository 路徑")
    parser.add_argument("--allow-skip", action="store_true",
                        help="私人字詞未設定或讀不到正式資料庫時仍以 0 結束（需確認是刻意略過）")
    args = parser.parse_args()
    target = Path(args.target).resolve()
    env = env_values()
    # 環境變數優先，方便不改 .env 就臨時加字詞。
    raw_terms = os.environ.get("RELEASE_PRIVATE_TERMS") or env.get("RELEASE_PRIVATE_TERMS", "")
    terms = {t.strip().encode() for t in raw_terms.split(",") if t.strip()}
    raw_public = os.environ.get("RELEASE_PUBLIC_TERMS") or env.get("RELEASE_PUBLIC_TERMS", "")
    public = {t.strip().lower().encode() for t in raw_public.split(",") if t.strip()}
    needles, skipped = production_needles(env)
    for kind, values in env_needles(env).items():
        needles.setdefault(kind, set()).update(values)
    # 刻意公開的字詞（例如品牌帳號）不算洩漏；只排除完全相同的值。
    needles = {
        kind: {v for v in values if v.lower() not in public} for kind, values in needles.items()
    }
    patterns = {k: re.compile(v) for k, v in {**SECRET_PATTERNS, **PRIVATE_PATTERNS}.items()}
    failures = defaultdict(lambda: defaultdict(int))
    emails = defaultdict(set)

    def scan(names, data):
        found = defaultdict(int)
        for kind, pattern in patterns.items():
            matches = pattern.findall(data)
            if kind in SAFE_MATCH:
                matches = [m for m in matches if not SAFE_MATCH[kind].search(m)]
            found[kind] += len(matches)
        found["phone"] = sum(1 for p in PHONE.findall(data) if p not in FAKE_PHONES)
        for term in terms:
            found["private_term"] += data.count(term)
        for kind, values in needles.items():
            found[kind] += sum(1 for value in values if value in data)
        for address in EMAIL.findall(data):
            domain = address.split(b"@")[1].lower()
            if not safe_domain(domain) and address.lower() not in public and domain not in public:
                for name in names:
                    emails[name].add(domain)
        for kind, count in found.items():
            if count:
                for name in names:
                    failures[kind][name] += count

    scanned = 0
    for names, data in blobs(target):
        scanned += 1
        scan(names, data)
    commits = 0
    for label, identities, text in metadata(target):
        commits += 1
        scan([label], text)
        # 提交作者信箱會跟著公開 repo 一起公開；只接受 GitHub noreply。
        for address in identities:
            if not address.strip().lower().endswith(NOREPLY):
                failures["non_noreply_identity"][label] += 1
    print(f"掃描 {scanned} 個檔案版本（含所有歷史）與 {commits} 筆提交／標籤資訊：{target.name}")
    print(f"私人字詞 {len(terms)} 個（RELEASE_PRIVATE_TERMS）；"
          f"刻意公開 {len(public)} 個（RELEASE_PUBLIC_TERMS）；"
          f".env 秘密值 {len(needles.get('env_secret', ()))} 個；正式資料庫比對："
          + (f"略過（{skipped}）" if skipped else "有"))
    for kind, files in sorted(failures.items()):
        print(f"[需處理] {kind}：{len(files)} 個位置")
        for name, count in sorted(files.items())[:20]:
            print(f"    {count:4d}  {name}")
    for name, domains in sorted(emails.items()):
        print(f"[確認] 信箱網域 {', '.join(sorted(d.decode() for d in domains))}：{name}")
    incomplete = []
    if not terms:
        incomplete.append("RELEASE_PRIVATE_TERMS 未設定")
    if skipped:
        incomplete.append(f"正式資料庫比對略過（{skipped}）")
    if failures:
        print("未通過：有需處理的項目。")
        return 1
    if emails:
        print("未通過：有未確認的信箱。確認是刻意公開的聯絡信箱後，"
              "把完整信箱加入 RELEASE_PUBLIC_TERMS 再掃描。")
        return 1
    if incomplete and not args.allow_skip:
        print("未通過：比對不完整（" + "；".join(incomplete)
              + "）。補齊後重掃，或確認刻意略過時加 --allow-skip。")
        return 1
    if incomplete:
        print("通過（--allow-skip，已略過：" + "；".join(incomplete)
              + "）：沒有找到金鑰、私人路徑或私人字詞。")
        return 0
    print("通過：沒有找到金鑰、私人路徑、私人字詞或正式資料。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
