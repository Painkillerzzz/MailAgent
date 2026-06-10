"""小工具：原子写文件，避免崩溃/磁盘满时损坏或清空数据。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str, *, mode: int | None = None) -> None:
    """把文本原子地写入 path（先写临时文件再 os.replace）。

    Args:
        path: 目标路径
        text: 内容
        mode: 可选权限位（如 0o600）
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        if mode is not None:
            try:
                os.chmod(tmp, mode)
            except OSError:
                pass
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
