"""suite 全体の共通 fixture。"""

import pytest

# src が os.environ から読む GitHub 接続先・認証の変数。呼び出し元 shell の値が
# test に漏れると identity probe の分岐が変わる。必要な test は
# monkeypatch.setenv で明示的に入れる (autouse の後に効く)。
AMBIENT_GITHUB_ENV = ("GH_TOKEN", "GITHUB_TOKEN", "GH_HOST")


@pytest.fixture(autouse=True)
def _isolate_ambient_github_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in AMBIENT_GITHUB_ENV:
        monkeypatch.delenv(name, raising=False)
