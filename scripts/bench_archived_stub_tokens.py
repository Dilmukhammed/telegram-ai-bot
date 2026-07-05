"""Benchmark archived tool-result stub size using Google's local Gemini tokenizer."""
from __future__ import annotations

import sqlite3
import statistics
from datetime import datetime
from pathlib import Path

from local_tokenizer import DEFAULT_LOCAL_TOKENIZER_MODEL, count_text
from tools.tool_results.archive import archived_content_json
from tools.tool_results.store import StoredToolResult, ToolResultStore

DB = Path("data/tool_results.sqlite")
LOCAL_MODEL = DEFAULT_LOCAL_TOKENIZER_MODEL


def load_records() -> list[StoredToolResult]:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT ref, user_id, run_id, tool_name, turn, args_json, payload_json,
               char_count, summary, summarize_status, summarize_attempts,
               ok, cached, created_at, expires_at
        FROM tool_results
        WHERE summarize_status = 'ok' AND summary IS NOT NULL AND summary != ''
        ORDER BY char_count DESC
        """
    ).fetchall()
    conn.close()
    records: list[StoredToolResult] = []
    for row in rows:
        records.append(
            StoredToolResult(
                ref=row["ref"],
                user_id=row["user_id"],
                run_id=row["run_id"],
                tool_name=row["tool_name"],
                turn=row["turn"],
                args_json=row["args_json"],
                payload_json=row["payload_json"],
                char_count=row["char_count"],
                summary=row["summary"],
                summarize_status=row["summarize_status"],
                summarize_attempts=row["summarize_attempts"],
                ok=bool(row["ok"]),
                cached=bool(row["cached"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                expires_at=datetime.fromisoformat(row["expires_at"]),
            )
        )
    return records


def main() -> None:
    records = load_records()
    if not records:
        print("No summarized rows in tool_results.sqlite")
        return

    stubs = [archived_content_json(r) for r in records]
    summaries = [r.summary or "" for r in records]
    full_payloads = [r.payload_json for r in records]

    stub_tokens = [count_text(stub) for stub in stubs]
    summary_tokens = [count_text(summary) for summary in summaries]
    full_tokens = [count_text(payload) for payload in full_payloads]

    stub_chars = [len(s) for s in stubs]
    summary_chars = [len(s) for s in summaries]
    full_chars = [len(p) for p in full_payloads]

    def stats(label: str, values: list[int]) -> None:
        print(f"  {label:22} mean={statistics.mean(values):6.1f}  median={statistics.median(values):6.0f}  "
              f"p90={sorted(values)[int(len(values) * 0.9) - 1]:4d}  min={min(values):4d}  max={max(values):4d}")

    print(f"tokenizer: google-genai LocalTokenizer ({LOCAL_MODEL}, gemma3 spiece)")
    print(f"rows: {len(records)}")
    print()
    print("=== TOKENS (local, text only) ===")
    stats("archived stub", stub_tokens)
    stats("summary only", summary_tokens)
    stats("full payload", full_tokens)
    print()
    print("=== CHARS ===")
    stats("archived stub", stub_chars)
    stats("summary only", summary_chars)
    stats("full payload", full_chars)
    print()
    print(f"stub/full tokens: {statistics.mean(stub_tokens) / statistics.mean(full_tokens) * 100:.1f}%")
    print(f"stub/full chars:  {statistics.mean(stub_chars) / statistics.mean(full_chars) * 100:.1f}%")
    print(f"chars/token (stub): {statistics.mean(stub_chars) / statistics.mean(stub_tokens):.2f}")
    print()
    print("=== top-5 largest stubs ===")
    ranked = sorted(
        zip(records, stub_tokens, stub_chars, full_tokens, full_chars),
        key=lambda item: item[1],
        reverse=True,
    )
    for record, tok, chars, full_tok, full_c in ranked[:5]:
        print(
            f"  {record.tool_name:40} stub={tok:3} tok ({chars:4} ch)  "
            f"full={full_tok:5} tok ({full_c:6,} ch)"
        )


if __name__ == "__main__":
    main()
