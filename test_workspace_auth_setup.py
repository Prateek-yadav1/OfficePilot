import pytest

from test_google_apis import LEGACY_TOKEN_FILE, token_file_for_user


def test_user_token_path_defaults_to_private_officepilot_directory(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr("test_google_apis.Path.home", lambda: tmp_path)

    token_file = token_file_for_user("officepilot-local-demo")

    assert token_file == (
        tmp_path
        / ".officepilot"
        / "tokens"
        / "officepilot-local-demo.json"
    )
    assert token_file != LEGACY_TOKEN_FILE.resolve()


def test_user_token_path_rejects_shared_legacy_token():
    with pytest.raises(ValueError, match="shared project token.json"):
        token_file_for_user(
            "officepilot-local-demo",
            str(LEGACY_TOKEN_FILE),
        )
