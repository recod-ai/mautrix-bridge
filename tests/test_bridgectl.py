import argparse
import importlib.machinery
import importlib.util
import sqlite3
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader("bridgectl", str(ROOT / "bin" / "bridgectl"))
_spec = importlib.util.spec_from_loader("bridgectl", _loader)
bc = importlib.util.module_from_spec(_spec)
_loader.exec_module(bc)

SERVER = {"homeserver_domain": "agorae.dedyn.io", "vpn_ip": "10.10.0.2", "owner_mxid": "@ana.souza:agorae.dedyn.io"}

CONFIG = """\
appservice:
    address: http://localhost:29335
    hostname: 0.0.0.0
    port: 29335
    id: slack
    username: slackbot
    as_token: "tok"
    hs_token: "tok2"
    username_template: 'slack_{{.}}'
bridge:
    permissions:
        "agorae.dedyn.io": user
encryption:
    allow: false
    default: false
    appservice: false
    msc4190: false
    allow_key_sharing: false
logging:
    min_level: debug
double_puppet:
    secrets:
        example.com: as_token:foobar
"""

SLOT = {
    "id": "slack-slot-003", "url": "http://10.10.0.3:29335", "as_token": "a", "hs_token": "h",
    "bot_username": "slackbot_s003", "username_template": "slack_s003_{{.}}", "owner_mxid": "@ana.souza:agorae.dedyn.io",
}


def test_pool_config_listens_only_where_the_slot_url_says(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(CONFIG)
    bc.apply_pool_config(f, SLOT, {"homeserver_domain": "agorae.dedyn.io"})
    assert "hostname: 10.10.0.3" in f.read_text()
    assert "0.0.0.0" not in f.read_text()


def test_house_style_key_sharing_and_log_level(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(CONFIG)
    changed = bc.apply_house_style(f, "slack")
    text = f.read_text()
    assert "allow_key_sharing: true" in text
    assert "min_level: info" in text
    assert "log em info" in changed

    quiet = tmp_path / "q.yaml"
    quiet.write_text(CONFIG.replace("min_level: debug", "min_level: warn"))
    bc.apply_house_style(quiet, "slack")
    assert "min_level: warn" in quiet.read_text()  # only lowers debug, never raises a chosen level


def test_double_puppet_secret_is_set_once_and_custom_values_are_kept(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(CONFIG)
    assert bc.apply_double_puppet(f, "agorae.dedyn.io") == "set"
    assert 'agorae.dedyn.io: "as_token:${keyring:as_token}"' in f.read_text()
    assert bc.apply_double_puppet(f, "agorae.dedyn.io") == "already"
    f.write_text(CONFIG.replace("example.com: as_token:foobar", "other.org: as_token:x"))
    assert bc.apply_double_puppet(f, "agorae.dedyn.io") == "custom"


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def set_password(self, service, key, value):
        self.store[(service, key)] = value


def test_harvest_moves_literal_media_keys_but_leaves_generate(tmp_path, monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setattr(bc, "keyring_mod", lambda: fake)
    f = tmp_path / "config.yaml"
    f.write_text("public_media:\n    signing_key: literalvalue\ndirect_media:\n    server_key: generate\nas_token: real\n")
    bc.cmd_harvest({"bridges": {"signal": {"keyring_service": "mautrix-signal"}}}, argparse.Namespace(name="signal", file=str(f), keys=None, prefix=False))
    text = f.read_text()
    assert 'signing_key: "${keyring:signing_key}"' in text
    assert "server_key: generate" in text  # sentinel untouched: a random hex isn't a valid ed25519 key
    assert fake.store[("mautrix-signal", "signing_key")] == "literalvalue"
    assert fake.store[("mautrix-signal", "as_token")] == "real"


def test_quiet_update_is_a_no_op_when_the_version_is_pinned(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "BIN_DIR", tmp_path)
    (tmp_path / "mautrix-slack").write_text("binary")
    monkeypatch.setattr(bc, "read_state", lambda name: {})
    monkeypatch.setattr(bc, "latest_ci", lambda *a: (_ for _ in ()).throw(AssertionError("must not check for updates")))
    monkeypatch.setattr(bc, "latest_release", lambda *a: (_ for _ in ()).throw(AssertionError("must not check for updates")))
    b = {"binary": "mautrix-slack", "repo": "slack", "channel": "ci", "arch": "amd64", "update_cooldown": 0, "auto_update": False}
    rc = bc.cmd_update({"bridges": {"slack": b}}, argparse.Namespace(all=False, name="slack", force=False, quiet=True))
    assert rc == 0


def test_doctor_reports_what_the_review_found(tmp_path):
    b = {"repo": "slack", "channel": "ci", "auto_update": True}
    reg = "io.element.msc4190: true\norg.matrix.msc3202: true\nreceive_ephemeral: true\n"
    results = dict((msg, level) for level, msg in bc.doctor_checks("slack", b, SERVER, CONFIG, reg))
    flat = " | ".join(results)
    assert "appservice.hostname = 0.0.0.0" in flat
    assert "logging.min_level = debug" in flat
    assert "allow_key_sharing não é true" in flat
    assert "sem o namespace de @ana.souza" in flat
    assert "bridge.permissions libera" in flat
    assert "auto_update ligado" in flat


def test_doctor_is_clean_once_everything_is_applied():
    b = {"repo": "slack", "channel": "ci", "auto_update": False}
    cfg = (CONFIG.replace("hostname: 0.0.0.0", "hostname: 10.10.0.2").replace("min_level: debug", "min_level: info")
           .replace("allow_key_sharing: false", "allow_key_sharing: true").replace("allow: false", "allow: true")
           .replace("default: false", "default: true").replace("appservice: false", "appservice: true")
           .replace("msc4190: false", "msc4190: true").replace('        "agorae.dedyn.io": user\n', '')
           .replace("example.com: as_token:foobar", 'agorae.dedyn.io: "as_token:${keyring:as_token}"')
           .replace('as_token: "tok"', 'as_token: "${keyring:as_token}"').replace('hs_token: "tok2"', 'hs_token: "${keyring:hs_token}"'))
    reg = ("io.element.msc4190: true\norg.matrix.msc3202: true\nreceive_ephemeral: true\n"
           "namespaces:\n  users:\n    - exclusive: false\n      regex: '@ana\\.souza:agorae\\.dedyn\\.io'\n")
    levels = [lvl for lvl, msg in bc.doctor_checks("slack", b, SERVER, cfg, reg)]
    assert levels and set(levels) == {"ok"}, bc.doctor_checks("slack", b, SERVER, cfg, reg)


def test_backup_is_consistent_private_and_keeps_only_the_newest(tmp_path):
    src = tmp_path / "slack.db"
    con = sqlite3.connect(src)
    con.execute("create table t (x)")
    con.execute("insert into t values (1)")
    con.commit()
    dest_dir = tmp_path / "backups"
    made = []
    for _ in range(4):
        made.append(bc.backup_database(src, dest_dir, "slack", keep=2))
        time.sleep(1.1)  # names carry a one-second timestamp
    left = sorted(dest_dir.glob("slack-*.db"))
    assert left == made[-2:]
    assert oct(left[0].stat().st_mode & 0o777) == "0o600" and oct(dest_dir.stat().st_mode & 0o777) == "0o700"
    assert sqlite3.connect(left[-1]).execute("select x from t").fetchone() == (1,)


def test_house_style_never_joins_lines(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(CONFIG.replace("    allow_key_sharing: false\n", "    allow_key_sharing: false\n\n    # a comment\n    other: 1\n"))
    bc.apply_house_style(f, "slack")
    assert "    allow_key_sharing: true\n\n    # a comment\n    other: 1\n" in f.read_text()
