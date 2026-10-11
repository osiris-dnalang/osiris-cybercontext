"""CyberContext Session AST Firewall & Injection Interceptor.

Protects SQLite agent session history against prompt injection and toxic tool payloads
before state compaction occurs.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


class ASTFirewallViolation(RuntimeError):
    """Raised when an unverified or dangerous payload is caught."""
    pass


@dataclass
class SanitizedTurn:
    raw_content: str
    is_safe: bool
    quarantine_reason: Optional[str] = None
    ast_nodes_count: int = 0


class CyberContextASTFirewall:
    """L0/L1 deterministic firewall for CLI agent transcripts."""

    FORBIDDEN_CALLS = {"exec", "eval", "compile", "__import__"}
    FORBIDDEN_MODULES = {"os.system", "subprocess.call", "subprocess.Popen"}
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
        """Inspects turn text before committing to CyberContext SQLite memory."""
        # 1. Check for blatant regex injection patterns
        for pattern in cls.DANGEROUS_SHELL_PATTERNS:
            if re.search(pattern, content):
                return SanitizedTurn(
                    raw_content=content,
                    is_safe=False,
                    quarantine_reason=f"Dangerous command pattern matched: '{pattern}'",
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
                            )
                return SanitizedTurn(raw_content=content, is_safe=True, ast_nodes_count=node_count)
            except SyntaxError:
                # Normal natural language text with python keywords
                pass

        return SanitizedTurn(raw_content=content, is_safe=True, ast_nodes_count=0)
