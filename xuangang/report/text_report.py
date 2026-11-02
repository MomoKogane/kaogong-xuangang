"""终端摘要文本。"""

from __future__ import annotations

from pathlib import Path

from .common import profile_text


def write_summary(result, path: Path, top: int = 15) -> Path:
    from ..pipeline import summarize_text

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if result.profile is not None:
        lines.append("个人条件：" + profile_text(result.profile))
        lines.append("")
    lines.append(summarize_text(result, top=top))
    lines.append("")
    lines.append("说明：本结果只做初筛，最终以招录机关解释和当年公告为准；分档与指数为启发式参考。")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
