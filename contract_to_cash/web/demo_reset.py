"""Confirmed archive-only reset, serialized with readers and bounded workers."""

from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4
from .store import StoreError


def reset_preview(store):
    root = store.settings.root
    return dict(
        epoch=store.enterprise.epoch(),
        investigations=len(store.metadata()),
        analyses=len(store.enterprise.analyses()),
        enterprise_decisions=len(store.enterprise.decisions()),
        will_archive="All active investigation journals, human operational decisions, analytical snapshots/results, scenarios and management/executive decisions. Prior archives remain retained.",
        will_preserve="Synthetic dataset, administrator pricing and registered source authority, server API credentials and launcher settings. Imported read-only recordings are not removed.",
        permanent_deletion_supported=False,
        active=bool(store.active or (store.worker and store.worker.is_alive())),
    )


def archive_demo(store, body):
    if store.settings.mode != "operator":
        raise StoreError(403, "Recorded mode is read-only")
    with store.lock:
        if store.active or (store.worker and store.worker.is_alive()):
            raise StoreError(
                409,
                "Wait for the active investigation or analysis to finish; reset never interrupts paid work",
            )
        if not store.accepting_launches:
            raise StoreError(503, "Workspace is shutting down or requires recovery")
        if body.expected_epoch != store.enterprise.epoch():
            raise StoreError(409, "Workspace already changed; review the reset scope again")
        root = store.settings.root
        preview = reset_preview(store)
        archive_id = uuid4().hex
        archive = root / "archives" / archive_id
        archive.mkdir(parents=True, exist_ok=False)
        names = ["index", "analyses", "enterprise.sqlite3"] + [
            p.name
            for p in root.iterdir()
            if p.is_dir() and len(p.name) == 32 and all(c in "0123456789abcdef" for c in p.name)
        ]
        moves = [(root / n, archive / n) for n in names if (root / n).exists()]
        if any(store.settings.data.resolve().is_relative_to(src.resolve()) for src, _ in moves):
            raise StoreError(
                409, "The source dataset overlaps active history; reset is refused to preserve it"
            )
        if any(src.is_symlink() for src, _ in moves):
            raise StoreError(409, "Symlinked history cannot be reset safely")
        marker = root / ".reset-recovery.json"
        manifest = dict(
            archive_id=archive_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            reviewer=store.settings.reviewer,
            confirmed=True,
            previous_epoch=store.enterprise.epoch(),
            epoch=uuid4().hex,
            scope=preview,
            moves=[src.name for src, _ in moves],
            state="preparing",
        )
        marker.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (archive / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        completed = []
        try:
            for src, dst in moves:
                src.replace(dst)
                completed.append((src, dst))
            store.index.mkdir(exist_ok=True)
            admin = root / "admin"
            admin.mkdir(exist_ok=True)
            temp = admin / "workspace.tmp"
            temp.write_text(json.dumps(dict(epoch=manifest["epoch"])), encoding="utf-8")
            temp.replace(admin / "workspace.json")
            manifest["state"] = "complete"
            (archive / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            marker.unlink()
        except OSError:
            try:
                if store.index.exists() and not any(store.index.iterdir()):
                    store.index.rmdir()
                for src, dst in reversed(completed):
                    dst.replace(src)
                store.index.mkdir(exist_ok=True)
                admin = root / "admin"
                admin.mkdir(exist_ok=True)
                (admin / "workspace.json").write_text(
                    json.dumps(dict(epoch=manifest["previous_epoch"])), encoding="utf-8"
                )
                manifest["state"] = "rolled_back"
                (archive / "manifest.json").write_text(
                    json.dumps(manifest, indent=2), encoding="utf-8"
                )
                marker.unlink()
            except OSError:
                store.accepting_launches = False
                raise StoreError(
                    503,
                    "Archive reset requires recovery; history is retained and writes are blocked. Inspect .reset-recovery.json and the archive manifest.",
                ) from None
            raise StoreError(
                503, "Archive reset failed and was rolled back; retained history is unchanged"
            ) from None
        return dict(
            archive_id=archive_id,
            epoch=manifest["epoch"],
            status="archived",
            persona="maya",
            message="All three workspaces reset. History was archived; no AI request, financial change or credential change occurred.",
        )
