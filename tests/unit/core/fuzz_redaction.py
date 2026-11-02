"""Planted-secret fuzz harness for the RedactionEngine (#261, #264).

Each case concatenates random noise and uniquely tagged FAKE secrets, then
checks that every planted secret is absent from the output of each path:

- ``two_pass``: ``clock_out._redact_text`` (DOTALL patterns first, then per line)
- ``whole``: ``RedactionEngine.redact_content`` on the whole text
- ``copy_and_redact``: the archive path, through a temporary file

Modes:

- ``A``: fragments may abut with no separator (adversarial)
- ``B``: every fragment is followed by at least one separator

Not a test module (no ``test_`` prefix). Reused by
``test_redaction_fuzz_property.py``; run it by hand from the repo root with::

    .venv/bin/python -m tests.unit.core.fuzz_redaction SEED N

Exit status: 0 only when no planted secret survives any path and the two-pass
helper agrees with a whole-text call on every case; 1 otherwise. It is 1 TODAY
because of the known #264 residual classes (bearer/db kinds, seed 261: 418 in
mode A, 58 in mode B). There is deliberately no allow-list flag: #264 spans
whole kinds, so excluding them would also hide any new leak of those kinds.

SYNTHETIC DATA ONLY: every secret is FAKE and assembled at runtime from parts.
"""

from __future__ import annotations

import collections
import random
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from hestai_context_mcp.core.redaction import RedactionEngine
from hestai_context_mcp.tools.clock_out import _redact_text

_DASHES = "-" * 5
SEPARATORS = ["\n", "\r\n", " ", "\t", " ", "\\n", '", "', "\n\n"]
NOISE = [
    "text",
    "mail a" + "@" + "b.org",
    "https://e.test:80/x",
    "BEGIN",
    _DASHES,
    ":",
    "@",
    "{",
    "}",
    "Bearer",
]
KINDS = ["sk", "aws", "gh", "bearer", "db", "db_at", "pk_t", "pk_u", "pk_lower"]
PRIVATE_KEY_KINDS = frozenset({"pk_t", "pk_u", "pk_lower"})
PATHS = ("two_pass", "whole", "copy_and_redact")


def _secret(rng: random.Random, tag: str) -> tuple[str, list[str], str]:
    """Return (fragment, planted cores that must not survive, kind)."""
    kind = rng.choice(KINDS)
    if kind == "sk":
        core = "TESTONLY" + tag + "Q" * 12
        return "sk-" + core, [core], kind
    if kind == "aws":
        core = "AKIA" + "TEST" + tag + "Z" * 7
        return core, [core], kind
    if kind == "gh":
        core = "TESTONLY" + tag + "G" * 23
        return "ghp_" + core, [core], kind
    if kind == "bearer":
        core = "FAKEbearer" + tag + ".val"
        return "Bearer " + core, [core], kind
    if kind in ("db", "db_at"):
        core = "fkPw" + tag + "x9"
        password = core if kind == "db" else "fk@" + core
        return "postgresql://svcuser:" + password + "@db.example.test/app", [core], kind
    body = ["MIIE" + "FAKE" + tag + "A" * 16, "FAKE" + tag + "B" * 20 + "="]
    lower = kind == "pk_lower"
    header = "rsa private" + " key" if lower else "RSA PRIVATE" + " KEY"
    begin = _DASHES + ("begin " if lower else "BEGIN ") + header + _DASHES
    end = _DASHES + ("end " if lower else "END ") + header + _DASHES
    text = begin + "\n" + "\n".join(body) + ("" if kind == "pk_u" else "\n" + end)
    return text, body, kind


@dataclass
class FuzzReport:
    """Counts from one seeded run."""

    seed: int
    mode: str
    cases: int = 0
    differ: int = 0
    leaks: collections.Counter[tuple[str, str]] = field(default_factory=collections.Counter)

    def leak_total(self, path: str, kinds: frozenset[str] | None = None) -> int:
        """Leaked planted secrets on ``path``, optionally limited to ``kinds``."""
        return sum(n for (p, k), n in self.leaks.items() if p == path and (not kinds or k in kinds))


def run(seed: int, n: int, mode: str, workdir: Path) -> FuzzReport:
    """Run ``n`` seeded cases in ``mode`` ("A" or "B"); temp files go in ``workdir``."""
    rng = random.Random(f"{seed}-{mode}")
    report = FuzzReport(seed=seed, mode=mode)
    glue = SEPARATORS + ([""] * 6 if mode == "A" else [])
    src, dst = workdir / "fuzz-src.txt", workdir / "fuzz-dst.txt"
    for i in range(n):
        parts: list[str] = []
        planted: list[tuple[str, str]] = []
        for j in range(rng.randint(1, 8)):
            if rng.random() < 0.45:
                fragment, cores, kind = _secret(rng, f"{i:05d}{j}")
                parts.append(fragment)
                planted += [(core, kind) for core in cores]
            else:
                parts.append(rng.choice(NOISE))
        text = "".join(part + rng.choice(glue) for part in parts)
        two, whole = _redact_text(text), RedactionEngine.redact_content(text)
        src.write_text(text, encoding="utf-8")
        RedactionEngine.copy_and_redact(src, dst)
        outputs = {"two_pass": two, "whole": whole, "copy_and_redact": dst.read_text("utf-8")}
        report.cases += 1
        report.differ += two != whole
        for core, kind in planted:
            for path, out in outputs.items():
                if core in out:
                    report.leaks[(path, kind)] += 1
    return report


def main(argv: list[str]) -> int:
    """CLI: print the per-mode table for SEED and N; exit 1 on any leak or disagreement."""
    seed, n = int(argv[1]), int(argv[2])
    failed = False
    with tempfile.TemporaryDirectory() as tmp:
        for mode in ("A", "B"):
            r = run(seed, n, mode, Path(tmp))
            totals = " ".join(f"leak_{p}={r.leak_total(p)}" for p in PATHS)
            print(f"mode={mode} seed={seed} cases={r.cases} differ={r.differ} {totals}")
            for path in PATHS:
                kinds = {k: r.leaks[(path, k)] for k in KINDS if r.leaks[(path, k)]}
                print(f"   {path:16s} {kinds}")
            failed |= r.differ > 0 or any(r.leak_total(p) > 0 for p in PATHS)
    print("RESULT:", "FAIL (leak or path disagreement)" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
