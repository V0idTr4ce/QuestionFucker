"""Offline replay: python tests/audit_plain_text.py <test-records.jsonl>."""
import collections
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from retrieval import QuestionBank


def main(path):
    rows = [json.loads(line) for line in Path(path).read_text("utf-8-sig").splitlines() if line.strip()]
    bank = QuestionBank(ROOT / "data" / "questions.js")
    formats = {
        "stem_only": lambda r: r["stem"],
        "multiline": lambda r: r["stem"] + "\n" + "\n".join(f"{k}. {v}" for k, v in r["options"].items()),
        "compact": lambda r: r["stem"] + "".join(f"{k}.{v}" for k, v in r["options"].items()),
    }
    result = {name: collections.Counter() for name in formats}
    details = []
    start = time.monotonic()
    for row in rows:
        item = {"idx": row["idx"], "stem": row["stem"]}
        for name, to_text in formats.items():
            # JSONL is only the test data source: search receives one plain string.
            matches = bank.search(to_text(row), 6)
            top = matches[0] if matches else None
            category = "exact" if top and top.exact else "strong" if top and top.score >= 0.55 else "weak" if top else "none"
            result[name][category] += 1
            item[name] = {"category": category, "score": round(top.score, 3) if top else None,
                          "top_stem": top.question["stem"] if top else None}
        details.append(item)
    output = {"count": len(rows), "summary": result, "elapsed_seconds": round(time.monotonic() - start, 1), "cases": details}
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python tests/audit_plain_text.py <test-records.jsonl>")
    main(sys.argv[1])
