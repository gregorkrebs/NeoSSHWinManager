"""Undo / redo of file operations (history.py) on the real local disk."""

import os

from src.filebrowser.fs import LocalFS
from src.filebrowser.history import (
    MKDIR, MKFILE, MOVE, RENAME, Modified, NotEmpty, UndoHistory, UndoOp, apply_op,
)


def _op(kind, items, side="local"):
    return UndoOp(kind, side, items)


def test_move_undo_and_redo(tmp_path):
    fs = LocalFS()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.txt").write_text("a")
    (tmp_path / "dst").mkdir()
    old, new = str(tmp_path / "src" / "a.txt"), str(tmp_path / "dst" / "a.txt")
    fs.move(old, new)
    op = _op(MOVE, [(old, new)])

    result = apply_op(fs, op, undo=True)
    assert not result.errors and result.done.items == [(old, new)]
    assert os.path.exists(old) and not os.path.exists(new)

    result = apply_op(fs, op, undo=False)
    assert not result.errors
    assert os.path.exists(new) and not os.path.exists(old)


def test_partial_failure_keeps_the_part_that_worked(tmp_path):
    fs = LocalFS()
    (tmp_path / "dst").mkdir()
    for name in ("a", "b"):
        (tmp_path / "dst" / name).write_text(name)
    pairs = [(str(tmp_path / n), str(tmp_path / "dst" / n)) for n in ("a", "b")]
    (tmp_path / "b").write_text("new b")              # "b" was recreated meanwhile
    result = apply_op(fs, _op(MOVE, pairs), undo=True)
    assert result.done.items == [pairs[0]]
    assert [name for name, _e in result.errors] == ["b"]
    assert (tmp_path / "a").read_text() == "a"
    assert (tmp_path / "b").read_text() == "new b"     # nothing was overwritten


def test_rename_undo(tmp_path):
    fs = LocalFS()
    (tmp_path / "new.txt").write_text("x")
    op = _op(RENAME, [(str(tmp_path / "old.txt"), str(tmp_path / "new.txt"))])
    assert not apply_op(fs, op, undo=True).errors
    assert (tmp_path / "old.txt").exists() and not (tmp_path / "new.txt").exists()


def test_new_folder_undo_only_while_empty(tmp_path):
    fs = LocalFS()
    folder = tmp_path / "neu"
    folder.mkdir()
    op = _op(MKDIR, [str(folder)])
    (folder / "inside.txt").write_text("keep me")
    result = apply_op(fs, op, undo=True)
    assert result.done is None and isinstance(result.errors[0][1], NotEmpty)
    assert (folder / "inside.txt").exists()

    (folder / "inside.txt").unlink()
    assert not apply_op(fs, op, undo=True).errors
    assert not folder.exists()
    assert not apply_op(fs, op, undo=False).errors      # redo creates it again
    assert folder.is_dir()


def test_new_file_undo_only_while_empty(tmp_path):
    fs = LocalFS()
    path = tmp_path / "notes.txt"
    path.write_text("")
    op = _op(MKFILE, [str(path)])
    path.write_text("edited")
    result = apply_op(fs, op, undo=True)
    assert isinstance(result.errors[0][1], Modified) and path.exists()
    path.write_text("")
    assert not apply_op(fs, op, undo=True).errors and not path.exists()
    assert not apply_op(fs, op, undo=True).errors       # already gone: nothing to do


def test_history_stacks():
    h = UndoHistory(limit=2)
    a, b, c = (_op(MOVE, [(n, n + "2")]) for n in "abc")
    for op in (a, b, c):
        h.push(op)
    assert h.take_undo() is c and h.take_undo() is b and h.take_undo() is None   # limit
    h.undone(b)
    assert h.peek_redo() is b
    h.redone(h.take_redo())
    assert h.peek_undo() is b and h.peek_redo() is None
    h.undone(h.take_undo())
    h.push(a)                                           # a new action clears redo
    assert h.peek_redo() is None
    h.push(_op(MOVE, []))                               # empty operations are ignored
    assert h.peek_undo() is a
