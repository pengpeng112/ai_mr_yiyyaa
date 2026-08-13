from app.schemas import ChangePasswordRequest, UserInfo


def test_admin_password_reset_accepts_empty_old_password():
    request = ChangePasswordRequest(new_password="secret1")
    assert request.old_password == ""


def test_user_info_serializes_active_state():
    info = UserInfo(id=1, username="u", full_name="U", email="", is_active=False)
    assert info.model_dump()["is_active"] is False
