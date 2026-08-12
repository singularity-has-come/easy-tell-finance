"""
Easy Finance Switch (쉬운말 스위치) core logic.

Ported from the vault's `easy-finance-demo-v2-20260807/demo.py` feasibility
demo unchanged — Kiwi-validated term detection + rule-based substitution +
3-axis verification loop. See that demo's README/results.md for the design
rationale. No LLM API is called anywhere in this module.
"""

import re
from collections import Counter
from pathlib import Path

from kiwipiepy import Kiwi

GLOSSARY_PATH = Path(__file__).resolve().parent / "data" / "glossary_expanded.md"

NUM_PATTERN = re.compile(r"\d+(?:\.\d+)?\s?(?:%p|%|개월|년|일|점|원)?")

HEDGE_MARKERS = [
    "할 수 있습니다", "될 수 있습니다", "될 수 있어요", "할 수 있어요",
    "될 수도 있습니다", "적용될 수 있습니다", "설정할 수 없습니다",
    "가능성이 있습니다", "예상됩니다",
]

CONDITION_MARKERS = [
    "다만", "단,", "에 한해", "에 한하여", "미만으로", "이상인 경우",
    "하지 않는 한", "제외하고", "경우에 한해", "인 경우에만",
]

# POS tags treated as part of a noun compound span when contiguous
# (no space/particle between them). SL/SH/SN let "DSR", "IC카드"-style
# alphanumeric terms join their neighboring Hangul nouns correctly.
NOUN_TAGS = {"NNG", "NNP", "XSN", "SL", "SH", "SN"}

_kiwi = Kiwi()


# ---------------------------------------------------------------------------
# Stage 0: anchor dictionary loading
# ---------------------------------------------------------------------------

def load_glossary(path=GLOSSARY_PATH):
    """Parse the '원 용어 | 쉬운말 설명 | 출처' tables in glossary_expanded.md.

    Registers both the main term and any parenthetical alias
    (e.g. "DSR (총부채원리금상환비율)") as lookup keys pointing to the
    same entry, so either form can be detected in running text.
    """
    text = Path(path).read_text(encoding="utf-8")
    entries = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 3:
            continue
        term_cell, definition, source = cells
        if term_cell in ("원 용어", ""):
            continue
        m = re.match(r"^(.+?)\s*\((.+)\)$", term_cell)
        if m:
            main_term, alias = m.group(1).strip(), m.group(2).strip()
        else:
            main_term, alias = term_cell, None
        entry = {"term": main_term, "alias": alias, "definition": definition, "source": source}
        entries[main_term] = entry
        if alias:
            entries[alias] = entry
    return entries


# ---------------------------------------------------------------------------
# Stage 1: Kiwi-validated term detection + constrained rewrite
# ---------------------------------------------------------------------------

def _noun_chunks(text):
    """Return maximal runs of contiguous noun-tag tokens (no gap between
    them — i.e. no space, particle, or punctuation) as (start, end) spans.
    """
    tokens = _kiwi.tokenize(text)
    chunks = []
    cur_start = cur_end = None
    for t in tokens:
        if t.tag in NOUN_TAGS:
            if cur_start is not None and t.start == cur_end:
                cur_end = t.start + t.len
            else:
                if cur_start is not None:
                    chunks.append((cur_start, cur_end))
                cur_start, cur_end = t.start, t.start + t.len
        else:
            if cur_start is not None:
                chunks.append((cur_start, cur_end))
            cur_start = cur_end = None
    if cur_start is not None:
        chunks.append((cur_start, cur_end))
    return chunks


def detect_terms(text, glossary):
    """Find non-overlapping glossary term spans, longest match wins at each
    position, then rejected if only part of a larger Kiwi noun-compound
    chunk (see module docstring / vault demo v2 README for the "약정금리"
    false-match story this guards against).
    """
    keys = sorted(glossary.keys(), key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(k) for k in keys))
    chunks = _noun_chunks(text)

    accepted, rejected = [], []
    for m in pattern.finditer(text):
        start, end, term = m.start(), m.end(), m.group(0)
        if " " in term:
            accepted.append((start, end, glossary[term]))
            continue
        chunk = next((c for c in chunks if c[0] <= start and end <= c[1]), None)
        if chunk is None or chunk == (start, end):
            accepted.append((start, end, glossary[term]))
        else:
            rejected.append({
                "term": term, "span": (start, end), "chunk_span": chunk,
                "chunk_text": text[chunk[0]:chunk[1]],
                "reason": (
                    f"'{term}'이(가) 더 큰 명사구 '{text[chunk[0]:chunk[1]]}'의 "
                    f"일부로만 매칭되어 탐지에서 제외됨(복합어 경계 미상)"
                ),
            })
    return accepted, rejected


def split_clauses(definition):
    return [c.strip() for c in re.split(r"(?<=[다요])\.\s*", definition) if c.strip()]


def strip_numeric_examples(clause):
    stripped = NUM_PATTERN.sub("", clause)
    stripped = re.sub(r"\s{2,}", " ", stripped).strip()
    return stripped


def constrained_clause(definition):
    """Return the anchor dictionary's most conservative licensed text: the
    first digit-free clause of the definition. Falls back to a
    numeric-stripped clause (flagged degraded) if none is digit-free."""
    clauses = split_clauses(definition)
    for c in clauses:
        if not re.search(r"\d", c):
            return c, False
    stripped = strip_numeric_examples(clauses[0]) if clauses else ""
    return stripped, True


def substitute(text, matches, mode):
    """mode='full' uses the complete glossary definition (more informative,
    tried first). mode='constrained' uses only the licensed digit-free
    clause (safer, used on retry)."""
    pieces = []
    last = 0
    degraded = False
    for start, end, entry in matches:
        pieces.append(text[last:start])
        if mode == "full":
            gloss = entry["definition"]
        else:
            gloss, was_degraded = constrained_clause(entry["definition"])
            degraded = degraded or was_degraded
        pieces.append(f'{gloss}({entry["term"]})')
        last = end
    pieces.append(text[last:])
    return "".join(pieces), degraded


# ---------------------------------------------------------------------------
# Stage 2: verification loop
# ---------------------------------------------------------------------------

def extract_numbers(text):
    return Counter(t.strip() for t in NUM_PATTERN.findall(text) if t.strip())


def check_axis1_numbers(original, rewritten):
    """① 수치·기간·비율 보존 — deterministic set comparison."""
    orig, new = extract_numbers(original), extract_numbers(rewritten)
    added, dropped = new - orig, orig - new
    reasons = []
    if added:
        reasons.append(f"원문에 없는 수치 토큰이 추가됨: {sorted(added.elements())}")
    if dropped:
        reasons.append(f"원문의 수치 토큰이 누락됨: {sorted(dropped.elements())}")
    return not reasons, reasons


def check_axis2_conditions_heuristic(original, rewritten):
    """② 조건·예외절 누락 — heuristic keyword-survival stand-in, not real
    NLI entailment. See vault demo results.md for the known gap."""
    reasons = []
    for marker in CONDITION_MARKERS:
        if marker in original and marker not in rewritten:
            reasons.append(f"조건/예외 표지 소실 의심(휴리스틱): '{marker}'가 재작성문에서 사라짐")
    return not reasons, reasons


def check_axis3_hedging(original, rewritten):
    """③ 단정 강화 — dictionary match on hedge markers."""
    reasons = []
    for marker in HEDGE_MARKERS:
        if marker in original and marker not in rewritten:
            reasons.append(f"헤지 표현 소실 의심: 원문의 '{marker}'가 재작성문에서 사라짐(단정 강화 가능성)")
    return not reasons, reasons


def verify(original, rewritten):
    ok1, r1 = check_axis1_numbers(original, rewritten)
    ok2, r2 = check_axis2_conditions_heuristic(original, rewritten)
    ok3, r3 = check_axis3_hedging(original, rewritten)
    return (ok1 and ok2 and ok3), r1 + r2 + r3, {"axis1": ok1, "axis2_heuristic": ok2, "axis3": ok3}


# ---------------------------------------------------------------------------
# Orchestration: 1차 치환 → 검증 → (실패 시) 1회 재시도 → (재실패 시) 보류
# ---------------------------------------------------------------------------

def process_paragraph(original, glossary):
    matches, rejected = detect_terms(original, glossary)
    if not matches:
        return {"status": "매칭 용어 없음", "text": original, "attempts": [], "rejected": rejected}

    attempts = []

    text1, degraded1 = substitute(original, matches, mode="full")
    passed1, reasons1, axes1 = verify(original, text1)
    attempts.append({"mode": "full", "text": text1, "passed": passed1, "reasons": reasons1, "axes": axes1, "degraded": degraded1})
    if passed1:
        return {"status": "합격(1차 치환)", "text": text1, "attempts": attempts, "degraded": degraded1, "rejected": rejected}

    text2, degraded2 = substitute(original, matches, mode="constrained")
    passed2, reasons2, axes2 = verify(original, text2)
    attempts.append({"mode": "constrained", "text": text2, "passed": passed2, "reasons": reasons2, "axes": axes2, "degraded": degraded2})
    if passed2:
        status = "합격(재시도, 품질 저하 경고)" if degraded2 else "합격(재시도)"
        return {"status": status, "text": text2, "attempts": attempts, "degraded": degraded2, "rejected": rejected}

    return {"status": "쉬운말 변환 보류", "text": original, "attempts": attempts, "degraded": False, "rejected": rejected}


def print_result(original, result):
    print(f"\n{'=' * 70}")
    print(f"[{result['status']}]")
    print(f"원문: {original}")
    for j, att in enumerate(result["attempts"], 1):
        mark = "PASS" if att["passed"] else "FAIL"
        print(f"  시도 {j} ({att['mode']}) [{mark}]: {att['text']}")
        if att["reasons"]:
            for r in att["reasons"]:
                print(f"    - {r}")
    if not result["attempts"]:
        print(f"  {result['text']}")
    if result["rejected"]:
        print("  [복합어 경계 검사로 탐지 거부된 매칭]")
        for r in result["rejected"]:
            print(f"    - {r['reason']}")
