"""CLI for easy-tell-finance. Run via `uv run python cli.py convert ...`."""

import argparse
import sys
from pathlib import Path

from core import GLOSSARY_PATH, load_glossary, print_result, process_paragraph


def _convert(args):
    glossary = load_glossary(args.glossary or GLOSSARY_PATH)
    text = Path(args.file).read_text(encoding="utf-8") if args.file else args.text
    if not text:
        sys.exit("--text 또는 --file 중 하나는 필요합니다.")
    print_result(text, process_paragraph(text, glossary))


def main():
    parser = argparse.ArgumentParser(prog="easy-tell", description="금융 약관 쉬운말 치환 CLI")
    parser.add_argument("--glossary", help="용어사전 md 경로 (기본: data/glossary_expanded.md)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_convert = sub.add_parser("convert", help="문장 하나를 쉬운말로 치환")
    p_convert.add_argument("--text", help="변환할 원문")
    p_convert.add_argument("--file", help="원문이 담긴 텍스트 파일 경로")
    p_convert.set_defaults(func=_convert)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
