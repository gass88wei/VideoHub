"""A directory with videos and their subtitles is a learning project.

One directory may hold many videos. Schema 2 records every video with its own
subtitle set; schema 1 (one video per directory) is still readable and is
rewritten as schema 2 on the next import.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .media import VIDEO_EXTENSIONS
from .store import new_id, now
from .subtitles import read_track

MANIFEST = "videohub_learning.json"
SCHEMA = 2
SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa"}


def inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("工程清单中的文件必须位于所选工程目录内")
    return path


def signature(path: Path) -> str:
    digest = hashlib.sha256(str(path.stat().st_size).encode())
    with path.open("rb") as stream:
        digest.update(stream.read(65536))
        stream.seek(max(0, path.stat().st_size - 65536))
        digest.update(stream.read(65536))
    return digest.hexdigest()


def normalize_stem(stem: str) -> str:
    """Compare a video name with a subtitle name without depending on layout.

    Videos and subtitles come from different tools: one uses " - YouTube" and
    spaces, the other full-width separators; both drop to the same key here.
    """
    try:
        from ..series_project import normalize_asset_stem
    except ImportError:
        from series_project import normalize_asset_stem
    return normalize_asset_stem(stem)


def classify(path: Path) -> tuple[str, str]:
    name = path.stem.lower()
    explicit = re.search(r"\.(source|target)\.([a-z]{2}(?:-[a-z]{2,4})?|auto)(?:\.|$)", name)
    if explicit:
        role, language = explicit.groups()
        return role, {"zh-cn": "zh-CN", "zh-tw": "zh-TW"}.get(language, language)
    # A language suffix is stronger evidence than words in the video title.
    suffix = re.search(r"(?:^|[_. -])(zh(?:[-_]?(?:cn|tw|hans|hant))?|en(?:-orig)?|ja|ko|fr|de|es)$", name)
    if suffix:
        language = suffix.group(1)
        if language.startswith("zh"):
            return "target", "zh-TW" if language.endswith(("tw", "hant")) else "zh-CN"
        return "source", language.replace("-orig", "")
    if re.search(
        r"(?:^|[_. -])(?:zh(?:[-_]?(?:cn|tw|hans|hant))?|cn|google|polished|translated)(?:$|[_. -])|中文|简体|繁体",
        name,
    ):
        return "target", "zh-CN"
    for code, words in [
        ("en", "english|英文|英语|原文"),
        ("ja", "japanese|日文|日语"),
        ("ko", "korean|韩文|韩语"),
        ("fr", "french|法语"),
        ("de", "german|德语"),
        ("es", "spanish|西班牙"),
    ]:
        if re.search(rf"(?:^|[_. -]){code}(?:$|[_. -])|{words}", name):
            return "source", code
    cues = read_track(path)["cues"][:12]
    text = "".join(c["text"] for c in cues)
    if re.search("[\u3040-\u30ff]", text):
        return "source", "ja"
    if re.search("[\uac00-\ud7af]", text):
        return "source", "ko"
    if len(re.findall("[\u4e00-\u9fff]", text)) > len(re.findall("[a-zA-Z]", text)):
        return "target", "zh-CN"
    return "source", "en"


def subtitle_files(root: Path) -> list[Path]:
    return [
        p
        for folder in (root, root / "subtitles", root / "subtitles" / "learning_tracks")
        if folder.is_dir()
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in SUBTITLE_EXTENSIONS
    ]


def tracks_for(root: Path, video: Path, candidates: list[Path], shared: bool) -> tuple[list[dict], list[str]]:
    """Read the subtitle files that belong to this video."""
    if shared:
        # Sibling videos in one directory: only files named after this video
        # belong to it, otherwise every video would load every subtitle.
        wanted = normalize_stem(video.stem)
        files = [p for p in candidates if normalize_stem(p.stem) == wanted]
    else:
        files = list(candidates)
    if len(files) > 80:
        raise ValueError("工程字幕超过80份，请按视频拆分目录")
    tracks, warnings = [], []
    for path in files:
        if not path.resolve().is_relative_to(root):
            continue
        try:
            role, language = classify(path)
            original = read_track(path, "source")["cues"]
            target = read_track(path, "target")["cues"]
            if original != target:
                tracks.extend(
                    [
                        {"path": str(path.resolve()), "role": "source", "language": "en"},
                        {"path": str(path.resolve()), "role": "target", "language": "zh-CN"},
                    ]
                )
                continue
            tracks.append({"path": str(path.resolve()), "role": role, "language": language})
        except (ValueError, UnicodeError, OSError):
            warnings.append(f"{path.name} 无法读取，已跳过")
    # Prefer a dedicated SRT original and Chinese track; preserve all alternatives.
    tracks.sort(
        key=lambda t: (
            t["role"],
            0 if re.search(r"\.(?:source|target)\.", Path(t["path"]).name) else 1,
            t["language"] != "en",
            "bilingual" in Path(t["path"]).stem.lower() or "双语" in Path(t["path"]).stem,
            (0 if "polished" in Path(t["path"]).stem.lower() else 2 if "google" in Path(t["path"]).stem.lower() else 1)
            if t["role"] == "target"
            else 0,
            {".srt": 0, ".vtt": 1, ".ass": 2, ".ssa": 3}[Path(t["path"]).suffix.lower()],
            -Path(t["path"]).stat().st_mtime_ns if re.search(r"\.(?:source|target)\.", Path(t["path"]).name) else 0,
            t["path"],
        )
    )
    if tracks and not any(t["role"] == "source" for t in tracks):
        tracks[0] = {**tracks[0], "role": "source"}
    return tracks, warnings


def read_manifest(root: Path) -> dict:
    """Load the manifest, translating a schema 1 file into schema 2 entries."""
    path = root / MANIFEST
    if not path.is_file():
        return {"schema_version": SCHEMA, "entries": [], "source_url": "", "title": "", "project_id": ""}
    if path.stat().st_size > 2_000_000:
        raise ValueError("工程清单过大")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        raise ValueError("工程清单损坏，请检查 videohub_learning.json") from None
    if not isinstance(data, dict):
        raise ValueError("工程清单格式不正确")
    version = data.get("schema_version")
    if version == 1:
        video = data.get("video")
        if not isinstance(video, str):
            raise ValueError("工程清单缺少视频路径")
        return {
            "schema_version": SCHEMA,
            # The schema 1 project id was also the video id; keep it so the
            # existing library record is reused instead of duplicated.
            "entries": [{"video": video, "id": data.get("id", ""), "subtitles": data.get("subtitles") or []}],
            "source_url": data.get("source_url", ""),
            "title": data.get("title", ""),
            "project_id": data.get("id", ""),
        }
    if version != SCHEMA:
        raise ValueError("不支持此学习工程清单版本")
    entries = data.get("videos")
    if not isinstance(entries, list):
        raise ValueError("工程清单缺少视频列表")
    return {
        "schema_version": SCHEMA,
        "entries": [e for e in entries if isinstance(e, dict) and isinstance(e.get("video"), str)],
        "source_url": data.get("source_url", ""),
        "title": data.get("title", ""),
        "project_id": data.get("id", ""),
    }


def scan(directory: str) -> dict:
    """List every video in a directory with the subtitles that match it.

    Read-only: importing is a separate step so the page can show a checklist
    first. Nothing is written beside the user's files here.
    """
    root = Path(directory.strip().strip('"')).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("请选择存在的视频工程目录")
    videos = sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS)
    if not videos:
        raise ValueError("目录中没有视频文件")
    if len(videos) > 500:
        raise ValueError("目录中视频超过500个，请按课程拆分目录")
    previous = read_manifest(root)
    remembered = {entry["video"] for entry in previous["entries"] if entry.get("video")}
    candidates = subtitle_files(root)
    shared = len(videos) > 1
    entries, warnings = [], []
    for video in videos:
        try:
            tracks, issues = tracks_for(root, video, candidates, shared)
        except ValueError as error:
            warnings.append(f"{video.stem}：{error}")
            continue
        warnings.extend(issues)
        previous_id = ""
        for entry in previous["entries"]:
            if entry["video"] == video.name or inside(root, entry["video"]) == video.resolve():
                previous_id = str(entry.get("id") or "")
                break
        entries.append(
            {
                "video": str(video.resolve()),
                "name": video.name,
                "title": video.stem,
                "relative": video.relative_to(root).as_posix(),
                "tracks": tracks,
                "track_count": len({(t["role"], t["language"]) for t in tracks}),
                "imported": video.name in remembered,
                "project_id": previous_id if re.fullmatch(r"[a-f0-9]{32}", previous_id or "") else "",
            }
        )
    return {
        "root": str(root),
        "videos": entries,
        "shared_subtitles": shared,
        "warnings": warnings,
        "schema_version": SCHEMA,
    }


def inspect_project(directory: str, video_path: str = "") -> dict:
    """Single-video view of a directory, kept for the download bundler.

    The learning importer works from scan()/import_project(); this simpler shape
    stays only because bundling a fresh download needs one manifest write.
    """
    root = Path(directory.strip().strip('"')).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("请选择存在的视频工程目录")
    if video_path:
        video = Path(video_path).resolve()
        if video.parent != root:
            raise ValueError("视频必须属于所选目录")
    else:
        videos = sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS)
        if not videos:
            raise ValueError("目录中没有视频文件")
        video = videos[0]
    previous = read_manifest(root)
    tracks, warnings = tracks_for(root, video, subtitle_files(root), False)
    project_id = previous["project_id"]
    return {
        "root": str(root),
        "path": str(video.resolve()),
        "title": previous["title"] or video.stem,
        "tracks": tracks,
        "id": project_id if re.fullmatch(r"[a-f0-9]{32}", project_id or "") else "",
        "media_signature": signature(video),
        "warnings": warnings,
    }


def import_project(service, directory: str, names: list[str] | None = None) -> dict:
    """Register the selected videos of a directory, then record the manifest."""
    scanned = scan(directory)
    root = Path(scanned["root"])
    selected = {name for name in (names or []) if isinstance(name, str)}
    entries = [e for e in scanned["videos"] if not selected or e["name"] in selected]
    if not entries:
        raise ValueError("请至少选择一个视频")
    previous = read_manifest(root)
    source_url = previous["source_url"] if isinstance(previous["source_url"], str) else ""
    imported, warnings = [], list(scanned["warnings"])
    for entry in entries:
        try:
            video = service.register(
                entry["video"],
                entry["title"],
                source_url=source_url,
                tracks=entry["tracks"],
                project={
                    "root": str(root),
                    "id": entry.get("project_id") or "",
                    "media_signature": signature(Path(entry["video"])),
                },
            )
        except (ValueError, OSError) as error:
            warnings.append(f"{entry['title']}：{error}")
            continue
        imported.append({"id": video["id"], "title": video["title"], "tracks": len(entry["tracks"])})
        entry["project_id"] = video["id"]
    if not imported:
        raise ValueError("没有视频导入成功" + ("：" + "；".join(warnings) if warnings else ""))
    # The manifest always describes the whole directory, so importing one more
    # video never forgets the ones imported earlier.
    merged = {e["name"]: e for e in scanned["videos"]}
    for entry in entries:
        merged[entry["name"]] = entry
    try:
        write_manifest(
            root,
            [{"video": merged[name]["name"], "title": merged[name]["title"],
              "project_id": merged[name].get("project_id", ""), "tracks": merged[name]["tracks"]}
             for name in sorted(merged)],
            source_url=source_url,
            project_id=previous.get("project_id", ""),
        )
    except OSError:
        warnings.append("目录不可写；资料已导入本机学习库，但工程清单未保存")
    return {"videos": imported, "warnings": warnings, "root": str(root)}


def relative_track(track: dict, root: Path) -> dict:
    """A subtitle path outside the project directory is not recorded."""
    try:
        return {**track, "path": Path(track["path"]).relative_to(root).as_posix()}
    except ValueError:
        return dict(track)


def write_manifest(root: Path, entries: list[dict], source_url: str = "", project_id: str = "", title: str = ""):
    """Write schema 2. `entries` is one dict per video, or a legacy project dict."""
    if isinstance(root, dict):
        # Legacy single-video call: write_manifest(project, source_url=...)
        legacy, root = root, Path(root["root"])
        entries = [{"video": Path(legacy["path"]).name, "title": legacy.get("title", ""),
                    "project_id": legacy.get("id", ""), "tracks": legacy.get("tracks", [])}]
        source_url = source_url or ""
        project_id = legacy.get("id", "") or project_id
        title = legacy.get("title", "") or title
    manifest = {
        "schema_version": SCHEMA,
        "project_type": "video_learning",
        "id": project_id if re.fullmatch(r"[a-f0-9]{32}", project_id or "") else new_id(),
        "title": title or root.name,
        "source_url": source_url,
        "videos": [
            {
                "id": entry.get("project_id", ""),
                "video": entry["video"],
                "title": entry["title"],
                "subtitles": [relative_track(t, root) for t in entry["tracks"]],
            }
            for entry in entries
        ],
        "updated": now(),
    }
    temporary = root / ("." + MANIFEST + "." + new_id() + ".tmp")
    try:
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(root / MANIFEST)
    finally:
        temporary.unlink(missing_ok=True)
