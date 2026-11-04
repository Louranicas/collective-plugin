#!/usr/bin/env python3
"""One gate runner for local.collective: CI, pre-commit and humans run exactly this.

Owner: collective-claude (card Q1/t12). Reviewer: Codex 2. Stdlib only.

    python3 -I tools/check.py                 # all gates, stop at the first failure
    python3 -I tools/check.py --keep-going    # run every gate and report all
    python3 -I tools/check.py --only fitness  # one gate
    python3 -I tools/check.py --receipt R.json

Eleven gates, in order: selftest, hygiene, history, diagrams, fitness, format, lint, types, security,
tests, coverage.
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
SOURCES = (
    "collective.py",
    "heartbeat.py",
    "install_monitor.py",
    "private_files.py",
    "notice_state.py",
    "coordination_jobs.py",
    "install_coordination_jobs.py",
)
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
# Opening an existing path without one of these can block forever on a FIFO (M1, 2026-11-05).
NONBLOCKING_FLAGS = {"O_NONBLOCK", "O_EXCL", "O_DIRECTORY"}
SUBPROCESS_FNS = {"run", "Popen", "call", "check_call", "check_output"}
# The only functions allowed to spawn processes: one audited door per module.
SUBPROCESS_DOORS = {
    "collective.py": {"run"},
    "heartbeat.py": {"run"},
    "install_monitor.py": {"command"},
    "coordination_jobs.py": {"_run"},
}


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
        self.funcs: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    def _add(self, rule: str, node: ast.AST, detail: str) -> None:
        self.findings.append(Finding(rule, self.path, getattr(node, "lineno", 0), detail))

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.stack.append(node.name)
        self.funcs.append(node)
        self.generic_visit(node)
        self.funcs.pop()
        self.stack.pop()

    @override
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.stack.append(node.name)
        self.funcs.append(node)
        self.generic_visit(node)
        self.funcs.pop()
        self.stack.pop()

    def _bindings(self, name: str) -> list[ast.AST]:
        """Every node in the enclosing function that binds ``name`` (any Store, parameter or augmented assign)."""
        out: list[ast.AST] = []
        for node in ast.walk(self.funcs[-1]):
            stored = isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, (ast.Store, ast.Del))
            param = isinstance(node, ast.arg) and node.arg == name
            scoped = isinstance(node, (ast.Global, ast.Nonlocal)) and name in node.names
            if stored or param or scoped:
                out.append(node)
        return out

    def _flag_names(self, expr: ast.AST, before: int, seen: frozenset[str] = frozenset()) -> set[str]:
        """Return the os.O_* names PROVABLY set in a flags expression; anything unproven contributes nothing.

        Sound by refusal, not by data flow: only ``os.O_*`` attributes, ``|`` and ``x if c else y`` (names in
        both branches) are understood. Any other operator (``&``, ``^``, ``~``, ``-``) proves nothing. A local
        name is followed only when the function binds it exactly once, by a plain assignment that appears
        before the call; reassignment, ``|=``, parameters, loops and globals prove nothing.
        """
        if isinstance(expr, ast.Attribute):
            return {expr.attr} if expr.attr.startswith("O_") and _dotted(expr.value) == "os" else set()
        if isinstance(expr, ast.IfExp):
            return self._flag_names(expr.body, before, seen) & self._flag_names(expr.orelse, before, seen)
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.BitOr):
            return self._flag_names(expr.left, before, seen) | self._flag_names(expr.right, before, seen)
        if isinstance(expr, ast.Name) and expr.id not in seen and self.funcs:
            return self._follow(expr.id, before, seen)
        return set()

    def _follow(self, name: str, before: int, seen: frozenset[str]) -> set[str]:
        """Follow a local name only through its single plain assignment, placed before the use."""
        binds = self._bindings(name)
        parent = (
            next(
                (
                    n
                    for n in ast.walk(self.funcs[-1])
                    if isinstance(n, (ast.Assign, ast.AnnAssign))
                    and any(t is binds[0] for t in (n.targets if isinstance(n, ast.Assign) else [n.target]))
                ),
                None,
            )
            if len(binds) == 1
            else None
        )
        if parent is None or parent.value is None or parent.lineno >= before:
            return set()
        return self._flag_names(parent.value, parent.lineno, seen | {name})

    def _check_open(self, node: ast.Call) -> None:
        flags = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "flags"), None)
        if flags is None:
            return
        names = self._flag_names(flags, node.lineno)
        if "O_EXCL" in names and "O_CREAT" not in names:
            names.discard("O_EXCL")  # O_EXCL without O_CREAT is undefined and does not refuse an existing FIFO
        if not names & NONBLOCKING_FLAGS:
            self._add(
                "F6-blocking-open",
                node,
                "os.open without a provable O_NONBLOCK, O_CREAT|O_EXCL or O_DIRECTORY can block forever on a "
                "FIFO; write the flags as one os.O_* | ... expression or one prior assignment, open non-blocking, "
                "fstat S_ISREG, then set_blocking(True)",
            )

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
        if name == "os.open":
            self._check_open(node)
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
    "F6-blocking-open": (
        "import os\ndef read(p):\n    flags = os.O_RDONLY | os.O_NOFOLLOW\n    return os.open(p, flags)\n"
    ),
}
# Snippets every rule must accept (guards against over-firing).
ACCEPTED = (
    "def run():\n    import subprocess\n    subprocess.run(['x'])\n",
    "import os\ndef read(p):\n    return os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)\n",
    "import os\ndef new(p):\n    return os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)\n",
    "import os\ndef read(p):\n    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK\n    return os.open(p, flags)\n",
    "import os\ndef d(p):\n    return os.open(p, os.O_RDONLY | (os.O_DIRECTORY if p else os.O_DIRECTORY))\n",
)
# Negative controls: each of these can block on a FIFO and F6 must fire on every one (C2 review, 2026-11-05).
F6_NEGATIVE = {
    "conditional-ifexp": (
        "import os\ndef w(p, x):\n    f = os.O_WRONLY | (os.O_EXCL if x else 0)\n    return os.open(p, f)\n"
    ),
    "overwritten": (
        "import os\ndef f(p):\n    fl = os.O_RDONLY | os.O_NONBLOCK\n    fl = os.O_RDONLY\n    return os.open(p, fl)\n"
    ),
    "assigned-after": (
        "import os\ndef f(p):\n    fl = os.O_RDONLY\n    fd = os.open(p, fl)\n    fl = os.O_NONBLOCK\n    return fd\n"
    ),
    "conditional-augassign": (
        "import os\ndef f(p, c):\n    fl = os.O_RDONLY\n    if c:\n        fl |= os.O_NONBLOCK\n"
        "    return os.open(p, fl)\n"
    ),
    "masked": "import os\ndef f(p):\n    return os.open(p, (os.O_RDONLY | os.O_NONBLOCK) & ~os.O_NONBLOCK)\n",
    "excl-without-creat": "import os\ndef f(p):\n    return os.open(p, os.O_RDONLY | os.O_EXCL)\n",
    "parameter": "import os\ndef f(p, fl=os.O_NONBLOCK):\n    return os.open(p, fl)\n",
    "loop-rebound": ("import os\ndef f(ps):\n    for fl in (os.O_NONBLOCK, os.O_RDONLY):\n        os.open(ps, fl)\n"),
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


def _git(*args: str, text: bool = True) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "-C", str(ROOT), *args],  # noqa: S607 - git from PATH
        capture_output=True,
        check=True,
        timeout=60,
        text=text,
    )


ZERO_SHA = re.compile(r"\A0+\Z")
PRE_PUSH_FIELDS = 4  # <local ref> <local sha> <remote ref> <remote sha>
BATCH_HEADER_FIELDS = 3  # <sha> <type> <size>


def _rev_args(push_refs: str | None, base: str | None) -> list[list[str]]:
    """Return one rev-list argument set per range a push or check must cover; fail closed when unsure.

    push_refs is git's pre-push stdin (``<local ref> <local sha> <remote ref> <remote sha>`` per line):
    every outgoing ref is scanned (branches, tags, new refs) with its ENTIRE history, not only HEAD
    and with no remote-based exclusion. Without push refs, scan base..HEAD; with no resolvable base, scan all of HEAD.
    """
    if push_refs is not None:
        ranges: list[list[str]] = []
        for line in push_refs.splitlines():
            parts = line.split()
            if not parts:
                continue
            if len(parts) != PRE_PUSH_FIELDS:
                msg = f"unparseable pre-push line: {line[:80]!r}"
                raise ValueError(msg)
            if ZERO_SHA.match(parts[1]):
                continue  # a delete publishes nothing
            # Scan the ENTIRE history of each outgoing tip. Excluding what remotes hold is unsound:
            # an unrelated remote (a private mirror) may hold a secret the target remote never had.
            ranges.append([parts[1]])
        return ranges
    if base:
        return [[f"{base}..HEAD"]]
    return [["HEAD"]]


def history_blobs(push_refs: str | None = None, base: str | None = None) -> list[tuple[str, bytes]]:
    """Return (label, bytes) for every blob, commit and tag object the scanned ranges would publish."""
    if str(_git("rev-parse", "--is-shallow-repository").stdout).strip() == "true":
        msg = "shallow clone: history is incomplete (fetch full depth)"
        raise ValueError(msg)
    objs: dict[str, str] = {}
    for args in _rev_args(push_refs, base):
        for line in str(_git("rev-list", "--objects", *args).stdout).splitlines():
            sha, _, path = line.partition(" ")
            objs.setdefault(sha, path)
    if not objs:
        return []
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "-C", str(ROOT), "cat-file", "--batch"],  # noqa: S607 - git from PATH
        input=("\n".join(objs) + "\n").encode(),
        capture_output=True,
        check=True,
        timeout=120,
    )
    out: list[tuple[str, bytes]] = []
    buf, pos = proc.stdout, 0
    for sha, path in objs.items():
        end = buf.index(b"\n", pos)
        header = buf[pos:end].split()
        if len(header) != BATCH_HEADER_FIELDS or header[0].decode() != sha:
            msg = f"cat-file --batch desynchronised at {sha[:8]}"
            raise ValueError(msg)
        kind, size = header[1].decode(), int(header[2])
        data = buf[end + 1 : end + 1 + size]
        pos = end + 2 + size
        if kind == "blob":
            out.append((f"{path}@{sha[:8]}", data))
        elif kind in {"commit", "tag"}:
            # Scan the message, not the header: author and tagger identities are git metadata.
            out.append((f"{kind}-message@{sha[:8]}", data.partition(b"\n\n")[2]))
    return out


def history_scan(blobs: list[tuple[str, bytes]]) -> list[Finding]:
    """Apply the hygiene rules to every historical blob (a deleted secret is still published)."""
    findings: list[Finding] = []
    for label, data in blobs:
        if len(data) > MAX_SCAN_BYTES:
            continue
        for n, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            for rule, rx in HYGIENE.items():
                hit = rx.search(line)
                if hit and rule == "public-ipv4":
                    hit = next((m for m in rx.finditer(line) if _is_public_ipv4(m.group(0))), None)
                if hit:
                    findings.append(Finding(f"HH-{rule}", label, n, hit.group(0)[:40]))
    return findings


MERMAID = re.compile(r"^(```|~~~)[ \t]*mermaid\b.*?^\1", re.DOTALL | re.MULTILINE)
RECEIPT_KEYS = {"source": str, "source_sha256": str, "diagram": int, "svg": str, "sha256": str}


def _contained(vault: Path, rel: object, under: str = "") -> Path | None:
    """Resolve a receipt path inside the vault (or one subfolder); None for escapes, symlinks or junk."""
    if not isinstance(rel, str) or not rel or rel.startswith("/") or "\\" in rel:
        return None
    root = (vault / under).resolve()
    path = vault / rel
    if path.is_symlink() or any(p.is_symlink() for p in path.parents if vault in p.parents or p == vault):
        return None
    resolved = path.resolve()
    return resolved if resolved.is_relative_to(root) and resolved.is_file() else None


def _receipt_problems(vault: Path, i: int, r: object, seen: dict[str, list[int]], svgs: set[Path]) -> list[str]:
    """Check one receipt entry; record its source index and SVG for the uniqueness checks."""
    if not isinstance(r, dict) or set(r) != set(RECEIPT_KEYS):
        return [f"D-bad-receipt entry {i}: needs exactly {sorted(RECEIPT_KEYS)}"]
    if not all(isinstance(r[k], t) and not isinstance(r[k], bool) for k, t in RECEIPT_KEYS.items()):
        return [f"D-bad-receipt entry {i}: wrong field types"]
    out: list[str] = []
    src, svg = _contained(vault, r["source"]), _contained(vault, r["svg"], "Assets")
    seen.setdefault(r["source"], []).append(r["diagram"])
    if src is None or hashlib.sha256(src.read_bytes()).hexdigest() != r["source_sha256"]:
        out.append(f"D-stale-source {r['source']} (diagram {r['diagram']}): re-render and update the receipt")
    if svg is None or hashlib.sha256(svg.read_bytes()).hexdigest() != r["sha256"]:
        out.append(f"D-svg-mismatch {r['svg']} (must be a regular file under Assets/)")
    elif svg in svgs:
        out.append(f"D-svg-reused {r['svg']}")
    else:
        svgs.add(svg)
    return out


def diagram_scan(vault: Path) -> list[str]:
    """Require exactly one matching receipt per Mermaid diagram.

    Indices are 1-based and unique per source; source and SVG must be contained regular files whose
    hashes still match; a missing or malformed receipt fails whenever the vault holds a diagram.
    """
    counts: dict[str, int] = {}
    for md in sorted(vault.rglob("*.md")):
        n = len(MERMAID.findall(md.read_text(encoding="utf-8")))
        if n:
            counts[str(md.relative_to(vault))] = n
    receipt_path = vault / "Assets" / "render-receipt.json"
    if not receipt_path.is_file() or receipt_path.is_symlink():
        return [f"D-no-receipt Assets/render-receipt.json: {sum(counts.values())} diagram(s)"] if counts else []
    try:
        receipts = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        return [f"D-bad-receipt unparseable: {exc}"]
    if not isinstance(receipts, list):
        return ["D-bad-receipt not a list"]
    problems: list[str] = []
    seen: dict[str, list[int]] = {}
    svgs: set[Path] = set()
    for i, r in enumerate(receipts):
        problems += _receipt_problems(vault, i, r, seen, svgs)
    for rel in sorted(set(counts) | set(seen)):
        want, got = list(range(1, counts.get(rel, 0) + 1)), sorted(seen.get(rel, []))
        if got != want:
            problems.append(f"D-unreceipted {rel}: diagrams {want}, receipts {got} (need each index exactly once)")
    return problems


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
    for case, snippet in F6_NEGATIVE.items():
        fired = {f.rule for f in fitness_scan("collective.py", snippet)}
        g.detail.append(f"F6 {case}: {'fires' if 'F6-blocking-open' in fired else 'DID NOT FIRE'}")
    for case, refused in _diagram_controls().items():
        if case == "accepted":
            g.detail.append(f"accepted diagram receipt passes: {'NO' if refused else 'yes'}")
        else:
            g.detail.append(f"D {case}: {'fires' if refused else 'DID NOT FIRE'}")
    over = [f.rule for snippet in ACCEPTED for f in fitness_scan("collective.py", snippet)]
    clean = not over
    g.detail.append(f"accepted snippets pass: {'yes' if clean else 'NO ' + ','.join(over)}")
    g.ok = (
        all("fires" in d for d in g.detail if d.startswith(("F", "H-", "D ")))
        and doc_ok
        and clean
        and not any(d.endswith(": NO") for d in g.detail)
    )


def _diagram_controls() -> dict[str, bool]:
    """Plant each known false-green receipt shape in a scratch vault; True means the scan refused it."""
    out: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="collective-d-") as tmp:
        vault = Path(tmp) / "vault"
        (vault / "Assets").mkdir(parents=True)
        md = vault / "doc.md"
        md.write_text("```mermaid\ngraph TD\nA-->B\n```\n~~~mermaid\ngraph TD\nB-->C\n~~~\n", encoding="utf-8")
        for n in (1, 2):
            (vault / "Assets" / f"d{n}.svg").write_text(f"<svg>{n}</svg>", encoding="utf-8")
        (Path(tmp) / "outside.svg").write_text("<svg>1</svg>", encoding="utf-8")
        (vault / "Assets" / "link.svg").symlink_to(vault / "Assets" / "d1.svg")

        def entry(n: int, svg: str) -> dict[str, object]:
            data = (vault / svg).read_bytes() if (vault / svg).exists() else b""
            return {
                "source": "doc.md",
                "source_sha256": hashlib.sha256(md.read_bytes()).hexdigest(),
                "diagram": n,
                "svg": svg,
                "sha256": hashlib.sha256(data).hexdigest(),
            }

        good = [entry(1, "Assets/d1.svg"), entry(2, "Assets/d2.svg")]
        cases: dict[str, object] = {
            "duplicate-index": [good[0], good[0]],
            "outside-vault": [good[0], {**good[1], "svg": "../outside.svg", "sha256": good[0]["sha256"]}],
            "symlink-svg": [good[0], {**good[1], "svg": "Assets/link.svg", "sha256": good[0]["sha256"]}],
            "bad-shape": [good[0], {**good[1], "diagram": "2"}],
            "accepted": good,
        }
        receipt = vault / "Assets" / "render-receipt.json"
        out["missing-receipt"] = bool(diagram_scan(vault))
        for case, body in cases.items():
            receipt.write_text(json.dumps(body), encoding="utf-8")
            out[case] = bool(diagram_scan(vault))
    return out


def g_hygiene(g: Gate) -> None:
    """Refuse secrets and infrastructure addresses in the publish set."""
    files = publish_set()
    found = hygiene_scan(files)
    g.detail = [f"{f.rule} {f.path}:{f.line} {f.detail}" for f in found] or [f"{len(files)} files clean"]
    g.ok = not found


def g_history(g: Gate) -> None:
    """Refuse secrets in any object a push would publish.

    Scope: every outgoing ref under the pre-push hook, else COLLECTIVE_PUSH_BASE..HEAD or
    @{upstream}..HEAD, else all of HEAD. Unscannable history (shallow, bad base) means FAIL.
    """
    push_refs = os.environ.get("COLLECTIVE_PUSH_REFS")
    base = os.environ.get("COLLECTIVE_PUSH_BASE") or None
    if push_refs is None and base is None:
        try:
            _git("rev-parse", "--verify", "--quiet", "@{upstream}")
            base = "@{upstream}"
        except (OSError, subprocess.SubprocessError):
            base = None  # detached or no upstream (CI): scan all of HEAD
    try:
        blobs = history_blobs(push_refs, base)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        g.ok = False
        g.detail = [f"history unscannable ({type(exc).__name__}: {str(exc)[:120]}); refusing"]
        return
    found = history_scan(blobs)
    scope = "outgoing refs" if push_refs is not None else (f"{base}..HEAD" if base else "all of HEAD")
    g.detail = [f"{f.rule} {f.path}:{f.line} {f.detail}" for f in found] or [f"{len(blobs)} objects clean ({scope})"]
    g.ok = not found


def g_diagrams(g: Gate) -> None:
    """Require every rendered diagram to match its Mermaid source (render receipts)."""
    problems = diagram_scan(ROOT / "Collective.vault")
    g.detail = problems or ["all diagram receipts match"]
    g.ok = not problems


def g_fitness(g: Gate) -> None:
    """Apply the architecture rules to every source module."""
    missing = [s for s in SOURCES if not (ROOT / s).is_file()]
    present = {p.name for p in ROOT.glob("*.py") if not p.name.startswith("test_")}
    unlisted = sorted(present - set(SOURCES))
    found = [f for s in SOURCES if s not in missing for f in fitness_scan(s, (ROOT / s).read_text(encoding="utf-8"))]
    g.detail = [f"{f.rule} {f.path}:{f.line} {f.detail}" for f in found]
    g.detail += [f"F0-sources {s}: listed in SOURCES but missing" for s in missing]
    g.detail += [f"F0-sources {s}: runtime module not in SOURCES, so no gate covers it" for s in unlisted]
    g.ok = not (found or missing or unlisted)
    g.detail = g.detail or [f"{len(SOURCES)} modules clean"]


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
        ("history", g_history),
        ("diagrams", g_diagrams),
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
