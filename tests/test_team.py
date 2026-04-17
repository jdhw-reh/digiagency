"""Tests for team record Redis helpers and team management API."""
import pytest
import pytest_asyncio
from datetime import datetime


# ---------------------------------------------------------------------------
# Unit tests — team record functions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_team_returns_team_id(patch_redis):
    import state
    team_id = await state.create_team("owner@example.com")
    assert isinstance(team_id, str)
    assert len(team_id) == 36  # UUID4


@pytest.mark.asyncio
async def test_create_team_creates_record(patch_redis):
    import state
    team_id = await state.create_team("owner@example.com")
    team = await state.get_team(team_id)
    assert team is not None
    assert team["owner_email"] == "owner@example.com"
    assert team["members"] == []
    assert team["max_seats"] == 5
    assert team["team_id"] == team_id


@pytest.mark.asyncio
async def test_get_team_by_owner(patch_redis):
    import state
    team_id = await state.create_team("owner@example.com")
    team = await state.get_team_by_owner("owner@example.com")
    assert team is not None
    assert team["team_id"] == team_id


@pytest.mark.asyncio
async def test_add_team_member_success(patch_redis):
    import state
    team_id = await state.create_team("owner@example.com")
    ok = await state.add_team_member(team_id, "member@example.com")
    assert ok is True
    team = await state.get_team(team_id)
    assert len(team["members"]) == 1
    assert team["members"][0]["email"] == "member@example.com"
    assert "joined_at" in team["members"][0]


@pytest.mark.asyncio
async def test_add_team_member_at_max_seats(patch_redis):
    import state
    team_id = await state.create_team("owner@example.com")
    # Owner occupies 1 seat; max_seats=5 means 4 more allowed
    for i in range(4):
        ok = await state.add_team_member(team_id, f"m{i}@example.com")
        assert ok is True
    # 5th member (owner + 4 members = 5 seats used) should fail
    ok = await state.add_team_member(team_id, "overflow@example.com")
    assert ok is False


@pytest.mark.asyncio
async def test_remove_team_member(patch_redis):
    import state
    team_id = await state.create_team("owner@example.com")
    await state.add_team_member(team_id, "member@example.com")
    await state.remove_team_member(team_id, "member@example.com")
    team = await state.get_team(team_id)
    assert team["members"] == []


@pytest.mark.asyncio
async def test_get_member_count(patch_redis):
    import state
    team_id = await state.create_team("owner@example.com")
    assert await state.get_member_count(team_id) == 1  # owner counts
    await state.add_team_member(team_id, "m1@example.com")
    assert await state.get_member_count(team_id) == 2


# ---------------------------------------------------------------------------
# Unit tests — account team helpers + join request functions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_and_get_account_team(patch_redis):
    import state
    await state.save_account("user@example.com", {
        "email": "user@example.com",
        "subscription_status": "active",
    })
    await state.set_account_team("user@example.com", "team-123", "owner")
    result = await state.get_account_team("user@example.com")
    assert result == ("team-123", "owner")


@pytest.mark.asyncio
async def test_get_account_team_none_when_not_set(patch_redis):
    import state
    await state.save_account("user@example.com", {"email": "user@example.com"})
    result = await state.get_account_team("user@example.com")
    assert result is None


@pytest.mark.asyncio
async def test_create_join_request_returns_token(patch_redis):
    import state
    token = await state.create_join_request(
        "DIGI-TEST", "owner@example.com", "team-123",
        "member@example.com", "Jane Smith"
    )
    assert isinstance(token, str)
    assert len(token) > 20


@pytest.mark.asyncio
async def test_get_join_request(patch_redis):
    import state
    token = await state.create_join_request(
        "DIGI-TEST", "owner@example.com", "team-123",
        "member@example.com", "Jane Smith"
    )
    req = await state.get_join_request(token)
    assert req is not None
    assert req["requester_email"] == "member@example.com"
    assert req["status"] == "pending"
    assert "email_action_token" in req


@pytest.mark.asyncio
async def test_get_pending_requests_for_owner(patch_redis):
    import state
    await state.create_join_request(
        "DIGI-TEST", "owner@example.com", "team-123",
        "m1@example.com", "M1"
    )
    await state.create_join_request(
        "DIGI-TEST", "owner@example.com", "team-123",
        "m2@example.com", "M2"
    )
    requests = await state.get_pending_requests_for_owner("owner@example.com")
    assert len(requests) == 2
    emails = {r["requester_email"] for r in requests}
    assert "m1@example.com" in emails


@pytest.mark.asyncio
async def test_resolve_join_request(patch_redis):
    import state
    token = await state.create_join_request(
        "DIGI-TEST", "owner@example.com", "team-123",
        "member@example.com", "Jane"
    )
    await state.resolve_join_request(token, "approved")
    req = await state.get_join_request(token)
    assert req["status"] == "approved"
    # Removed from pending set
    pending = await state.get_pending_requests_for_owner("owner@example.com")
    assert len(pending) == 0


# ---------------------------------------------------------------------------
# Integration tests — team API routes
# ---------------------------------------------------------------------------

import asyncio
from tests.conftest import register_user, login_user, get_csrf_from_response


async def setup_agency_owner(client, email="owner@test.com"):
    """Register + activate as agency owner with a team and workspace code."""
    await register_user(client, email)
    import state
    import secrets as _secrets
    account = await state.get_account(email)
    account["subscription_status"] = "active"
    account["plan"] = "agency"
    raw = _secrets.token_urlsafe(4).upper()
    workspace_code = f"{raw[:4]}-{raw[4:]}"
    account["workspace_code"] = workspace_code
    await state.redis_client.setex(f"workspace_code:{workspace_code}", 86400, email)
    team_id = await state.create_team(email)
    account["team_id"] = team_id
    account["team_role"] = "owner"
    await state.save_account(email, account)
    return workspace_code, team_id


@pytest.mark.asyncio
async def test_request_access_happy_path(client):
    workspace_code, team_id = await setup_agency_owner(client, "owner@test.com")
    await register_user(client, "requester@test.com")
    import state as _state
    req_acct = await _state.get_account("requester@test.com")
    req_acct["subscription_status"] = "active"
    req_acct["plan"] = "pro"
    await _state.save_account("requester@test.com", req_acct)
    login_resp = await login_user(client, "requester@test.com")
    csrf = get_csrf_from_response(login_resp)

    resp = await client.post(
        "/api/team/request-access",
        json={"workspace_code": workspace_code, "requester_name": "Jane"},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "Request sent" in data["message"]


@pytest.mark.asyncio
async def test_request_access_invalid_code(client):
    await register_user(client, "user@test.com")
    import state
    acct = await state.get_account("user@test.com")
    acct["subscription_status"] = "active"
    await state.save_account("user@test.com", acct)
    login_resp = await login_user(client, "user@test.com")
    csrf = get_csrf_from_response(login_resp)

    resp = await client.post(
        "/api/team/request-access",
        json={"workspace_code": "FAKE-CODE", "requester_name": "Jane"},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_owner_pending_requests(client):
    workspace_code, team_id = await setup_agency_owner(client, "owner@test.com")
    await register_user(client, "req@test.com")

    import state
    await state.create_join_request(workspace_code, "owner@test.com", team_id, "req@test.com", "Req")
    account = await state.get_account("req@test.com")
    account["subscription_status"] = "pending_team"
    await state.save_account("req@test.com", account)

    owner_login = await login_user(client, "owner@test.com")
    csrf = get_csrf_from_response(owner_login)
    resp = await client.get("/api/team/pending-requests", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["requester_email"] == "req@test.com"


@pytest.mark.asyncio
async def test_approve_member(client):
    workspace_code, team_id = await setup_agency_owner(client, "owner@test.com")
    await register_user(client, "newmember@test.com")

    import state
    token = await state.create_join_request(
        workspace_code, "owner@test.com", team_id, "newmember@test.com", "New"
    )
    nm_acct = await state.get_account("newmember@test.com")
    nm_acct["subscription_status"] = "pending_team"
    await state.save_account("newmember@test.com", nm_acct)

    owner_login = await login_user(client, "owner@test.com")
    csrf = get_csrf_from_response(owner_login)
    resp = await client.post(f"/api/team/approve/{token}", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200, resp.text

    nm_acct = await state.get_account("newmember@test.com")
    assert nm_acct["subscription_status"] == "active"
    assert nm_acct["team_id"] == team_id
    assert nm_acct["team_role"] == "member"


@pytest.mark.asyncio
async def test_deny_member(client):
    workspace_code, team_id = await setup_agency_owner(client, "owner@test.com")
    await register_user(client, "denied@test.com")

    import state
    token = await state.create_join_request(
        workspace_code, "owner@test.com", team_id, "denied@test.com", "Denied"
    )
    d_acct = await state.get_account("denied@test.com")
    d_acct["subscription_status"] = "pending_team"
    await state.save_account("denied@test.com", d_acct)

    owner_login = await login_user(client, "owner@test.com")
    csrf = get_csrf_from_response(owner_login)
    resp = await client.post(f"/api/team/deny/{token}", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200

    d_acct = await state.get_account("denied@test.com")
    assert d_acct["subscription_status"] == "inactive"


@pytest.mark.asyncio
async def test_get_team_owner(client):
    workspace_code, team_id = await setup_agency_owner(client, "owner@test.com")
    owner_login = await login_user(client, "owner@test.com")
    csrf = get_csrf_from_response(owner_login)
    resp = await client.get("/api/team", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    data = resp.json()
    assert data["owner_email"] == "owner@test.com"
    assert data["your_role"] == "owner"
    assert data["workspace_code"] == workspace_code


@pytest.mark.asyncio
async def test_get_team_not_on_team(client):
    await register_user(client, "solo@test.com")
    import state
    acct = await state.get_account("solo@test.com")
    acct["subscription_status"] = "active"
    await state.save_account("solo@test.com", acct)
    login_resp = await login_user(client, "solo@test.com")
    csrf = get_csrf_from_response(login_resp)
    resp = await client.get("/api/team", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 404
