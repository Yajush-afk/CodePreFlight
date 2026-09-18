from auth import create_session


def test_invalid_token_does_not_create_session() -> None:
    assert create_session("invalid-token") is None


if __name__ == "__main__":
    test_invalid_token_does_not_create_session()
