"""AI operation snapshots and deterministic rollback."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import uuid
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from markinote_api.platform.io import atomic_write_json, resource_lock
from markinote_api.platform.paths import resolve_under_root, validate_storage_id

LOGGER = logging.getLogger(__name__)


class BackupCapacityError(ValueError):
    """Raised before a mutation when its recovery snapshot cannot be retained."""


class RollbackRefusedError(ValueError):
    """A safe, expected rollback refusal with a stable public reason."""

    def __init__(self, reason: str, public_message: str):
        super().__init__(public_message)
        self.reason = reason
        self.public_message = public_message


class BackupManager:
    _OPERATION_METADATA_RESERVE = 64 * 1024

    def __init__(
        self,
        backup_dir,
        library_dir,
        max_count=100,
        max_bytes=256 * 1024 * 1024,
        *,
        active_lease_seconds=10 * 60,
        now: Callable[[], datetime] | None = None,
    ):
        self.backup_dir = Path(backup_dir).resolve()
        self.library_dir = Path(library_dir).resolve()
        self.max_count = max(1, int(max_count))
        self.max_bytes = max(1, int(max_bytes))
        self.active_lease = timedelta(seconds=max(1, int(active_lease_seconds)))
        self._now = now or (lambda: datetime.now(UTC))
        self.owner_id = f'owner_{uuid.uuid4().hex}'
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        # Startup retention also recovers expired active groups left behind by
        # a terminated worker. Live groups from other workers remain leased.
        self.cleanup()

    def _utc_now(self):
        value = self._now()
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

    def _group_dir(self, group_id):
        validate_storage_id(group_id, '备份组 ID')
        return self.backup_dir / group_id

    def _library_path(self, rel_path, *, allow_root=False):
        return resolve_under_root(self.library_dir, rel_path, allow_root=allow_root)[0]

    def create_operation_group(self, conversation_id=None):
        now = self._utc_now()
        group_id = now.strftime('%Y%m%dT%H%M%S%f') + '_' + uuid.uuid4().hex[:8]
        group_dir = self._group_dir(group_id)
        with resource_lock(self.backup_dir), resource_lock(group_dir):
            (group_dir / 'before').mkdir(parents=True, exist_ok=False)
            (group_dir / 'after').mkdir(parents=True, exist_ok=False)
            atomic_write_json(group_dir / 'manifest.json', {
                'version': 3,
                'id': group_id,
                'timestamp': now.isoformat(),
                'conversation_id': conversation_id,
                'state': 'active',
                'owner_id': self.owner_id,
                'lease_until': (now + self.active_lease).isoformat(),
                'quota_reserved_bytes': 0,
                'completed_at': None,
                'operations': [],
            })
        return group_id

    def complete_operation_group(self, group_id):
        """Mark a group terminal so retention may safely remove it.

        Cleanup deliberately ignores active groups.  This matters because
        separate conversations may execute tools concurrently and an older
        group is not necessarily an idle group.
        """
        group_dir = self._group_dir(group_id)
        if not group_dir.is_dir():
            return False
        with resource_lock(self.backup_dir), resource_lock(group_dir):
            if not group_dir.is_dir():
                return False
            manifest = self._load_manifest(group_dir)
            if manifest.get('state') == 'active':
                if not manifest.get('operations'):
                    shutil.rmtree(group_dir)
                    return True
                manifest['state'] = 'completed'
                manifest['owner_id'] = None
                manifest['lease_until'] = None
                manifest['quota_reserved_bytes'] = 0
                manifest['completed_at'] = self._utc_now().isoformat()
                self._save_manifest(group_dir, manifest)
        return True

    def heartbeat_operation_group(self, group_id):
        """Renew ownership while a streamed agent run is still active."""
        group_dir = self._group_dir(group_id)
        with resource_lock(group_dir):
            if not group_dir.is_dir():
                return False
            manifest = self._load_manifest(group_dir)
            if manifest.get('state') != 'active':
                return False
            now = self._utc_now()
            manifest['owner_id'] = self.owner_id
            manifest['lease_until'] = (now + self.active_lease).isoformat()
            self._save_manifest(group_dir, manifest)
            return True

    def backup_before_modify(
        self,
        group_id,
        operation_type,
        rel_path,
        description='',
        *,
        target_path=None,
    ):
        group_dir = self._group_dir(group_id)
        source = self._library_path(rel_path)
        if target_path is not None:
            self._library_path(target_path)

        with resource_lock(self.backup_dir), resource_lock(group_dir):
            manifest = self._load_manifest(group_dir)
            if manifest.get('state', 'completed') != 'active':
                raise ValueError('backup group is no longer active')
            index = len(manifest['operations'])
            snapshot_rel = f'{index:04d}/item'
            snapshot = group_dir / 'before' / snapshot_rel
            has_backup = source.exists()
            snapshot_bytes = self._path_size(source) if has_backup else 0
            previous_reservation = self._non_negative_int(manifest.get('quota_reserved_bytes'))
            projected_usage = self._group_usage(group_dir, manifest) + snapshot_bytes + self._OPERATION_METADATA_RESERVE
            self._ensure_capacity(group_dir, projected_usage)

            now = self._utc_now()
            manifest['owner_id'] = self.owner_id
            manifest['lease_until'] = (now + self.active_lease).isoformat()
            manifest['quota_reserved_bytes'] = projected_usage
            self._save_manifest(group_dir, manifest)
            try:
                if has_backup:
                    self._copy_path(source, snapshot)
            except Exception:
                self._remove_path(snapshot)
                manifest['quota_reserved_bytes'] = previous_reservation
                self._save_manifest(group_dir, manifest)
                raise

            operation = {
                'index': index,
                'type': operation_type,
                'path': rel_path,
                'target_path': target_path,
                'description': description,
                'has_backup': has_backup,
                'snapshot': snapshot_rel if has_backup else None,
                'timestamp': now.isoformat(),
                'rolled_back_at': None,
            }
            manifest['operations'].append(operation)
            self._save_manifest(group_dir, manifest)
            return index

    def backup_after_modify(self, group_id, operation_index, rel_path):
        group_dir = self._group_dir(group_id)
        source = self._library_path(rel_path)
        with resource_lock(group_dir):
            manifest = self._load_manifest(group_dir)
            if manifest.get('state', 'completed') != 'active':
                raise ValueError('backup group is no longer active')
            for operation in manifest.get('operations', []):
                if operation.get('index') == operation_index:
                    self._capture_after_state(operation, source, rel_path)
                    break
            now = self._utc_now()
            manifest['owner_id'] = self.owner_id
            manifest['lease_until'] = (now + self.active_lease).isoformat()
            self._save_manifest(group_dir, manifest)

    def compensate_active_operation(
        self,
        group_id,
        operation_index,
        *,
        observed_path=None,
        require_after_match=False,
    ):
        """Restore the before-image when a mutation cannot be finalized.

        This is intentionally allowed only while the group is active and is
        called under the same library lock as the mutation. If compensation
        itself fails, the manifest retains a verifiable recovery reference.
        """
        group_dir = self._group_dir(group_id)
        with resource_lock(self.library_dir), resource_lock(group_dir):
            if not group_dir.is_dir():
                return False, 'backup group does not exist'
            manifest = self._load_manifest(group_dir)
            if manifest.get('state') != 'active':
                return False, 'backup group is not active'
            operation = next(
                (item for item in manifest.get('operations', []) if item.get('index') == operation_index),
                None,
            )
            if not isinstance(operation, dict):
                return False, 'backup operation does not exist'

            try:
                if require_after_match:
                    self._assert_after_state_unchanged(group_dir, operation)
                self._restore_before_state(group_dir, operation)
            except (OSError, ValueError, KeyError):
                LOGGER.error(
                    "active mutation compensation failed",
                    extra={"backup_group_id": str(group_id)},
                )
                now = self._utc_now()
                operation['command_state'] = 'recovery_required'
                operation['recovery_required_at'] = now.isoformat()
                operation['recovery_error'] = 'before_image_restore_failed'
                if isinstance(observed_path, str) and not isinstance(operation.get('after_path'), str):
                    try:
                        self._capture_after_state(
                            operation,
                            self._library_path(observed_path),
                            observed_path,
                        )
                    except (OSError, ValueError):
                        operation['after_path'] = observed_path
                        operation['after_unverifiable'] = True
                self._save_manifest(group_dir, manifest)
                return False, 'compensation failed; recovery is required'

            now = self._utc_now()
            operation['compensated_at'] = now.isoformat()
            operation['rolled_back_at'] = now.isoformat()
            operation['command_state'] = 'compensated'
            operation.pop('recovery_required_at', None)
            operation.pop('recovery_error', None)
            self._save_manifest(group_dir, manifest)
            return True, 'mutation was compensated from its before-image'

    def prepare_command(self, group_id, operation_index, command_id):
        """Durably bind a command id before applying its filesystem mutation."""
        if not isinstance(command_id, str) or not command_id or len(command_id) > 128:
            raise ValueError('invalid command id')
        group_dir = self._group_dir(group_id)
        with resource_lock(group_dir):
            manifest = self._load_manifest(group_dir)
            if manifest.get('state') != 'active':
                raise ValueError('backup group is no longer active')
            operation = next(
                (item for item in manifest.get('operations', []) if item.get('index') == operation_index),
                None,
            )
            if not isinstance(operation, dict):
                raise ValueError('backup operation does not exist')
            existing = operation.get('command_id')
            if existing not in {None, command_id}:
                raise ValueError('backup operation is already bound to another command')
            operation['command_id'] = command_id
            operation['command_state'] = 'prepared'
            self._save_manifest(group_dir, manifest)

    def mark_command_applied(self, group_id, operation_index, command_id):
        group_dir = self._group_dir(group_id)
        with resource_lock(group_dir):
            manifest = self._load_manifest(group_dir)
            operation = next(
                (item for item in manifest.get('operations', []) if item.get('index') == operation_index),
                None,
            )
            if not isinstance(operation, dict) or operation.get('command_id') != command_id:
                raise ValueError('prepared command operation does not exist')
            if operation.get('command_state') not in {'recovery_required', 'compensated'}:
                operation['command_state'] = 'applied'
            operation['applied_at'] = self._utc_now().isoformat()
            self._save_manifest(group_dir, manifest)

    def record_command_result(self, group_id, operation_index, command_id, result, backup_info):
        group_dir = self._group_dir(group_id)
        with resource_lock(group_dir):
            manifest = self._load_manifest(group_dir)
            operation = next(
                (item for item in manifest.get('operations', []) if item.get('index') == operation_index),
                None,
            )
            if not isinstance(operation, dict) or operation.get('command_id') != command_id:
                raise ValueError('applied command operation does not exist')
            if operation.get('command_state') not in {'recovery_required', 'compensated'}:
                operation['command_state'] = 'applied'
            operation['command_result'] = {
                'result': str(result)[:5000],
                'backup_info': backup_info if isinstance(backup_info, dict) else None,
            }
            self._save_manifest(group_dir, manifest)

    def mark_command_committed(self, group_id, operation_index, command_id):
        group_dir = self._group_dir(group_id)
        with resource_lock(group_dir):
            if not group_dir.is_dir():
                return False
            manifest = self._load_manifest(group_dir)
            operation = next(
                (item for item in manifest.get('operations', []) if item.get('index') == operation_index),
                None,
            )
            if not isinstance(operation, dict) or operation.get('command_id') != command_id:
                return False
            if operation.get('command_state') != 'applied':
                return False
            operation['command_state'] = 'committed'
            operation['command_committed_at'] = self._utc_now().isoformat()
            self._save_manifest(group_dir, manifest)
            return True

    def find_command(self, command_id):
        """Find a prepared/applied command after a journal lease takeover."""
        if not isinstance(command_id, str) or not command_id:
            return None
        with resource_lock(self.backup_dir):
            for group_dir in sorted(self.backup_dir.iterdir(), reverse=True):
                if not group_dir.is_dir() or group_dir.is_symlink() or not (group_dir / 'manifest.json').is_file():
                    continue
                with resource_lock(group_dir):
                    try:
                        manifest = self._load_manifest(group_dir)
                        manifest = self._recover_manifest_if_expired(group_dir, manifest)
                    except (OSError, ValueError):
                        continue
                    for operation in reversed(manifest.get('operations', [])):
                        if not isinstance(operation, dict) or operation.get('command_id') != command_id:
                            continue
                        stored = operation.get('command_result')
                        if not isinstance(stored, dict):
                            stored = {}
                        backup_info = stored.get('backup_info')
                        if not isinstance(backup_info, dict):
                            backup_info = {
                                'type': operation.get('type'),
                                'path': operation.get('path'),
                                'operation_index': operation.get('index'),
                            }
                            if operation.get('target_path'):
                                backup_info['target'] = operation['target_path']
                        state = str(operation.get('command_state') or 'prepared')
                        if state == 'recovery_required':
                            backup_info['recovery_required'] = True
                        return {
                            'backup_group_id': str(manifest.get('id') or group_dir.name),
                            'backup_group_state': str(manifest.get('state') or 'completed'),
                            'backup_lease_until': manifest.get('lease_until'),
                            'backup_lease_active': (
                                manifest.get('state') == 'active'
                                and self._active_group_is_live(manifest, self._utc_now())
                            ),
                            'backup_info': backup_info,
                            'result': str(
                                stored.get('result')
                                or 'A previous worker applied this command before journal finalization.'
                            ),
                            'state': state,
                        }
        return None

    @staticmethod
    def _capture_after_state(operation: dict, source: Path, rel_path: str):
        operation['after_path'] = rel_path
        operation['after_missing'] = not source.exists()
        operation.pop('after_unverifiable', None)
        operation.pop('after_snapshot', None)
        operation.pop('after_fingerprint', None)
        if source.exists():
            operation['after_fingerprint'] = BackupManager._path_fingerprint(source)

    def _restore_before_state(self, group_dir: Path, operation: dict):
        operation_type = operation.get('type')
        target = self._library_path(operation['path'])
        if operation.get('has_backup'):
            snapshot_rel = operation.get('snapshot') or operation['path']
            snapshot = self._snapshot_path(group_dir, 'before', snapshot_rel)
            if not snapshot.exists():
                raise FileNotFoundError('before-operation snapshot does not exist')
            self._restore_snapshot(snapshot, target)
            if operation_type == 'move_item' and operation.get('target_path'):
                self._remove_path(self._library_path(operation['target_path']))
            return
        if operation_type in {'create_file', 'create_folder'}:
            self._remove_path(target)
            return
        raise ValueError('operation has no restorable before-state')

    def rollback_operation(self, group_id, operation_index=None):
        group_dir = self._group_dir(group_id)
        if operation_index is not None and (isinstance(operation_index, bool) or not isinstance(operation_index, int)):
            return False, '操作索引非法'

        # Resolve an expired active lease before taking the library lock. The
        # global order remains backup-root -> group and library -> group,
        # avoiding a root/library lock cycle with snapshot creation.
        with resource_lock(self.backup_dir), resource_lock(group_dir):
            if not group_dir.is_dir():
                return False, '备份不存在'
            manifest = self._load_manifest(group_dir)
            manifest = self._recover_manifest_if_expired(group_dir, manifest)
            if manifest.get('state') == 'active':
                return False, 'backup group is still active; rollback refused'

        with resource_lock(self.library_dir), resource_lock(group_dir):
            # Cleanup takes this same per-group lock. The directory can vanish
            # between the optimistic check above and acquiring the lock.
            if not group_dir.is_dir():
                return False, 'backup group does not exist'
            manifest = self._load_manifest(group_dir)
            if manifest.get('state') == 'active':
                return False, 'backup group became active unexpectedly; rollback refused'
            operations = manifest.get('operations', [])
            if operation_index is not None:
                operations = [op for op in operations if op.get('index') == operation_index]
                if not operations:
                    return False, '操作不存在'

            changed = 0
            warnings = []
            for operation in reversed(operations):
                if operation.get('rolled_back_at'):
                    continue
                try:
                    self._rollback_one(group_dir, operation)
                    operation['rolled_back_at'] = self._utc_now().isoformat()
                    changed += 1
                except RollbackRefusedError as error:
                    LOGGER.warning(
                        "backup rollback refused",
                        extra={
                            "backup_group_id": str(group_id),
                            "rollback_failure_reason": error.reason,
                        },
                    )
                    warnings.append(error.public_message)
                except (OSError, ValueError, KeyError):
                    LOGGER.error(
                        "backup rollback operation failed",
                        extra={
                            "backup_group_id": str(group_id),
                            "rollback_failure_reason": "state_verification_failed",
                        },
                    )
                    warnings.append('rollback refused because the live state could not be verified')

            self._save_manifest(group_dir, manifest)
            if warnings:
                return False, '；'.join(warnings)
            if not changed:
                return True, '操作已经回滚，无需重复执行'
            return True, f'已回滚 {changed} 个操作'

    def get_group_manifest(self, group_id):
        group_dir = self._group_dir(group_id)
        with resource_lock(self.backup_dir), resource_lock(group_dir):
            if not group_dir.is_dir():
                return None
            manifest = self._load_manifest(group_dir)
            return self._recover_manifest_if_expired(group_dir, manifest)

    def _rollback_one(self, group_dir, operation):
        operation_type = operation.get('type')
        target = self._library_path(operation['path'])
        self._assert_after_state_unchanged(group_dir, operation)

        if operation_type == 'move_item' and target.exists():
            raise RollbackRefusedError(
                'live_state_changed',
                'rollback refused: a document changed after the AI operation',
            )

        move_target = operation.get('target_path') if operation_type == 'move_item' else None

        if not operation.get('has_backup'):
            if operation_type in {'create_file', 'create_folder'}:
                self._remove_path(target)
            return

        snapshot_rel = operation.get('snapshot')
        if snapshot_rel:
            snapshot = self._snapshot_path(group_dir, 'before', snapshot_rel)
        else:
            # Read-only compatibility for version-1 backup groups.
            snapshot = self._snapshot_path(group_dir, 'before', operation['path'])
        if not snapshot.exists():
            raise RollbackRefusedError(
                'recovery_snapshot_unavailable',
                'rollback refused: the recovery snapshot is unavailable',
            )

        # Materialize the complete recovery copy before touching live data.
        # The final swap is recoverable even for non-empty directories.
        self._restore_snapshot(snapshot, target)
        if move_target:
            # Restore the source first. A destination-cleanup failure may leave
            # a duplicate, but can no longer lose the only surviving copy.
            self._remove_path(self._library_path(move_target))

    def _restore_snapshot(self, snapshot: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        staging = target.parent / f'.{target.name}.rollback-{token}'
        displaced = target.parent / f'.{target.name}.rollback-current-{token}'
        installed = False
        displaced_live = False
        try:
            self._copy_path(snapshot, staging)
            if target.exists() or target.is_symlink():
                os.replace(target, displaced)
                displaced_live = True
            try:
                os.replace(staging, target)
                installed = True
            except OSError:
                if displaced_live and not target.exists() and not target.is_symlink():
                    os.replace(displaced, target)
                    displaced_live = False
                raise
        finally:
            self._remove_path(staging)
            if installed:
                self._remove_path(displaced)

    def _assert_after_state_unchanged(self, group_dir, operation):
        after_path = operation.get('after_path')
        if not isinstance(after_path, str):
            # Older groups cannot prove that live content is still the exact
            # result produced by the recorded command. Overwriting it would
            # silently destroy later user edits, so upgrades fail closed.
            raise RollbackRefusedError(
                'after_state_unavailable',
                'rollback refused: this older backup cannot verify the current document state',
            )
        current = self._library_path(after_path)
        if operation.get('after_missing'):
            if current.exists():
                raise RollbackRefusedError(
                    'live_state_changed',
                    'rollback refused: a document changed after the AI operation',
                )
            return

        if not current.exists():
            raise RollbackRefusedError(
                'live_state_changed',
                'rollback refused: a document changed after the AI operation',
            )
        expected_fingerprint = operation.get('after_fingerprint')
        if isinstance(expected_fingerprint, str):
            actual_fingerprint = self._path_fingerprint(current)
        else:
            # Read-only compatibility for version-2 groups that stored the
            # complete after-image instead of its content fingerprint.
            snapshot_rel = operation.get('after_snapshot')
            if not isinstance(snapshot_rel, str):
                raise RollbackRefusedError(
                    'after_state_unavailable',
                    'rollback refused: this older backup cannot verify the current document state',
                )
            snapshot = self._snapshot_path(group_dir, 'after', snapshot_rel)
            if not snapshot.exists():
                raise RollbackRefusedError(
                    'after_state_unavailable',
                    'rollback refused: this older backup cannot verify the current document state',
                )
            expected_fingerprint = self._path_fingerprint(snapshot)
            actual_fingerprint = self._path_fingerprint(current)
        if actual_fingerprint != expected_fingerprint:
            raise RollbackRefusedError(
                'live_state_changed',
                'rollback refused: a document changed after the AI operation',
            )

    @staticmethod
    def _snapshot_path(group_dir: Path, area: str, relative_path: str) -> Path:
        if area not in {'before', 'after'} or not isinstance(relative_path, str):
            raise ValueError('invalid snapshot path')
        try:
            return resolve_under_root(Path(group_dir) / area, relative_path, allow_root=False)[0]
        except (FileNotFoundError, ValueError) as error:
            raise ValueError('invalid snapshot path') from error

    @staticmethod
    def _path_fingerprint(path: Path):
        digest = hashlib.sha256()
        if path.is_symlink():
            raise ValueError('symbolic links cannot be fingerprinted')
        if path.is_file():
            digest.update(b'file\0')
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            return digest.hexdigest()
        if not path.is_dir():
            raise ValueError('unsupported resource type')
        digest.update(b'directory\0')
        for item in sorted(path.rglob('*'), key=lambda value: value.as_posix()):
            if item.is_symlink():
                raise ValueError('symbolic links cannot be fingerprinted')
            relative = item.relative_to(path).as_posix().encode('utf-8')
            digest.update(relative)
            digest.update(b'\0directory\0' if item.is_dir() else b'\0file\0')
            if item.is_file():
                with item.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _non_negative_int(value):
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    @staticmethod
    def _timestamp(value):
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    @classmethod
    def _path_size(cls, path: Path):
        if path.is_symlink():
            raise ValueError('symbolic links cannot be snapshotted')
        if path.is_file():
            return path.stat().st_size
        if not path.is_dir():
            raise ValueError('unsupported snapshot source type')
        total = 0
        for item in path.rglob('*'):
            if item.is_symlink():
                raise ValueError('snapshot directories cannot contain symbolic links')
            if item.is_file():
                total += item.stat().st_size
        return total

    def _group_usage(self, group_dir: Path, manifest=None):
        manifest = manifest if isinstance(manifest, dict) else self._load_manifest(group_dir)
        return max(
            self._tree_size(group_dir),
            self._non_negative_int(manifest.get('quota_reserved_bytes')),
        )

    def _ensure_capacity(self, current_group: Path, projected_usage: int):
        """Reserve space, evicting only older terminal groups.

        The caller owns both the backup-root and current-group locks. Keeping
        the source live until this succeeds makes destructive tools fail closed.
        """
        if projected_usage > self.max_bytes:
            raise BackupCapacityError(
                f'recovery snapshot needs {projected_usage} bytes; backup quota is {self.max_bytes} bytes'
            )

        total_usage = projected_usage
        terminal_groups: list[tuple[Path, int]] = []
        for path in sorted(self.backup_dir.iterdir()):
            if path == current_group or not path.is_dir() or path.is_symlink():
                continue
            if not (path / 'manifest.json').is_file():
                continue
            try:
                manifest = self._load_manifest(path)
                usage = self._group_usage(path, manifest)
            except (OSError, ValueError) as error:
                LOGGER.error(
                    "backup quota verification failed",
                    extra={"backup_group_id": path.name},
                )
                raise BackupCapacityError(
                    "backup storage cannot be verified; mutation was not applied"
                ) from error
            total_usage += usage
            if (
                manifest.get('state', 'completed') != 'active'
                and not self._manifest_requires_recovery(manifest)
            ):
                terminal_groups.append((path, usage))

        for path, measured_usage in terminal_groups:
            if total_usage <= self.max_bytes:
                break
            with resource_lock(path):
                try:
                    if not path.is_dir() or not (path / 'manifest.json').is_file():
                        total_usage -= measured_usage
                        continue
                    manifest = self._load_manifest(path)
                    if (
                        manifest.get('state', 'completed') == 'active'
                        or self._manifest_requires_recovery(manifest)
                    ):
                        continue
                    actual_usage = self._group_usage(path, manifest)
                    shutil.rmtree(path)
                    total_usage -= actual_usage
                except (OSError, ValueError):
                    continue

        if total_usage > self.max_bytes:
            raise BackupCapacityError(
                'backup quota is occupied by active or recovery-required operations; '
                'mutation was not applied'
            )

    def _active_group_is_live(self, manifest: dict, now: datetime):
        lease_until = self._timestamp(manifest.get('lease_until'))
        if lease_until is None:
            created_at = self._timestamp(manifest.get('timestamp'))
            lease_until = created_at + self.active_lease if created_at else None
        return lease_until is not None and lease_until > now

    @staticmethod
    def _manifest_requires_recovery(manifest: dict) -> bool:
        """Keep recovery evidence until an operator resolves it explicitly."""
        if manifest.get('state') == 'quarantined' or bool(manifest.get('integrity_error')):
            return True
        if bool(manifest.get('recovery_required')):
            return True
        operations = manifest.get('operations', [])
        if not isinstance(operations, list):
            return True
        if any(not isinstance(operation, dict) for operation in operations):
            return True
        return any(
            (
                operation.get('command_state') in {'prepared', 'applied', 'recovery_required'}
                or bool(operation.get('recovery_required'))
                or bool(operation.get('recovery_error'))
                or bool(operation.get('recovery_required_at'))
            )
            for operation in operations
        )

    def _recover_expired_group(self, group_dir: Path, manifest: dict, now: datetime):
        integrity_error: str | None = None
        try:
            for operation in manifest.get('operations', []):
                if not isinstance(operation, dict):
                    raise ValueError('operation entry is invalid')
                if operation.get('has_backup'):
                    snapshot_rel = operation.get('snapshot') or operation.get('path')
                    if not isinstance(snapshot_rel, str):
                        raise ValueError('operation snapshot path is invalid')
                    snapshot = self._snapshot_path(group_dir, 'before', snapshot_rel)
                    if not snapshot.exists():
                        raise FileNotFoundError(f'missing before snapshot for operation {operation.get("index")}')
                    self._path_size(snapshot)
        except (OSError, ValueError, TypeError):
            LOGGER.error(
                "expired backup group failed integrity verification",
                extra={"backup_group_id": group_dir.name},
            )
            integrity_error = 'snapshot_integrity_verification_failed'

        manifest['state'] = 'quarantined' if integrity_error else 'abandoned'
        manifest['owner_id'] = None
        manifest['lease_until'] = None
        manifest['quota_reserved_bytes'] = 0
        manifest['completed_at'] = now.isoformat()
        manifest['recovery_reason'] = 'active lease expired after worker termination'
        if integrity_error:
            manifest['integrity_error'] = integrity_error[:1000]
        self._save_manifest(group_dir, manifest)
        return manifest

    def _recover_manifest_if_expired(self, group_dir: Path, manifest: dict):
        if manifest.get('state', 'completed') != 'active':
            return manifest
        now = self._utc_now()
        if self._active_group_is_live(manifest, now):
            return manifest
        return self._recover_expired_group(group_dir, manifest, now)

    def list_backups(self, limit=50):
        groups: list[dict[str, object]] = []
        with resource_lock(self.backup_dir):
            for group_dir in sorted(self.backup_dir.iterdir(), reverse=True):
                if len(groups) >= limit:
                    break
                manifest_path = group_dir / 'manifest.json'
                if (
                    not group_dir.is_dir()
                    or group_dir.is_symlink()
                    or not manifest_path.is_file()
                ):
                    continue
                with resource_lock(group_dir):
                    try:
                        if not group_dir.is_dir() or not manifest_path.is_file():
                            continue
                        manifest = self._load_manifest(group_dir)
                        groups.append(self._recover_manifest_if_expired(group_dir, manifest))
                    except (OSError, ValueError):
                        continue
        return groups

    def delete_conversation_backups(self, conversation_id):
        if not conversation_id:
            return 0
        removed = 0
        with resource_lock(self.backup_dir):
            for group_dir in self.backup_dir.iterdir():
                manifest_path = group_dir / 'manifest.json'
                if not group_dir.is_dir() or group_dir.is_symlink() or not manifest_path.is_file():
                    continue
                with resource_lock(group_dir):
                    try:
                        # Revalidate under the same lock used by rollback.
                        if not group_dir.is_dir() or not manifest_path.is_file():
                            continue
                        manifest = self._load_manifest(group_dir)
                        manifest = self._recover_manifest_if_expired(group_dir, manifest)
                        if (
                            manifest.get('conversation_id') == conversation_id
                            and manifest.get('state', 'completed') != 'active'
                            and not self._manifest_requires_recovery(manifest)
                        ):
                            shutil.rmtree(group_dir)
                            removed += 1
                    except (OSError, ValueError):
                        continue
        return removed

    def cleanup(self, max_count=None, max_bytes=None):
        max_count = self.max_count if max_count is None else max(1, int(max_count))
        max_bytes = self.max_bytes if max_bytes is None else max(1, int(max_bytes))
        with resource_lock(self.backup_dir):
            groups = []
            now = self._utc_now()
            for path in sorted(self.backup_dir.iterdir()):
                if not path.is_dir() or path.is_symlink() or not (path / 'manifest.json').is_file():
                    continue
                with resource_lock(path):
                    try:
                        if not path.is_dir() or not (path / 'manifest.json').is_file():
                            continue
                        manifest = self._load_manifest(path)
                        if manifest.get('state', 'completed') == 'active':
                            if self._active_group_is_live(manifest, now):
                                continue
                            manifest = self._recover_expired_group(path, manifest, now)
                        if self._manifest_requires_recovery(manifest):
                            continue
                        groups.append(path)
                    except (OSError, ValueError):
                        continue

            sizes = {path: self._tree_size(path) for path in groups}
            total_size = sum(sizes.values())
            while groups and (len(groups) > max_count or total_size > max_bytes):
                old = groups.pop(0)
                with resource_lock(old):
                    try:
                        # State and existence may have changed while waiting for
                        # a rollback that already owned the group lock.
                        if not old.is_dir() or old.is_symlink():
                            continue
                        manifest = self._load_manifest(old)
                        if (
                            manifest.get('state', 'completed') == 'active'
                            or self._manifest_requires_recovery(manifest)
                        ):
                            continue
                        actual_size = sizes.get(old, self._tree_size(old))
                        shutil.rmtree(old)
                        total_size -= actual_size
                    except (OSError, ValueError):
                        continue

    @staticmethod
    def _copy_path(source: Path, destination: Path):
        if source.is_symlink():
            raise ValueError('不备份符号链接')
        if not source.exists():
            raise FileNotFoundError(f'snapshot source does not exist: {source}')
        if source.is_dir() and any(item.is_symlink() for item in source.rglob('*')):
            raise ValueError('snapshot directories cannot contain symbolic links')
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            shutil.copy2(source, destination)
        elif source.is_dir():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(source, destination, symlinks=False)
        else:
            raise ValueError('unsupported snapshot source type')

    @staticmethod
    def _remove_path(path: Path):
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path)

    @staticmethod
    def _tree_size(path: Path):
        total = 0
        for root, _, files in os.walk(path):
            for name in files:
                with suppress(OSError):
                    total += os.path.getsize(os.path.join(root, name))
        return total

    @staticmethod
    def _save_manifest(group_dir, manifest):
        atomic_write_json(Path(group_dir) / 'manifest.json', manifest)

    @staticmethod
    def _load_manifest(group_dir):
        with open(Path(group_dir) / 'manifest.json', encoding='utf-8') as stream:
            value = json.load(stream)
        if not isinstance(value, dict) or not isinstance(value.get('operations'), list):
            raise ValueError('备份清单格式非法')
        return value
