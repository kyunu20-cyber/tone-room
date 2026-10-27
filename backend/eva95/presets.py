"""내장 프리셋(읽기 전용) + 사용자 프리셋(data/presets/user) 관리."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .params import normalize

BUILTIN_DIR = Path(__file__).parent / "presets"
DATA_DIR = Path(os.environ.get("EVA95_DATA", Path(__file__).resolve().parents[2] / "data"))
DEFAULT_PRESET = "iphone17_natural"
BUILTIN_ORDER = ["iphone17_natural", "iphone17_vivid", "iphone17_soft",
                 "eva95_original_tv", "eva95_cel_color", "eva95_cinematic", "eva95_archival"]


def user_dir() -> Path:
    d = DATA_DIR / "presets" / "user"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load(path: Path) -> dict:
    p = json.loads(path.read_text(encoding="utf-8"))
    p["params"] = normalize(p.get("params"))
    return p


def list_presets() -> list[dict]:
    builtin = {p.stem: _load(p) for p in BUILTIN_DIR.glob("*.json")}
    out = [builtin[k] for k in BUILTIN_ORDER if k in builtin]
    for p in sorted(user_dir().glob("*.json")):
        try:
            item = _load(p)
            item["builtin"] = False
            out.append(item)
        except (ValueError, OSError):
            continue  # 깨진 사용자 프리셋은 목록에서만 제외
    return out


def get_preset(preset_id: str) -> dict:
    for p in list_presets():
        if p["id"] == preset_id:
            return p
    raise KeyError(f"프리셋을 찾을 수 없습니다: {preset_id}")


def _slug(name: str) -> str:
    s = re.sub(r"[^\w-]+", "_", name.strip().lower(), flags=re.UNICODE).strip("_")
    return "user_" + (s or "preset")


def save_preset(name: str, params: dict, description: str = "") -> dict:
    if not name.strip():
        raise ValueError("프리셋 이름이 비어 있습니다")
    pid = _slug(name)
    if pid.removeprefix("user_") in BUILTIN_ORDER:
        raise ValueError("내장 프리셋 이름은 쓸 수 없습니다")
    item = {"id": pid, "name": name.strip(), "description": description, "builtin": False,
            "params": normalize(params)}
    (user_dir() / f"{pid}.json").write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    return item


def delete_preset(preset_id: str) -> None:
    if not preset_id.startswith("user_"):
        raise ValueError("내장 프리셋은 삭제할 수 없습니다")
    path = user_dir() / f"{preset_id}.json"
    if not path.exists():
        raise KeyError(f"프리셋을 찾을 수 없습니다: {preset_id}")
    path.unlink()
