#!/usr/bin/env python3
"""One gate runner for local.collective: CI, pre-commit and humans run exactly this.

Owner: collective-claude (card Q1/t12). Reviewer: Codex 2. Stdlib only.

    python3 -I tools/check.py                 # all gates, stop at the first failure
    python3 -I tools/check.py --keep-going    # run every gate and report all
    python3 -I tools/check.py --only fitness  # one gate
    python3 -I tools/check.py --receipt R.json

Gates, in order: selftest, hygiene, fitness, format, lint, types, security, tests (+coverage).
`selftest` plants a known-bad snippet for every fitness rule and requires each rule to fire,
so a green fitness gate has been seen red first.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, override

if TYPE_CHECKING:
    from collections.abc import Callable

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ("collective.py", "heartbeat.py", "install_monitor.py")
MAX_SCAN_BYTES = 2_000_000
PINS = {"ruff": "ruff==0.17.3", "mypy": "mypy==2.4.1", "bandit": "bandit==1.9.4", "coverage": "coverage==7.17.1"}

# ---------------------------------------------------------------- fitness rules (architecture as code)
BANNED_CALLS = {
    "os.system": "shell execution",
    "os.popen": "shell execution",
    "eval": "dynamic code",
    "exec": "dynamic code",
    "compile": "dynamic code",
    "pickle.load": "unsafe deserialisation",
    "pickle.loads": "unsafe deserialisation",
    "marshal.loads": "unsafe deserialisation",
    "tempfile.mktemp": "race-prone temp file",
}
# Effects the collective must never perform (write tier W5). Any of these strings in source is refused.
FORBIDDEN_VERBS = (
    "send-keys",
    "send-text",
    "send_keys",
    "send_text",
    "set-pane-grants",
    "apply-config",
    "set-config",
    "agent.prompt",
    "pane.send_input",
    "agent.start",
    "server.stop",
    "plugin.enable",
    "plugin.link",
)
SUBPROCESS_FNS = {"run", "Popen", "call", "check_call", "check_output"}
# The only functions allowed to spawn processes: one audited door per module.
SUBPROCESS_DOORS = {"collective.py": {"run"}, "heartbeat.py": {"run"}, "install_monitor.py": {"command"}}


@dataclass
class Finding:
    """One rule violation at a file and line."""

    rule: str
    path: str
    line: int
    detail: str


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


class _Fitness(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.findings: list[Finding] = []
        self.stack: list[str] = []

    def _add(self, rule: str, node: ast.AST, detail: str) -> None:
        self.findings.append(Finding(rule, self.path, getattr(node, "lineno", 0), detail))

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    @override
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    @override
    def visit_Call(self, node: ast.Call) -> None:
        name = _dotted(node.func)
        if name in BANNED_CALLS:
            self._add("F1-banned-call", node, f"{name}: {BANNED_CALLS[name]}")
        for kw in node.keywords:
            if kw.arg == "shell" and not (isinstance(kw.value, ast.Constant) and kw.value.value is False):
                self._add("F1-banned-call", node, "subprocess shell= must be absent or literally False")
        if name.startswith("subprocess.") and name.split(".")[-1] in SUBPROCESS_FNS:
            doors = SUBPROCESS_DOORS.get(Path(self.path).name, set())
            if not (self.stack and self.stack[-1] in doors):
                where = self.stack[-1] if self.stack else "<module>"
                self._add("F2-subprocess-door", node, f"{name} outside the audited door (in {where})")
        if name in {"os.chmod", "os.fchmod", "Path.chmod"} or name.endswith(".chmod"):
            mode = node.args[-1] if node.args else None
            if isinstance(mode, ast.Constant) and isinstance(mode.value, int) and mode.value & 0o077:
                self._add("F4-private-modes", node, f"chmod {oct(mode.value)} grants group/other access")
        if name == "socket.socket" and node.args:
            fam = _dotted(node.args[0])
            if fam != "socket.AF_UNIX":
                self._add("F5-unix-sockets-only", node, f"socket family {fam or '?'}; only AF_UNIX is allowed")
        self.generic_visit(node)

    @override
    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            for verb in FORBIDDEN_VERBS:
                if re.search(rf"(?<![\w.-]){re.escape(verb)}(?![\w-])", node.value):
                    self._add("F3-forbidden-effect", node, f"'{verb}' is a W5 effect the collective never performs")


def fitness_scan(path: str, source: str) -> list[Finding]:
    """Return every fitness-rule violation in one module's source."""
    visitor = _Fitness(path)
    visitor.visit(ast.parse(source, filename=path))
    return visitor.findings


PLANTED = {
    "F1-banned-call": "import os\nos.system('x')\n",
    "F2-subprocess-door": "import subprocess\ndef helper():\n    subprocess.run(['x'])\n",
    "F3-forbidden-effect": "VERB = 'send-keys'\n",
    "F4-private-modes": "import os\nos.chmod('p', 0o644)\n",
    "F5-unix-sockets-only": "import socket\nsocket.socket(socket.AF_INET)\n",
}

# ---------------------------------------------------------------- hygiene (publication safety)
HYGIENE = {
    "private-key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "token": re.compile(
        r"\b(ghp|gho|ghs|glpat|xox[bpas])[-_][A-Za-z0-9_-]{16,}|\bAKIA[0-9A-Z]{16}\b|\bsk-[A-Za-z0-9]{20,}",
    ),
    "rfc1918-ip": re.compile(r"\b(10\.\d{1,3}|192\.168|172\.(1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"),
    "tailnet-ip": re.compile(r"\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"),
    "public-ipv4": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),  # filtered by _is_public_ipv4
    "home-path": re.compile(r"/(?:var/)?home/[A-Za-z_][A-Za-z0-9_.-]*/"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@(?!example\.)[A-Za-z0-9.-]+\.(com|net|org|io|dev|au)\b"),
}
TEXT_SUFFIXES = {".py", ".md", ".toml", ".yml", ".yaml", ".json", ".svg", ".canvas", ".txt", ".cfg", ".sh", ""}


def publish_set() -> list[Path]:
    """Files git would publish: tracked + untracked, minus ignored. Falls back to a walk without git."""
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(ROOT), "ls-files", "-co", "--exclude-standard", "-z"],  # noqa: S607 - git from PATH
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout
        rels = [p for p in out.decode().split("\0") if p]
    except (OSError, subprocess.SubprocessError):
        rels = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]
    return sorted(ROOT / r for r in rels if (ROOT / r).is_file())


def _is_public_ipv4(text: str) -> bool:
    """Return True for a routable public IPv4 literal; documentation, loopback and unspecified ranges pass."""
    try:
        addr = ipaddress.IPv4Address(text)
    except ipaddress.AddressValueError:
        return False
    allowed = ("127.0.0.0/8", "0.0.0.0/8", "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")
    if any(addr in ipaddress.IPv4Network(n) for n in allowed):
        return False
    return addr.is_global


def hygiene_scan(files: list[Path]) -> list[Finding]:
    """Find secrets and infrastructure addresses in files that would be published."""
    findings: list[Finding] = []
    for f in files:
        if f.suffix not in TEXT_SUFFIXES or f.stat().st_size > MAX_SCAN_BYTES:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            for rule, rx in HYGIENE.items():
                hit = rx.search(line)
                if hit and rule == "public-ipv4":
                    hit = next((m for m in rx.finditer(line) if _is_public_ipv4(m.group(0))), None)
                if hit:
                    findings.append(Finding(f"H-{rule}", str(f.relative_to(ROOT)), n, hit.group(0)[:40]))
    return findings


# ---------------------------------------------------------------- gate runner
@dataclass
class Gate:
    """The outcome of one named gate."""

    name: str
    ok: bool = False
    seconds: float = 0.0
    detail: list[str] = field(default_factory=list)


def tool(name: str) -> list[str]:
    """Prefer a tool already on PATH (CI installs pinned versions); else run the pinned one through uv."""
    if shutil.which(name):
        return [name]
    uv = shutil.which("uv")
    if uv:
        return [uv, "tool", "run", "--from", PINS[name], name]
    msg = f"{name} is not installed and uv is unavailable; install {PINS[name]}"
    raise SystemExit(msg)


def run(argv: list[str], env: dict[str, str] | None = None) -> tuple[int, str]:
    """Run one gate command from the repo root; the audited subprocess door of this module."""
    proc = subprocess.run(  # noqa: S603 - argv list built from fixed tool names, no shell
        argv,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
        env={**os.environ, **(env or {})},
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def g_selftest(g: Gate) -> None:
    """Plant one bad snippet per fitness rule; every rule must fire, and the audited door must pass."""
    for rule, snippet in PLANTED.items():
        fired = {f.rule for f in fitness_scan("collective.py", snippet)}
        g.detail.append(f"{rule}: {'fires' if rule in fired else 'DID NOT FIRE'}")
    planted_ip = ".".join(["8", "8", "8", "8"])  # noqa: FLY002 - built at runtime so this file never holds a public IP literal
    hyg = [
        rule
        for rule, rx in HYGIENE.items()
        for m in rx.finditer(planted_ip)
        if rule != "public-ipv4" or _is_public_ipv4(m.group(0))
    ]
    g.detail.append(f"H-public-ipv4: {'fires' if 'public-ipv4' in hyg else 'DID NOT FIRE'}")
    planted_home = "/".join(["", "var", "home", "someone", "project"])  # noqa: FLY002 - built at runtime so the hygiene gate never sees a home-path literal
    g.detail.append(f"H-home-path: {'fires' if HYGIENE['home-path'].search(planted_home) else 'DID NOT FIRE'}")
    doc_ok = not _is_public_ipv4("192.0.2.10")
    g.detail.append(f"documentation range allowed: {'yes' if doc_ok else 'NO'}")
    clean = fitness_scan("collective.py", "def run():\n    import subprocess\n    subprocess.run(['x'])\n")
    g.detail.append(f"audited door accepted: {'yes' if not clean else 'NO'}")
    g.ok = all("fires" in d for d in g.detail if d.startswith(("F", "H-"))) and doc_ok and not clean


def g_hygiene(g: Gate) -> None:
    """Refuse secrets and infrastructure addresses in the publish set."""
    files = publish_set()
    found = hygiene_scan(files)
    g.detail = [f"{f.rule} {f.path}:{f.line} {f.detail}" for f in found] or [f"{len(files)} files clean"]
    g.ok = not found


def g_fitness(g: Gate) -> None:
    """Apply the architecture rules to every source module."""
    found = [f for s in SOURCES for f in fitness_scan(s, (ROOT / s).read_text(encoding="utf-8"))]
    g.detail = [f"{f.rule} {f.path}:{f.line} {f.detail}" for f in found] or [f"{len(SOURCES)} modules clean"]
    g.ok = not found


def g_cmd(g: Gate, argv: list[str], env: dict[str, str] | None = None) -> None:
    """Pass when an external tool exits 0."""
    rc, out = run(argv, env)
    g.ok = rc == 0
    g.detail = out.splitlines()[-25:] if out else ["(no output)"]


def g_coverage(g: Gate, env: dict[str, str]) -> None:
    """Require the configured fail_under floor in aggregate and for every production module."""
    g_cmd(g, [*tool("coverage"), "report"], env)
    for source in SOURCES:
        rc, out = run([*tool("coverage"), "report", f"--include={source}"], env)
        g.ok = g.ok and rc == 0
        g.detail.append(
            f"{source}: {'meets' if rc == 0 else 'BELOW'} fail_under ({out.splitlines()[-1] if out else rc})"
        )


def main() -> int:
    """Run the gates in order and print one PASS/FAIL line each."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--keep-going", action="store_true")
    ap.add_argument("--receipt", type=Path)
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="collective-gates-"))
    env = {"RUFF_CACHE_DIR": str(tmp / "ruff"), "COVERAGE_FILE": str(tmp / "coverage"), "PYTHONDONTWRITEBYTECODE": "1"}
    plan: list[tuple[str, Callable[[Gate], None]]] = [
        ("selftest", g_selftest),
        ("hygiene", g_hygiene),
        ("fitness", g_fitness),
        ("format", lambda g: g_cmd(g, [*tool("ruff"), "format", "--check", "."], env)),
        ("lint", lambda g: g_cmd(g, [*tool("ruff"), "check", "."], env)),
        ("types", lambda g: g_cmd(g, [*tool("mypy"), "--cache-dir", str(tmp / "mypy")], env)),
        ("security", lambda g: g_cmd(g, [*tool("bandit"), "-q", "-ll", "-c", "pyproject.toml", "-r", *SOURCES], env)),
        (
            "tests",
            lambda g: g_cmd(
                g, [*tool("coverage"), "run", "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py", "-q"], env
            ),
        ),
        ("coverage", lambda g: g_coverage(g, env)),
    ]
    gates: list[Gate] = []
    for name, fn in plan:
        if a.only and name not in a.only:
            continue
        g = Gate(name)
        t0 = time.monotonic()
        fn(g)
        g.seconds = round(time.monotonic() - t0, 2)
        gates.append(g)
        print(f"{'PASS' if g.ok else 'FAIL'}  {name:9} {g.seconds:6.2f}s")
        if not g.ok:
            for line in g.detail:
                print(f"      {line}")
            if not a.keep_going:
                break
    shutil.rmtree(tmp, ignore_errors=True)
    ok = all(g.ok for g in gates) and len(gates) == (len(a.only) or len(plan))
    if a.receipt:
        digest = hashlib.sha256()
        for f in publish_set():
            digest.update(str(f.relative_to(ROOT)).encode() + b"\0" + f.read_bytes())
        a.receipt.write_text(
            json.dumps(
                {
                    "tree_sha256": digest.hexdigest(),
                    "ok": ok,
                    "python": sys.version.split()[0],
                    "gates": [{"name": g.name, "ok": g.ok, "seconds": g.seconds} for g in gates],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    print("ALL GATES PASS" if ok else "GATES FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
