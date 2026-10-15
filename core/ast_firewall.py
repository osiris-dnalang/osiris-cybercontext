"""CyberContext session-turn screen: regex deny-list plus a Python AST check.

This is a heuristic filter, not a sandbox or a security boundary. It runs two
checks in order:

1. A regex deny-list over the raw text (``; rm -rf``, backticks, ``$(...)``,
   ``/etc/passwd``, ``/etc/shadow``, ``.env``). Most mixed prose-and-code turns
   are caught here, if at all. It also flags harmless text that happens to
   match, such as any mention of a ``.env`` file.
2. If the whole turn parses as Python, an AST walk that flags calls to
   ``exec``, ``eval``, ``compile`` and ``__import__``, and the dotted calls in
   FORBIDDEN_MODULES (``os.system``, ``subprocess.run`` and so on). A turn that
   does not parse as Python skips this check.

Obfuscated payloads get through: string-built names
(``getattr(__builtins__, "ev" + "al")``), aliased imports
(``import os as o; o.system(...)``), encoded strings, and code in other
languages. Nothing is quarantined, compacted or signed here; the caller gets a
SanitizedTurn and decides what to store.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Optional


class ASTFirewallViolation(RuntimeError):
    """Raised when an unverified or dangerous payload is caught."""
    pass


@dataclass
class SanitizedTurn:
    raw_content: str
    is_safe: bool
    quarantine_reason: Optional[str] = None
    ast_nodes_count: int = 0
    detection_layer: Optional[str] = None  # "regex" or "ast" when flagged


def _dotted_name(node: ast.AST) -> str:
    """Return 'a.b.c' for a Name/Attribute chain, or '' for anything else."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


class CyberContextASTFirewall:
    """Heuristic screen for CLI agent transcript turns (regex, then AST)."""

    FORBIDDEN_CALLS = {"exec", "eval", "compile", "__import__"}
    FORBIDDEN_MODULES = {
        "os.system",
        "os.popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.run",
        "subprocess.Popen",
    }
    DANGEROUS_SHELL_PATTERNS = [
        r";\s*rm\s+-rf",
        r"`.*`",
        r"\$\(.*\)",
        r"/etc/shadow",
        r"/etc/passwd",
        r"\.env",
    ]

    @classmethod
    def sanitize_turn(cls, content: str) -> SanitizedTurn:
        """Screens turn text before it would be stored in session memory."""
        # 1. Regex deny-list over the raw text
        for pattern in cls.DANGEROUS_SHELL_PATTERNS:
            if re.search(pattern, content):
                return SanitizedTurn(
                    raw_content=content,
                    is_safe=False,
                    quarantine_reason=f"Dangerous command pattern matched: '{pattern}'",
                    detection_layer="regex",
                )

        # 2. If content looks like python code, parse AST
        if any(kw in content for kw in ["import ", "def ", "class ", "exec(", "eval("]):
            try:
                tree = ast.parse(content)
                node_count = len(list(ast.walk(tree)))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        func_name = ""
                        if isinstance(node.func, ast.Name):
                            func_name = node.func.id
                        elif isinstance(node.func, ast.Attribute):
                            func_name = node.func.attr

                        if func_name in cls.FORBIDDEN_CALLS:
                            return SanitizedTurn(
                                raw_content=content,
                                is_safe=False,
                                quarantine_reason=f"Forbidden dynamic evaluation primitive: '{func_name}()'",
                                ast_nodes_count=node_count,
                                detection_layer="ast",
                            )

                        dotted = _dotted_name(node.func)
                        if dotted in cls.FORBIDDEN_MODULES:
                            return SanitizedTurn(
                                raw_content=content,
                                is_safe=False,
                                quarantine_reason=f"Forbidden system call: '{dotted}()'",
                                ast_nodes_count=node_count,
                                detection_layer="ast",
                            )
                return SanitizedTurn(raw_content=content, is_safe=True, ast_nodes_count=node_count)
            except SyntaxError:
                # Natural-language text that happens to contain Python keywords
                pass

        return SanitizedTurn(raw_content=content, is_safe=True, ast_nodes_count=0)
