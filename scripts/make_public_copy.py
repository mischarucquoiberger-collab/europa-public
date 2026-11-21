#!/usr/bin/env python3
"""Build the clean copy of this project that goes into the PUBLIC repository.

    python3 scripts/make_public_copy.py [destination]      (default: ~/Desktop/europa-public)

The copy is the committed code of this (private) repository, minus what must stay private:
- the planning notes under docs/superpowers/ (they describe a private codebase);
- local paths on the owner's machine in docstrings;
- the contact address in the interface's licence notice.
It then checks the copy (no key from .env, no key-shaped string, no local path, no contact address)
and commits it. The destination keeps its own short history: the first run makes one commit, a later
run adds one commit with the changes. Nothing is pushed here; the script prints the command.
"""
from __future__ import annotations

import io
import re
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.home() / "Desktop" / "europa-public"
MARKER = ".public-copy"

REMOVE = ("docs/superpowers",)
TEXT = {".py", ".md", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".json", ".html", ".css", ".sh", ".txt", ".toml",
        ".ini", ".yml", ".yaml", ".example", ""}
BUILT = "LECTIO/kabu/public/xyz"            # a minified build: never rewritten, only scanned

SCRUB = (
    (re.compile(r"/Users/[A-Za-z0-9_.-]+/Desktop/LLM/app/services/"), "the original product's "),
    (re.compile(r"/Users/[A-Za-z0-9_.-]+/Desktop/LLM/app"), "the original product"),
    (re.compile(r"/Users/[A-Za-z0-9_.-]+/Desktop/LLM/?"), "the original product "),
    (re.compile(r"/Users/[A-Za-z0-9_.-]+/Desktop/prism-nicrron/?"), "./"),
    (re.compile(r"/Users/[A-Za-z0-9_.-]+/anaconda3/bin/python3"), "python3"),
    (re.compile(r"/Users/[A-Za-z0-9_.-]+/"), "~/"),
    (re.compile(r"Contact [A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+ for the relevant agreement"),
     "Contact the rights holder for the relevant agreement"),
)
KEY_SHAPES = re.compile(rb"(pt-sk-[A-Za-z0-9]{8,}|sk-[A-Za-z0-9]{24,}|sk_(?:live|test)_[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|"
                        rb"AIza[0-9A-Za-z_-]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY)")
CONTACT = re.compile(rb"contact@" + rb"ind" + rb"ago")     # written in parts so this file passes its own check
ALLOWED_KEY_SHAPES = (b"pt-sk-abcdef1234567890",)     # the made-up key in the redaction test


def run(*cmd: str, cwd: Path | None = None) -> str:
    return subprocess.run(cmd, cwd=cwd or ROOT, check=True, capture_output=True, text=True).stdout


def secrets() -> dict[str, bytes]:
    """Names and values from .env that would be a leak (never printed)."""
    out: dict[str, bytes] = {}
    env = ROOT / ".env"
    if not env.is_file():
        return out
    for line in env.read_text().splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        name, value = line.split("=", 1)
        value = value.strip().strip("'\"")
        if name.strip() in ("PRISMTRACE_HOST", "PRISM_HIDE_SYSTEM_PROMPT", "PRISM_MAX_CHARS") or len(value) < 12:
            continue
        # for the SEC contact line, the address alone is the private part
        out[name.strip()] = (value.split()[-1] if name.strip() == "SEC_USER_AGENT" else value).encode()
    return out


def main() -> int:
    if DEST.exists() and not (DEST / MARKER).is_file() and any(DEST.iterdir()):
        print(f"refusing: {DEST} exists and is not an earlier public copy")
        return 2
    DEST.mkdir(parents=True, exist_ok=True)
    head = run("git", "rev-parse", "--short", "HEAD").strip()

    # 1. empty the old copy (its .git stays), then lay down the committed tree
    for child in DEST.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir() and not child.is_symlink():
            subprocess.run(["rm", "-rf", str(child)], check=True)
        else:
            child.unlink()
    archive = subprocess.run(["git", "archive", "HEAD"], cwd=ROOT, check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(DEST)
    for rel in REMOVE:
        subprocess.run(["rm", "-rf", str(DEST / rel)], check=True)
    if (DEST / "docs").is_dir() and not any((DEST / "docs").iterdir()):
        (DEST / "docs").rmdir()

    # 2. scrub text files (the minified build is left byte for byte)
    changed = 0
    for path in DEST.rglob("*"):
        if not path.is_file() or ".git" in path.parts or str(path.relative_to(DEST)).startswith(BUILT):
            continue
        if path.suffix.lower() not in TEXT and path.name != "LICENSE":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new = text
        for pattern, replacement in SCRUB:
            new = pattern.sub(replacement, new)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed += 1
    (DEST / MARKER).write_text("A clean copy of the project for the public repository.\n"
                               "Made by scripts/make_public_copy.py of the private repository.\n")

    # 3. checks: any hit stops everything
    problems: list[str] = []
    private = secrets()
    for path in DEST.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        rel = str(path.relative_to(DEST))
        for name, value in private.items():
            if value and value in data:
                problems.append(f"{rel}: holds the value of {name}")
        for found in KEY_SHAPES.findall(data):
            if not any(found.startswith(ok) for ok in ALLOWED_KEY_SHAPES):
                problems.append(f"{rel}: a key-shaped string")
        if not rel.startswith(BUILT):
            if b"/Users/" in data and rel != "scripts/make_public_copy.py":
                problems.append(f"{rel}: a local path")
            if CONTACT.search(data):
                problems.append(f"{rel}: the contact address")
    if problems:
        print("NOT COMMITTED. Problems:")
        for line in sorted(set(problems))[:40]:
            print("  ", line)
        return 1

    # 4. commit
    first = not (DEST / ".git").is_dir()
    if first:
        run("git", "init", "-q", "-b", "main", cwd=DEST)
    run("git", "add", "-A", cwd=DEST)
    if not run("git", "status", "--porcelain", cwd=DEST).strip():
        print(f"nothing new since the last public copy (private commit {head})")
        return 0
    message = ("Europa: research reports from SEC filings, a markets desk, and PRISM-traced agents\n\n"
               "Hackathon project (MONEY TALKS #3, Track 1 \"Money Intelligence\"). See README.md.\n"
               if first else f"Update from the working repository ({head})\n")
    message += ("\nCo-authored-by: Aditya Anirudh <69091366+adityaanirudh@users.noreply.github.com>\n"
                "Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>\n")
    author = run("git", "log", "-1", "--format=%an <%ae>", "--author=Mischa").strip() or None
    cmd = ["git", "commit", "-q", "-m", message]
    if author:
        cmd += ["--author", author]
    run(*cmd, cwd=DEST)
    files = len(run("git", "ls-files", cwd=DEST).splitlines())
    print(f"public copy at {DEST}: {files} files, {changed} scrubbed, from private commit {head}")
    print("first time:  gh repo create <name> --public --source . --remote origin --push   (run inside that folder)")
    print("later:       git push                                                          (run inside that folder)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
