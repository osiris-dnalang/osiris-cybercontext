"""Tamper-evident evidence ledger (SQLite + SHA-256 hash chain).

Zero-dependency append-only log used by the demo and the evidence workbench.

What verify_integrity() detects: a block edited in place without recomputing
its hash and every later hash (for example a direct SQL UPDATE of one row), and
gaps or re-ordering in the sequence.

What it does not detect: anyone with write access to the database can rewrite a
block and recompute the rest of the chain, and the result verifies as intact.
There is no signature and no external anchor, so a passing check means "this
file is internally consistent", not "this history is authentic".
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


def canonical_json(data: Any) -> str:
    """Serialize to deterministic JSON: sorted keys, compact separators.

    Modeled on RFC 8785 (JCS) but not a full implementation: number formatting
    and the ordering of some non-ASCII keys can differ, and values JSON can't
    represent are stringified via ``default=str``.
    """
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def compute_sha256(text: str | bytes) -> str:
    if isinstance(text, str):
        text = text.encode("utf-8")
    return hashlib.sha256(text).hexdigest()


@dataclass
class LedgerRecord:
    entry_id: int
    prev_hash: str
    timestamp: float
    domain: str
    action: str
    payload_digest: str
    metric_data: Dict[str, Any]
    current_hash: str


class EvidenceLedger:
    """SQLite-backed append-only hash chain."""

    GENESIS_HASH = "0" * 64

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self._init_db()

    def _init_db(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ledger (
                entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                prev_hash TEXT NOT NULL,
                timestamp REAL NOT NULL,
                domain TEXT NOT NULL,
                action TEXT NOT NULL,
                payload_digest TEXT NOT NULL,
                metric_json TEXT NOT NULL,
                current_hash TEXT NOT NULL
            )
        """)
        self.conn.commit()

    def get_latest_hash(self) -> Tuple[int, str]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT entry_id, current_hash FROM ledger ORDER BY entry_id DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            return row[0], row[1]
        return 0, self.GENESIS_HASH

    def append(
        self,
        domain: str,
        action: str,
        payload_data: Any,
        metric_data: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ) -> LedgerRecord:
        last_id, prev_hash = self.get_latest_hash()
        new_id = last_id + 1
        now = timestamp if timestamp is not None else time.time()

        payload_digest = compute_sha256(canonical_json(payload_data))
        metrics = metric_data or {}
        metric_str = canonical_json(metrics)

        preimage = f"{prev_hash}:{new_id}:{now:.4f}:{domain}:{action}:{payload_digest}:{metric_str}"
        current_hash = compute_sha256(preimage)

        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO ledger (entry_id, prev_hash, timestamp, domain, action, payload_digest, metric_json, current_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (new_id, prev_hash, now, domain, action, payload_digest, metric_str, current_hash))
        self.conn.commit()

        return LedgerRecord(
            entry_id=new_id,
            prev_hash=prev_hash,
            timestamp=now,
            domain=domain,
            action=action,
            payload_digest=payload_digest,
            metric_data=metrics,
            current_hash=current_hash,
        )

    def verify_integrity(self) -> Tuple[bool, Optional[str]]:
        self.conn.row_factory = sqlite3.Row
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM ledger ORDER BY entry_id ASC")
        rows = cursor.fetchall()
        self.conn.row_factory = None

        if not rows:
            return True, "Ledger is empty (valid genesis state)."

        expected_prev = self.GENESIS_HASH
        for idx, row in enumerate(rows, start=1):
            if row["entry_id"] != idx:
                return False, f"Sequence break: expected #{idx}, got #{row['entry_id']}"
            if row["prev_hash"] != expected_prev:
                return False, f"Chain linkage break at block #{idx}"

            preimage = f"{row['prev_hash']}:{row['entry_id']}:{row['timestamp']:.4f}:{row['domain']}:{row['action']}:{row['payload_digest']}:{row['metric_json']}"
            recomputed = compute_sha256(preimage)
            if recomputed != row["current_hash"]:
                return False, f"Data tampering detected at block #{idx}: computed {recomputed[:12]} != stored {row['current_hash'][:12]}"

            expected_prev = row["current_hash"]

        return True, f"All {len(rows)} blocks verified successfully. Hash chain is intact."

    def chain_digest(self) -> str:
        """SHA-256 over the ordered block hashes joined with ':'.

        One digest that summarizes the whole chain. It is not a Merkle tree
        root: there is no tree and no inclusion proof.
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT current_hash FROM ledger ORDER BY entry_id ASC")
        hashes = [r[0] for r in cursor.fetchall()]

        if not hashes:
            return self.GENESIS_HASH
        combined = ":".join(hashes)
        return compute_sha256(combined)

    def get_merkle_root(self) -> str:
        """Deprecated alias for chain_digest(); the value is not a Merkle root."""
        return self.chain_digest()

    def merkle_root(self) -> str:
        """Deprecated alias for chain_digest(); the value is not a Merkle root."""
        return self.chain_digest()

    def fetch_chain(self) -> List[Dict[str, Any]]:
        """Fetch all ledger blocks as dictionaries."""
        self.conn.row_factory = sqlite3.Row
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM ledger ORDER BY entry_id ASC")
        rows = [dict(r) for r in cursor.fetchall()]
        self.conn.row_factory = None
        return rows

    def close(self):
        self.conn.close()
