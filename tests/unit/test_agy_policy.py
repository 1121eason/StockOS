"""Temporary-file tests only; never touches actual AGY settings or launches a model."""

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from valuation_engine.ai.agy_policy import (
    DENIES,
    PolicyBusy,
    PolicyError,
    PolicyRestoreConflict,
    proposed_strict_policy,
    temporary_disabled_hooks,
    temporary_disabled_plugins,
)


@pytest.mark.parametrize("original_exists", [True, False])
@pytest.mark.parametrize("body_error", [False, True])
def test_exact_original_bytes_and_mode_restored_or_new_settings_removed(
    tmp_path, original_exists, body_error
):
    settings = tmp_path / "settings.json"
    journal_dir = tmp_path / "journals"
    original = b'{ "theme":"dark", "language":"zh-TW", "authMethod":"subscription", "permissions":{"allow":["read_file(*)"],"customHint":"preserved"}}\n'
    if original_exists:
        settings.write_bytes(original)
        settings.chmod(0o640)
    receipt = {}
    try:
        with proposed_strict_policy(settings, journal_dir) as receipt:
            current = json.loads(settings.read_bytes())
            assert current["toolPermission"] == "strict"
            assert current["permissions"]["deny"] == list(DENIES)
            assert current["permissions"]["allow"] == []
            assert current["permissions"]["ask"] == []
            assert current["enableTerminalSandbox"] is True
            assert current["allowNonWorkspaceAccess"] is False
            assert current["useG1Credits"] is False
            if original_exists:
                assert current["theme"] == "dark"
                assert current["language"] == "zh-TW"
                assert current["authMethod"] == "subscription"
                assert current["permissions"]["customHint"] == "preserved"
            backup = Path(receipt["backup_path"])
            journal = Path(receipt["recovery_journal"])
            assert backup.read_bytes() == (original if original_exists else b"")
            assert stat.S_IMODE(backup.stat().st_mode) == 0o600
            assert stat.S_IMODE(journal.stat().st_mode) == 0o600
            assert stat.S_IMODE(journal.parent.stat().st_mode) == 0o700
            if body_error:
                raise ValueError("synthetic body failure")
    except ValueError as exc:
        assert body_error and str(exc) == "synthetic body failure"
    assert receipt["restored"] is True
    assert receipt["status"] == "RESTORED"
    assert (
        receipt["restored_sha256"]
        == hashlib.sha256(original if original_exists else b"").hexdigest()
    )
    assert not Path(receipt["owner_lock"]).exists()
    assert not Path(receipt["backup_path"]).exists()
    assert json.loads(Path(receipt["recovery_journal"]).read_text())["status"] == "RESTORED"
    assert settings.exists() == original_exists
    if original_exists:
        assert settings.read_bytes() == original
        assert stat.S_IMODE(settings.stat().st_mode) == 0o640


@pytest.mark.parametrize("change", ["bytes", "mode", "replace_same_bytes", "delete", "symlink"])
def test_parallel_settings_change_never_overwritten_and_recovery_retained(tmp_path, change):
    settings = tmp_path / "settings.json"
    original = b'{"theme":"old"}\n'
    settings.write_bytes(original)
    settings.chmod(0o640)
    foreign = tmp_path / "foreign.json"
    foreign.write_bytes(b'{"foreign":"untouched"}')
    expected_bytes = expected_mode = expected_inode = None
    with pytest.raises(PolicyRestoreConflict, match="RESTORE_CONFLICT") as captured:
        with proposed_strict_policy(settings, tmp_path / "journals") as receipt:
            if change == "bytes":
                settings.write_bytes(b'{"theme":"changed by another application"}')
            elif change == "mode":
                settings.chmod(0o644)
            elif change == "replace_same_bytes":
                replacement = tmp_path / "replacement.json"
                replacement.write_bytes(settings.read_bytes())
                replacement.chmod(stat.S_IMODE(settings.stat().st_mode))
                os.replace(replacement, settings)
            elif change == "delete":
                settings.unlink()
            else:
                settings.unlink()
                settings.symlink_to(foreign)
            if settings.exists():
                expected_bytes = settings.read_bytes()
                expected_mode = stat.S_IMODE(settings.stat().st_mode)
                expected_inode = settings.stat().st_ino
    receipt = captured.value.receipt
    assert receipt["restored"] is False
    assert receipt["status"] == "RESTORE_CONFLICT"
    assert Path(receipt["backup_path"]).read_bytes() == original
    assert Path(receipt["owner_lock"]).is_file()
    assert json.loads(Path(receipt["recovery_journal"]).read_text())["status"] == "RESTORE_CONFLICT"
    if change == "delete":
        assert not settings.exists()
    else:
        assert settings.read_bytes() == expected_bytes
        assert stat.S_IMODE(settings.stat().st_mode) == expected_mode
        assert settings.stat().st_ino == expected_inode
    assert foreign.read_bytes() == b'{"foreign":"untouched"}'


@pytest.mark.parametrize(
    "content", [b"not json", b"[]", b'{"x":1,"x":2}', b'{"x":NaN}', b'{"permissions":[]}']
)
def test_invalid_json_or_configuration_rejected_before_backup(tmp_path, content):
    settings = tmp_path / "settings.json"
    settings.write_bytes(content)
    with pytest.raises(PolicyError), proposed_strict_policy(settings, tmp_path / "journals"):
        pytest.fail("Invalid settings must not yield")
    assert settings.read_bytes() == content
    assert not (tmp_path / "journals").exists()
    assert not list(tmp_path.glob("*.stockos-strict-policy.lock"))


@pytest.mark.parametrize(
    "key",
    [
        "apiKey",
        "access_token",
        "oauth",
        "credential",
        "nestedPassword",
        "clientSecret",
        "Authorization",
        "bearer",
        "private_key",
        "private-key",
    ],
)
def test_credential_like_keys_never_backed_up(tmp_path, key):
    settings = tmp_path / "settings.json"
    original = json.dumps({"nested": [{key: "fake-test-canary"}]}).encode()
    settings.write_bytes(original)
    with (
        pytest.raises(PolicyError, match="CREDENTIAL"),
        proposed_strict_policy(settings, tmp_path / "journals"),
    ):
        pytest.fail("Credential-like settings must not yield")
    assert settings.read_bytes() == original
    assert not (tmp_path / "journals").exists()
    assert not list(tmp_path.glob("*.stockos-strict-policy.lock"))


@pytest.mark.parametrize("link_kind", ["settings", "settings_parent", "journal_dir"])
def test_symlink_paths_rejected(tmp_path, link_kind):
    actual = tmp_path / "actual"
    actual.mkdir()
    target = actual / "settings.json"
    target.write_bytes(b"{}")
    settings, journals = target, tmp_path / "journals"
    if link_kind == "settings":
        settings = tmp_path / "settings-link.json"
        settings.symlink_to(target)
    elif link_kind == "settings_parent":
        directory_link = tmp_path / "parent-link"
        directory_link.symlink_to(actual, target_is_directory=True)
        settings = directory_link / "settings.json"
    else:
        journals = tmp_path / "journal-link"
        journals.symlink_to(actual, target_is_directory=True)
    with pytest.raises(PolicyError, match="SYMLINK"), proposed_strict_policy(settings, journals):
        pytest.fail("Symlink paths must not yield")
    assert target.read_bytes() == b"{}"


def test_fixed_lock_shared_across_different_journal_directories(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_bytes(b"{}")
    with proposed_strict_policy(settings, tmp_path / "journals-one") as first:
        lock = Path(first["owner_lock"])
        original_lock = lock.read_bytes()
        installed = settings.read_bytes()
        with (
            pytest.raises(PolicyBusy, match="EXISTING_POLICY_LOCK"),
            proposed_strict_policy(settings, tmp_path / "journals-two"),
        ):
            pytest.fail("Second writer must not acquire")
        assert lock.read_bytes() == original_lock
        assert settings.read_bytes() == installed
        assert not (tmp_path / "journals-two").exists()
    assert settings.read_bytes() == b"{}"


def test_old_or_foreign_lock_never_stolen(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_bytes(b"{}")
    lock = settings.with_name(settings.name + ".stockos-strict-policy.lock")
    original_lock = b'{"owner":"foreign","pid":999999999}'
    lock.write_bytes(original_lock)
    with pytest.raises(PolicyBusy), proposed_strict_policy(settings, tmp_path / "journals"):
        pytest.fail("Foreign lock must not yield")
    assert lock.read_bytes() == original_lock
    assert settings.read_bytes() == b"{}"


def test_changed_backup_prevents_unverified_restore(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_bytes(b'{"theme":"original"}')
    with pytest.raises(PolicyRestoreConflict):
        with proposed_strict_policy(settings, tmp_path / "journals") as receipt:
            installed = settings.read_bytes()
            Path(receipt["backup_path"]).write_bytes(b"unverified backup")
    assert settings.read_bytes() == installed
    assert Path(receipt["owner_lock"]).exists()
    assert Path(receipt["recovery_journal"]).exists()


def test_replaced_lock_never_removed_and_settings_not_restored_over_foreign_owner(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_bytes(b"{}")
    with pytest.raises(PolicyRestoreConflict):
        with proposed_strict_policy(settings, tmp_path / "journals") as receipt:
            installed = settings.read_bytes()
            lock = Path(receipt["owner_lock"])
            lock.write_bytes(b'{"owner":"foreign"}')
    assert lock.read_bytes() == b'{"owner":"foreign"}'
    assert settings.read_bytes() == installed
    assert Path(receipt["backup_path"]).exists()


def test_keyboard_interrupt_restores_exact_original(tmp_path):
    settings = tmp_path / "settings.json"
    original = b'{"theme":"original"}\n'
    settings.write_bytes(original)
    with pytest.raises(KeyboardInterrupt):
        with proposed_strict_policy(settings, tmp_path / "journals") as receipt:
            raise KeyboardInterrupt()
    assert receipt["restored"] is True
    assert settings.read_bytes() == original


@pytest.mark.parametrize("original_exists", [True, False])
@pytest.mark.parametrize("body_error", [False, True])
def test_hooks_disabled_then_exact_bytes_and_mode_restored(tmp_path, original_exists, body_error):
    hooks = tmp_path / "hooks.json"
    original = b'{ "clawd": {"enabled":true,"PreInvocation":[{"command":"sensitive command not in receipt"}],"PostToolUse":[]}, "already-off":{"enabled":false,"Stop":[]} }\n'
    if original_exists:
        hooks.write_bytes(original)
        hooks.chmod(0o640)
    receipt = {}
    try:
        with temporary_disabled_hooks(hooks, tmp_path / "journals") as receipt:
            installed = json.loads(hooks.read_bytes())
            if original_exists:
                parsed = json.loads(original)
                assert set(installed) == set(parsed)
                for name, definition in parsed.items():
                    assert installed[name] == {**definition, "enabled": False}
            else:
                assert installed == {}
            assert receipt["version"] == "StockOSAGYTemporaryDisabledHooksV1"
            assert receipt["document_kind"] == "hooks"
            assert receipt["global_hooks_modified"] is True
            assert receipt["global_settings_modified"] is False
            assert "sensitive command" not in json.dumps(receipt)
            assert "sensitive command" not in Path(receipt["recovery_journal"]).read_text()
            if body_error:
                raise ValueError("synthetic hook body failure")
    except ValueError as exc:
        assert body_error and str(exc) == "synthetic hook body failure"
    assert receipt["restored"] is True
    assert receipt["backup_removed"] is True
    assert hooks.exists() == original_exists
    if original_exists:
        assert hooks.read_bytes() == original
        assert stat.S_IMODE(hooks.stat().st_mode) == 0o640
    assert not Path(receipt["owner_lock"]).exists()


@pytest.mark.parametrize("change", ["bytes", "mode", "replace", "symlink"])
def test_parallel_hooks_change_not_overwritten(tmp_path, change):
    hooks = tmp_path / "hooks.json"
    original = b'{"clawd":{"PreInvocation":[{"command":"local canary"}]}}\n'
    hooks.write_bytes(original)
    hooks.chmod(0o640)
    foreign = tmp_path / "foreign.json"
    foreign.write_text("{}")
    with pytest.raises(PolicyRestoreConflict) as captured:
        with temporary_disabled_hooks(hooks, tmp_path / "journals"):
            if change == "bytes":
                hooks.write_bytes(b'{"foreign":{"enabled":true}}')
            elif change == "mode":
                hooks.chmod(0o644)
            elif change == "replace":
                replacement = tmp_path / "replacement.json"
                replacement.write_bytes(hooks.read_bytes())
                replacement.chmod(stat.S_IMODE(hooks.stat().st_mode))
                os.replace(replacement, hooks)
            else:
                hooks.unlink()
                hooks.symlink_to(foreign)
            expected = hooks.read_bytes()
            expected_inode = hooks.stat().st_ino
            expected_mode = stat.S_IMODE(hooks.stat().st_mode)
    assert hooks.read_bytes() == expected
    assert hooks.stat().st_ino == expected_inode
    assert stat.S_IMODE(hooks.stat().st_mode) == expected_mode
    receipt = captured.value.receipt
    assert receipt["restored"] is False
    assert Path(receipt["backup_path"]).read_bytes() == original
    assert Path(receipt["owner_lock"]).exists()


@pytest.mark.parametrize(
    "definition",
    [None, [], "command", {"enabled": 1}, {"Stop": "wrong"}, {"PreToolUse": ["wrong"]}],
)
def test_invalid_hook_definition_refused_before_backup(tmp_path, definition):
    hooks = tmp_path / "hooks.json"
    raw = json.dumps({"clawd": definition}).encode()
    hooks.write_bytes(raw)
    with pytest.raises(PolicyError, match="INVALID_HOOK_DEFINITION"):
        with temporary_disabled_hooks(hooks, tmp_path / "journals"):
            pytest.fail("Invalid hooks must not yield")
    assert hooks.read_bytes() == raw
    assert not (tmp_path / "journals").exists()
    assert not list(tmp_path.glob("*.stockos-strict-policy.lock"))


def test_nested_settings_and_hooks_contexts_restore_in_reverse_on_exception(tmp_path):
    settings = tmp_path / "settings.json"
    hooks = tmp_path / "hooks.json"
    original_settings = b'{ "toolPermission":"always-proceed", "theme":"dark" }\n'
    original_hooks = b'{ "clawd":{"enabled":true,"PreInvocation":[{"command":"canary"}]} }\n'
    settings.write_bytes(original_settings)
    hooks.write_bytes(original_hooks)
    with pytest.raises(RuntimeError, match="stop"):
        with proposed_strict_policy(settings, tmp_path / "settings-journal") as settings_receipt:
            strict_settings = settings.read_bytes()
            try:
                with temporary_disabled_hooks(hooks, tmp_path / "hooks-journal") as hooks_receipt:
                    assert json.loads(settings.read_text())["toolPermission"] == "strict"
                    assert json.loads(hooks.read_text())["clawd"]["enabled"] is False
                    raise RuntimeError("stop")
            finally:
                assert hooks.read_bytes() == original_hooks
                assert settings.read_bytes() == strict_settings
    assert settings.read_bytes() == original_settings
    assert hooks.read_bytes() == original_hooks
    assert hooks_receipt["restored"] is settings_receipt["restored"] is True


@pytest.mark.parametrize("body_error", [False, True])
def test_plugins_disabled_with_all_metadata_preserved_then_exact_restore(tmp_path, body_error):
    config = tmp_path / "config.json"
    original = b'{ "theme":"dark", "plugins":{"data-agent":{"enabled":true,"installedFrom":{"url":"https://example.com/package","revision":"abc"},"userSettings":{"dataset":"keep-this-value"},"otherMetadata":[1,2]},"already-off":{"enabled":false,"installedFrom":"local"}} }\n'
    config.write_bytes(original)
    config.chmod(0o640)
    receipt = {}
    try:
        with temporary_disabled_plugins(config, tmp_path / "journals") as receipt:
            current = json.loads(config.read_bytes())
            expected = json.loads(original)
            for definition in expected["plugins"].values():
                definition["enabled"] = False
            assert current == expected
            assert receipt["version"] == "StockOSAGYTemporaryDisabledPluginsV1"
            assert receipt["document_kind"] == "plugins"
            assert receipt["global_plugins_modified"] is True
            assert receipt["global_hooks_modified"] is receipt["global_settings_modified"] is False
            assert "keep-this-value" not in json.dumps(receipt)
            assert "keep-this-value" not in Path(receipt["recovery_journal"]).read_text()
            if body_error:
                raise RuntimeError("synthetic plugin body failure")
    except RuntimeError as exc:
        assert body_error and str(exc) == "synthetic plugin body failure"
    assert config.read_bytes() == original
    assert stat.S_IMODE(config.stat().st_mode) == 0o640
    assert receipt["restored"] is receipt["backup_removed"] is True
    assert not Path(receipt["owner_lock"]).exists()


@pytest.mark.parametrize("original", [None, b"{}", b'{"theme":"keep"}\n'])
def test_absent_plugins_do_not_invent_entries_or_leave_new_configuration(tmp_path, original):
    config = tmp_path / "config.json"
    if original is not None:
        config.write_bytes(original)
    with temporary_disabled_plugins(config, tmp_path / "journals") as receipt:
        assert json.loads(config.read_bytes()) == (json.loads(original) if original else {})
        assert receipt["policy_overrides"]["disabled_plugin_names"] == []
    assert config.exists() == (original is not None)
    if original is not None:
        assert config.read_bytes() == original


@pytest.mark.parametrize(
    "plugins",
    [
        None,
        [],
        "invalid",
        {"data-agent": None},
        {"data-agent": []},
        {"data-agent": {}},
        {"data-agent": {"enabled": 1}},
        {"data-agent": {"enabled": "true"}},
    ],
)
def test_malformed_plugin_configuration_refused_before_backup(tmp_path, plugins):
    config = tmp_path / "config.json"
    original = json.dumps({"plugins": plugins}).encode()
    config.write_bytes(original)
    with pytest.raises(PolicyError, match="INVALID_PLUGIN"):
        with temporary_disabled_plugins(config, tmp_path / "journals"):
            pytest.fail("Malformed plugins must not yield")
    assert config.read_bytes() == original
    assert not (tmp_path / "journals").exists()
    assert not list(tmp_path.glob("*.stockos-strict-policy.lock"))


@pytest.mark.parametrize("change", ["bytes", "replace", "mode"])
def test_parallel_plugin_configuration_change_is_not_overwritten(tmp_path, change):
    config = tmp_path / "config.json"
    original = b'{"plugins":{"data-agent":{"enabled":true}}}\n'
    config.write_bytes(original)
    config.chmod(0o640)
    with pytest.raises(PolicyRestoreConflict) as captured:
        with temporary_disabled_plugins(config, tmp_path / "journals"):
            if change == "bytes":
                config.write_bytes(b'{"plugins":{},"foreign":"preserve"}')
            elif change == "mode":
                config.chmod(0o644)
            else:
                replacement = tmp_path / "replacement.json"
                replacement.write_bytes(config.read_bytes())
                replacement.chmod(stat.S_IMODE(config.stat().st_mode))
                os.replace(replacement, config)
            expected = (
                config.read_bytes(),
                config.stat().st_ino,
                stat.S_IMODE(config.stat().st_mode),
            )
    assert (
        config.read_bytes(),
        config.stat().st_ino,
        stat.S_IMODE(config.stat().st_mode),
    ) == expected
    assert Path(captured.value.receipt["backup_path"]).read_bytes() == original
    assert Path(captured.value.receipt["owner_lock"]).exists()


def test_plugin_credentials_are_refused_before_backup(tmp_path):
    config = tmp_path / "config.json"
    original = b'{"plugins":{"data-agent":{"enabled":true,"userSettings":{"Authorization":"fake-test-only"}}}}'
    config.write_bytes(original)
    with pytest.raises(PolicyError, match="CREDENTIAL"):
        with temporary_disabled_plugins(config, tmp_path / "journals"):
            pytest.fail("Credential-like configuration must not be backed up")
    assert config.read_bytes() == original
    assert not (tmp_path / "journals").exists()


def test_three_global_configuration_contexts_restore_in_reverse_on_exception(tmp_path):
    settings, hooks, config = (
        tmp_path / name for name in ("settings.json", "hooks.json", "config.json")
    )
    originals = (
        b'{"theme":"keep"}',
        b'{"clawd":{"enabled":true}}',
        b'{"plugins":{"data-agent":{"enabled":true}}}',
    )
    for path, raw in zip((settings, hooks, config), originals, strict=True):
        path.write_bytes(raw)
    with pytest.raises(RuntimeError, match="stop all"):
        with proposed_strict_policy(settings, tmp_path / "settings-journal"):
            try:
                with temporary_disabled_hooks(hooks, tmp_path / "hooks-journal"):
                    try:
                        with temporary_disabled_plugins(config, tmp_path / "plugins-journal"):
                            raise RuntimeError("stop all")
                    finally:
                        assert config.read_bytes() == originals[2]
                        assert json.loads(hooks.read_bytes())["clawd"]["enabled"] is False
            finally:
                assert hooks.read_bytes() == originals[1]
                assert json.loads(settings.read_bytes())["toolPermission"] == "strict"
    assert tuple(path.read_bytes() for path in (settings, hooks, config)) == originals
