import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import load_glossary, process_paragraph  # noqa: E402


def test_load_glossary_smoke():
    glossary = load_glossary()
    assert len(glossary) > 0


def test_process_paragraph_smoke():
    glossary = load_glossary()
    result = process_paragraph("본 대출의 DSR은 40%입니다.", glossary)
    assert "status" in result
    assert "text" in result
