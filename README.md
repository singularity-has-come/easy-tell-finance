# easy-tell-finance

이 문서는 easy-tell-finance CLI를 로컬 및 Colab 환경에서 실행하는 방법을 설명합니다.

## Prerequisites

- Python 3.12 이상
- [uv](https://docs.astral.sh/uv/)

## 로컬 실행

1. 의존성을 설치합니다.

    ```bash
    uv sync
    ```

1. 문장을 변환합니다.

    ```bash
    uv run python cli.py convert --text "..."
    ```

1. 테스트를 실행합니다.

    ```bash
    uv run pytest
    ```

## Colab 실행

1. `notebook.ipynb`을 엽니다.
1. `REPO_URL` 변수를 이 저장소 주소로 바꿉니다.
1. 셀을 순서대로 실행합니다.
