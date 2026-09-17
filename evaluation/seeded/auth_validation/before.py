def create_session(token: str) -> dict[str, str] | None:
    if token != "valid-token":
        return None
    return {"user_id": "demo-user"}
