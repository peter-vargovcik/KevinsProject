"""One-shot SSH helper for Pi setup. Password via env PI_PASS only."""
from __future__ import annotations

import os
import pathlib
import sys

import paramiko

HOST = os.environ.get("PI_HOST", "192.168.1.152")
USER = os.environ.get("PI_USER", "pi")
PASSWORD = os.environ.get("PI_PASS", "")
KEY_PATH = pathlib.Path(os.environ.get("PI_KEY", str(pathlib.Path.home() / ".ssh" / "id_ed25519_pi")))


def connect(password: bool = False, key: bool = False) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = dict(
        hostname=HOST,
        username=USER,
        timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )
    if key:
        kwargs["key_filename"] = str(KEY_PATH)
    if password:
        kwargs["password"] = PASSWORD
    client.connect(**kwargs)
    return client


def run(client: paramiko.SSHClient, cmd: str, timeout: int = 120) -> tuple[int, str, str]:
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "info"
    if action == "install-key":
        if not PASSWORD:
            print("PI_PASS not set", file=sys.stderr)
            return 1
        pub = KEY_PATH.with_suffix(".pub").read_text().strip()
        client = connect(password=True)
        run(client, "mkdir -p ~/.ssh && chmod 700 ~/.ssh")
        # Write key via SFTP to avoid quoting hell
        sftp = client.open_sftp()
        try:
            try:
                with sftp.open(".ssh/authorized_keys", "r") as f:
                    existing = f.read().decode(errors="replace")
            except IOError:
                existing = ""
            if pub not in existing:
                with sftp.open(".ssh/authorized_keys", "a") as f:
                    f.write((pub + "\n").encode())
            sftp.chmod(".ssh/authorized_keys", 0o600)
        finally:
            sftp.close()
        code, out, err = run(client, "uname -a; hostname; whoami; head -5 /etc/os-release")
        print(out)
        if err:
            print(err, file=sys.stderr)
        client.close()
        return 0

    if action == "cmd":
        cmd = " ".join(sys.argv[2:])
        client = connect(key=True)
        code, out, err = run(client, cmd, timeout=600)
        sys.stdout.write(out)
        sys.stderr.write(err)
        client.close()
        return code

    if action == "upload":
        # upload local_dir_or_file remote_path
        local = pathlib.Path(sys.argv[2])
        remote = sys.argv[3]
        client = connect(key=True)
        sftp = client.open_sftp()

        def ensure_dir(path: str) -> None:
            parts = path.strip("/").split("/")
            cur = ""
            # absolute path
            if path.startswith("/"):
                cur = ""
            for part in parts:
                if not part:
                    continue
                cur = f"{cur}/{part}" if cur or path.startswith("/") else part
                if path.startswith("/") and not cur.startswith("/"):
                    cur = "/" + cur
                try:
                    sftp.stat(cur)
                except IOError:
                    sftp.mkdir(cur)

        def upload_path(src: pathlib.Path, dst: str) -> None:
            if src.is_dir():
                ensure_dir(dst)
                for child in src.iterdir():
                    if child.name in {".git", "__pycache__", ".venv"} or child.suffix == ".pyc":
                        continue
                    upload_path(child, f"{dst.rstrip('/')}/{child.name}")
            else:
                parent = dst.rsplit("/", 1)[0]
                ensure_dir(parent)
                sftp.put(str(src), dst)
                print(f"put {src} -> {dst}")

        upload_path(local, remote)
        sftp.close()
        client.close()
        return 0

    print(f"unknown action: {action}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
