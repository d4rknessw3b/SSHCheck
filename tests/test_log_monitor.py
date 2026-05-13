"""
tests/test_log_monitor.py — Тесты парсинга auth.log строк.
"""
import pytest
from src.log_monitor import parse_line


class TestParseFailedPassword:
    def test_basic_failed(self):
        line = "May 13 12:34:56 server sshd[1234]: Failed password for root from 192.168.1.100 port 54321 ssh2"
        event = parse_line(line)
        assert event is not None
        assert event.event_type == "failed"
        assert event.ip == "192.168.1.100"
        assert event.username == "root"
        assert event.auth_method == "password"
        assert event.port == 54321

    def test_invalid_user_failed(self):
        line = "May 13 12:34:56 server sshd[1234]: Failed password for invalid user admin from 10.0.0.1 port 12345 ssh2"
        event = parse_line(line)
        assert event is not None
        assert event.event_type == "failed"
        assert event.ip == "10.0.0.1"
        assert event.username == "admin"

    def test_failed_publickey(self):
        line = "May 13 12:34:56 server sshd[1234]: Failed publickey for ubuntu from 1.2.3.4 port 9999 ssh2"
        event = parse_line(line)
        assert event is not None
        assert event.auth_method == "publickey"


class TestParseAccepted:
    def test_accepted_password(self):
        line = "May 13 12:34:56 server sshd[1234]: Accepted password for ubuntu from 192.168.1.1 port 22 ssh2"
        event = parse_line(line)
        assert event is not None
        assert event.event_type == "accepted"
        assert event.username == "ubuntu"
        assert event.ip == "192.168.1.1"

    def test_accepted_publickey(self):
        line = "May 13 12:34:56 server sshd[1234]: Accepted publickey for deploy from 5.5.5.5 port 33333 ssh2"
        event = parse_line(line)
        assert event is not None
        assert event.event_type == "accepted"
        assert event.auth_method == "publickey"


class TestParseInvalidUser:
    def test_invalid_user(self):
        line = "May 13 12:34:56 server sshd[1234]: Invalid user testuser from 8.8.8.8 port 45678"
        event = parse_line(line)
        assert event is not None
        assert event.event_type == "invalid_user"
        assert event.ip == "8.8.8.8"
        assert event.username == "testuser"


class TestParseIgnoredLines:
    def test_non_sshd_line(self):
        line = "May 13 12:34:56 server cron[1234]: (root) CMD (test)"
        assert parse_line(line) is None

    def test_empty_line(self):
        assert parse_line("") is None

    def test_unrelated_sshd_line(self):
        line = "May 13 12:34:56 server sshd[1234]: Server listening on 0.0.0.0 port 22."
        assert parse_line(line) is None
