"""End-of-job archive: one zip with scenes, sources, dailies and the project's paperwork, without heavy caches.

An ARCHIVE_INFO.md at the root of the zip records the time spent, shot statuses and what was left out (with sizes),
so the archive explains itself months later.
"""
import datetime
import os
import zipfile

import mke_project
import mke_tracking

CACHE_EXT = (".bgeo", ".bgeo.sc", ".bgeo.gz", ".vdb", ".sim", ".simdata", ".bphys", ".geo", ".geo.sc")
RENDER_EXT = (".exr",)
STORED_EXT = (".mp4", ".mov", ".jpg", ".jpeg", ".png", ".exr", ".zip", ".sc", ".gz", ".vdb", ".abc", ".usdc")  # already compressed
SKIP_DIRS = {"backup", mke_project.AUTOSAVE_DIR, "__pycache__"}


def plan(info, include_caches=False, include_renders=False):
    """Walk the project and decide file by file. Returns (kept [(path, arcname, size)], skipped {reason: size})."""
    root = info["root"]
    cache_root = os.path.normcase(os.path.normpath(mke_project.cache_dir(info)))
    kept, skipped = [], {}

    def skip(reason, size):
        skipped[reason] = skipped.get(reason, 0) + size

    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        norm = os.path.normcase(os.path.normpath(folder))
        in_cache_root = norm == cache_root or norm.startswith(cache_root + os.sep)
        in_sources = os.path.relpath(folder, root).replace("\\", "/").split("/")[0] == "IN"
        for name in files:
            path = os.path.join(folder, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            lower = name.lower()
            if not include_caches and (in_cache_root or lower.endswith(CACHE_EXT)):
                skip("Caches (bgeo, vdb, sim...)", size)
            elif not include_renders and lower.endswith(RENDER_EXT) and not in_sources:
                skip("EXR renders", size)
            else:
                kept.append((path, os.path.relpath(path, root), size))
    return kept, skipped


def info_markdown(info, kept, skipped, include_caches, include_renders):
    summary = mke_tracking.time_summary(info)
    statuses = mke_tracking.all_statuses(info)
    lines = [
        f"# Archive : {info['name']}", "",
        f"- Archived on {datetime.datetime.now():%d/%m/%Y %H:%M} by {mke_project.user_trigram()}",
        f"- Project created on {info.get('created', '?')}, type {info['type']}, {info['fps']:g} fps, "
        f"{info['resolution'][0]}x{info['resolution'][1]}",
        f"- Original folder: `{info['root']}`",
        f"- {len(kept)} files, {mke_tracking.human(sum(s for *_, s in kept))} before compression", "",
        "## Time spent", "",
        f"**Total: {mke_tracking.hours(summary['total'])}** over {len(summary['days'])} working day(s)", "",
    ]
    lines += [f"- {mke_tracking.key_label(key)} : {mke_tracking.hours(seconds)}"
              for key, seconds in sorted(summary["keys"].items(), key=lambda kv: -kv[1])]
    if statuses:
        lines += ["", "## Shot status", ""]
        lines += [f"- {mke_tracking.key_label(key)} : {mke_tracking.STATUS[status][0]}" for key, status in sorted(statuses.items())]
    lines += ["", "## Left out", ""]
    if skipped:
        lines += [f"- {reason} : {mke_tracking.human(size)} (still in the original folder)" for reason, size in skipped.items()]
    else:
        lines.append("- Nothing: the archive is complete.")
    lines += ["", f"Options: caches {'included' if include_caches else 'excluded'}, EXR renders {'included' if include_renders else 'excluded'}."]
    return "\n".join(lines) + "\n"


def default_destination(info):
    return os.path.join(os.path.dirname(info["root"]), f"{info['name']}_ARCHIVE_{datetime.date.today():%Y%m%d}.zip")


def archive(info, destination=None, include_caches=False, include_renders=False, progress=None):
    """Write the zip. progress(done_bytes, total_bytes, name) may return False to cancel. Returns (zip path, plan)."""
    destination = destination or default_destination(info)
    kept, skipped = plan(info, include_caches, include_renders)
    own = {os.path.normcase(os.path.abspath(p)) for p in (destination, destination + ".part")}
    kept = [k for k in kept if os.path.normcase(os.path.abspath(k[0])) not in own]  # zip saved inside the project
    total = sum(size for *_, size in kept) or 1
    done = 0
    tmp = destination + ".part"
    try:
        with zipfile.ZipFile(tmp, "w", allowZip64=True) as archive_file:
            archive_file.writestr("ARCHIVE_INFO.md", info_markdown(info, kept, skipped, include_caches, include_renders))
            for path, arcname, size in kept:
                compress = zipfile.ZIP_STORED if arcname.lower().endswith(STORED_EXT) else zipfile.ZIP_DEFLATED
                archive_file.write(path, arcname, compress_type=compress)
                done += size
                if progress and progress(done, total, arcname) is False:
                    raise InterruptedError("Archiving cancelled")
        os.replace(tmp, destination)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return destination, (kept, skipped)
