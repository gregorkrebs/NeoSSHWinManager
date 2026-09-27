"""
history.py – Undo / redo of file operations in the browser.

Only operations that can be reversed without losing data are recorded:
moving (drag & drop), renaming, and creating a folder or an empty file.
Deleting on the server is final and transfers are copies, so neither ends up
here.

Undoing or redoing applies an operation item by item. Items that fail (the
file was changed or removed meanwhile, a name is taken …) are reported and
dropped from the history; the items that worked move to the other stack.

Pure Python without Qt: the window runs apply_op() in a worker thread.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.filebrowser.fs import FsError

MOVE = "move"          # items: [(old path, new path)]
RENAME = "rename"      # items: [(old path, new path)]
MKDIR = "mkdir"        # items: [path]
MKFILE = "mkfile"      # items: [path] (an empty file)


class NotEmpty(FsError):
    """Undo of "new folder": the folder has content by now."""


class Modified(FsError):
    """Undo of "new file": the file has content by now."""


@dataclass
class UndoOp:
    kind: str
    side: str                                   # "remote" | "local"
    items: list = field(default_factory=list)


@dataclass
class ApplyResult:
    done: Optional[UndoOp]                      # the part that was applied
    errors: list = field(default_factory=list)  # [(name, FsError)]


def _apply_item(fs, kind: str, item, undo: bool) -> None:
    if kind in (MOVE, RENAME):
        old, new = item
        src, dst = (new, old) if undo else (old, new)
        (fs.rename if kind == RENAME else fs.move)(src, dst)
    elif kind == MKDIR:
        if not undo:
            fs.mkdir(item)
        elif fs.stat(item) is not None:          # already gone: nothing left to undo
            if fs.listdir(item):
                raise NotEmpty(fs.basename(item))
            fs.rmdir(item)
    elif kind == MKFILE:
        if not undo:
            fs.create_empty(item)
            return
        entry = fs.stat(item)
        if entry is None:
            return
        if entry.is_dir or entry.size:
            raise Modified(fs.basename(item))
        fs.remove(item)
    else:
        raise FsError(f"unknown operation {kind}")


def _item_name(fs, kind: str, item) -> str:
    return fs.basename(item[0] if kind in (MOVE, RENAME) else item)


def apply_op(fs, op: UndoOp, undo: bool) -> ApplyResult:
    """Undo (or redo) op on fs, item by item."""
    done, errors = [], []
    items = list(reversed(op.items)) if undo else list(op.items)
    for item in items:
        try:
            _apply_item(fs, op.kind, item, undo)
            done.append(item)
        except FsError as e:
            errors.append((_item_name(fs, op.kind, item), e))
    if undo:
        done.reverse()
    return ApplyResult(UndoOp(op.kind, op.side, done) if done else None, errors)


class UndoHistory:
    """Two stacks; a new operation clears the redo stack."""

    def __init__(self, limit: int = 100) -> None:
        self.limit = limit
        self._undo: list[UndoOp] = []
        self._redo: list[UndoOp] = []

    def push(self, op: UndoOp) -> None:
        if not op.items:
            return
        self._undo.append(op)
        del self._undo[:-self.limit]
        self._redo.clear()

    def peek_undo(self) -> Optional[UndoOp]:
        return self._undo[-1] if self._undo else None

    def peek_redo(self) -> Optional[UndoOp]:
        return self._redo[-1] if self._redo else None

    def take_undo(self) -> Optional[UndoOp]:
        return self._undo.pop() if self._undo else None

    def take_redo(self) -> Optional[UndoOp]:
        return self._redo.pop() if self._redo else None

    def undone(self, op: UndoOp) -> None:
        """op was undone: it can be redone now."""
        self._redo.append(op)

    def redone(self, op: UndoOp) -> None:
        """op was redone: it can be undone again (redo stack stays)."""
        self._undo.append(op)
        del self._undo[:-self.limit]

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
