"""不依赖第三方库的轻量中文题库检索器。"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path


def normalize(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(text)).lower()


def head_of_question(text: str) -> str:
    # 用户粘贴完整选项时，优先拿第一项选项之前的部分与题干比较。
    parts = re.split(r"(?:^|\s)[A-Ha-h][\.、．:：\)）]\s*", text, maxsplit=1)
    return parts[0].strip() or text.strip()


def terms(text: str) -> list[str]:
    norm = normalize(text)
    result: list[str] = []
    # 中文/整体字符二元组对短题和改写题比较稳健。
    if len(norm) == 1:
        result.append(norm)
    else:
        result.extend(norm[i:i + 2] for i in range(len(norm) - 1))
    # 英文缩写、协议名、端口数字保留为完整词。
    result.extend(x.lower() for x in re.findall(r"[A-Za-z][A-Za-z0-9_+./-]*|\d+", text))
    return result


@dataclass
class Match:
    score: float
    exact: bool
    question: dict


def load_questions(path: Path) -> list[dict]:
    """读取 JSONL、独立 questions.js，或兼容旧版HTML内嵌题库。"""
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".js":
        marker = re.search(r"(?:window\.)?QUESTION_BANK\s*=", text)
        if not marker:
            raise ValueError(f"JS 中未找到 QUESTION_BANK：{path}")
        questions, _ = json.JSONDecoder().raw_decode(text, marker.end())
        if not isinstance(questions, list):
            raise ValueError(f"JS 题库格式错误：{path}")
        return questions
    if suffix in {".html", ".htm"}:
        marker = re.search(r"\bconst\s+DATA\s*=", text)
        if not marker:
            raise ValueError(f"HTML 中未找到内嵌题库 const DATA：{path}")
        questions, _ = json.JSONDecoder().raw_decode(text, marker.end())
        if not isinstance(questions, list):
            raise ValueError(f"HTML 内嵌题库格式错误：{path}")
        return questions
    return [json.loads(line) for line in text.splitlines() if line.strip()]


class QuestionBank:
    def __init__(self, path: Path):
        self.path = path
        self.questions = load_questions(path)
        self.doc_terms: list[Counter[str]] = []
        document_frequency: defaultdict[str, int] = defaultdict(int)
        for q in self.questions:
            stem = q.get("stem", "")
            options = " ".join((q.get("options") or {}).values())
            # 题干重复一遍，让题干比干扰选项权重更高。
            counts = Counter(terms(stem + " " + stem + " " + options))
            self.doc_terms.append(counts)
            for token in counts:
                document_frequency[token] += 1
        n = max(1, len(self.questions))
        self.idf = {token: math.log((n + 1) / (df + 1)) + 1.0 for token, df in document_frequency.items()}

    def _cosine(self, query: Counter[str], doc: Counter[str]) -> float:
        common = set(query) & set(doc)
        dot = sum(query[t] * doc[t] * self.idf.get(t, 1.0) ** 2 for t in common)
        qnorm = math.sqrt(sum((v * self.idf.get(t, 1.0)) ** 2 for t, v in query.items()))
        dnorm = math.sqrt(sum((v * self.idf.get(t, 1.0)) ** 2 for t, v in doc.items()))
        return dot / (qnorm * dnorm) if qnorm and dnorm else 0.0

    def search(self, query_text: str, limit: int = 6) -> list[Match]:
        query_norm = normalize(query_text)
        head_norm = normalize(head_of_question(query_text))
        query_terms = Counter(terms(query_text))
        scored: list[Match] = []
        for i, q in enumerate(self.questions):
            stem = q.get("stem", "")
            stem_norm = normalize(stem)
            if not stem_norm:
                continue
            exact = bool(
                query_norm == stem_norm
                or (len(stem_norm) >= 8 and stem_norm in query_norm)
                or (len(head_norm) >= 8 and (head_norm in stem_norm or stem_norm in head_norm))
            )
            if exact:
                score = 1.0
            else:
                cosine = self._cosine(query_terms, self.doc_terms[i])
                ratio = SequenceMatcher(None, head_norm, stem_norm, autojunk=False).ratio() if head_norm else 0.0
                score = min(0.99, 0.72 * cosine + 0.28 * ratio)
            if score >= 0.12:
                scored.append(Match(score=score, exact=exact, question=q))
        scored.sort(key=lambda x: (x.score, x.exact), reverse=True)
        return scored[:limit]


def format_context(matches: list[Match], reliable_threshold: float) -> tuple[str, bool]:
    if not matches:
        return "未检索到候选题。", False
    reliable = matches[0].exact or matches[0].score >= reliable_threshold
    # 弱匹配只给前三条；可靠匹配可给更多相关改写题供模型核验。
    chosen = matches if reliable else matches[:3]
    blocks: list[str] = []
    for idx, match in enumerate(chosen, 1):
        q = match.question
        opts = q.get("options") or {}
        answer_letters = q.get("answer") or []
        answer_text = "；".join(f"{x}. {opts.get(x, '')}" for x in answer_letters)
        option_text = "\n".join(f"{k}. {v}" for k, v in opts.items())
        blocks.append(
            f"[候选{idx} | 相似度 {match.score:.3f}{' | 题干命中' if match.exact else ''}]\n"
            f"题目：{q.get('stem', '')}\n{option_text}\n"
            f"标准答案：{answer_text or ''.join(answer_letters)}\n"
            f"解析：{q.get('explanation', '') or '无'}"
        )
    return "\n\n".join(blocks), reliable
