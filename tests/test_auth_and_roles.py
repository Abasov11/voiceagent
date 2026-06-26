def _seed_user(session, email, role, password="topsecret"):
    from shared.auth import hash_password
    from shared.models import DashboardUser

    u = DashboardUser(
        email=email,
        password_hash=hash_password(password),
        full_name=email.split("@")[0],
        role=role,
        is_active=True,
    )
    session.add(u)
    session.commit()
    return u, password


def test_login_bad_password(client, session):
    _seed_user(session, "owner@example.com", "owner")
    r = client.post(
        "/dashboard/login",
        data={"email": "owner@example.com", "password": "wrong"},
    )
    assert r.status_code == 400


def test_login_owner_can_access_users(client, session):
    _, pwd = _seed_user(session, "owner@example.com", "owner")
    r = client.post(
        "/dashboard/login",
        data={"email": "owner@example.com", "password": pwd},
        follow_redirects=False,
    )
    assert r.status_code == 303
    cookie = r.cookies.get("voiceagent_session")
    assert cookie
    r2 = client.get("/dashboard/users", cookies={"voiceagent_session": cookie})
    assert r2.status_code == 200


def test_manager_blocked_from_users(client, session):
    _, pwd = _seed_user(session, "manager@example.com", "manager")
    r = client.post(
        "/dashboard/login",
        data={"email": "manager@example.com", "password": pwd},
        follow_redirects=False,
    )
    cookie = r.cookies.get("voiceagent_session")
    r2 = client.get("/dashboard/users", cookies={"voiceagent_session": cookie})
    assert r2.status_code == 403


def test_manager_blocked_from_zvonar_page(client, session):
    _, pwd = _seed_user(session, "manager@example.com", "manager")
    r = client.post(
        "/dashboard/login",
        data={"email": "manager@example.com", "password": pwd},
        follow_redirects=False,
    )
    cookie = r.cookies.get("voiceagent_session")
    r2 = client.get("/dashboard/zvonar", cookies={"voiceagent_session": cookie})
    assert r2.status_code == 403
