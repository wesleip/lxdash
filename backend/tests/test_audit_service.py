"""Tests for services.audit_service.log_action."""

from __future__ import annotations

import json

from models.audit_log import AuditLog


def test_log_action_creates_entry(db_session):
    from services.audit_service import log_action

    log_action(
        db_session,
        user_id=1,
        action="container.create",
        resource_type="container",
        resource_name="web01",
        status="success",
    )
    db_session.commit()

    entry = db_session.query(AuditLog).filter_by(resource_name="web01").first()
    assert entry is not None
    assert entry.action == "container.create"
    assert entry.resource_type == "container"
    assert entry.user_id == 1
    assert entry.status == "success"


def test_log_action_serialises_dict_detail(db_session):
    from services.audit_service import log_action

    detail = {"image": "ubuntu/22.04", "profiles": ["default"]}
    log_action(
        db_session,
        user_id=None,
        action="container.create",
        resource_type="container",
        resource_name="web01",
        detail=detail,
    )
    db_session.commit()

    entry = db_session.query(AuditLog).first()
    assert entry.detail is not None
    assert json.loads(entry.detail) == detail


def test_log_action_passes_string_detail_through(db_session):
    from services.audit_service import log_action

    log_action(
        db_session,
        user_id=None,
        action="container.delete",
        resource_type="container",
        resource_name="web01",
        detail="manual delete",
    )
    db_session.commit()

    entry = db_session.query(AuditLog).first()
    assert entry.detail == "manual delete"


def test_log_action_with_failure_status(db_session):
    from services.audit_service import log_action

    log_action(
        db_session,
        user_id=2,
        action="container.start",
        resource_type="container",
        resource_name="db01",
        status="failure",
        detail="timed out after 30s",
    )
    db_session.commit()

    entry = db_session.query(AuditLog).filter_by(resource_name="db01").first()
    assert entry.status == "failure"
    assert entry.detail == "timed out after 30s"


def test_log_action_with_host_id(db_session):
    from services.audit_service import log_action

    log_action(
        db_session,
        user_id=1,
        action="host.register",
        resource_type="host",
        resource_name="lxd-node-1",
        host_id=42,
    )
    db_session.commit()

    entry = db_session.query(AuditLog).first()
    assert entry.host_id == 42
