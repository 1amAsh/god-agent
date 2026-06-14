"""
coding_agent/tools.py — File system + terminal primitives.

Improvements over the original:
  - Operates SYSTEM-WIDE: any absolute path is accepted without restriction.
  - LIST_DIR can traverse the full system (C:/, /, /home, etc.)
  - MOVE_FILE and COPY_FILE added for real file management workflows.
  - FIND_FILE does a true system-wide recursive search.
  - RUN_COMMAND timeout raised to 120s for long installs.
"""
from __future__ import annotations

import fnmatch
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional


class ToolKit:
    def __init__(self, workspace: str):
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.is_windows = platform.system() == "Windows"

    def _resolve(self, path: str) -> Path:
        """
        Resolve path.
        - Absolute paths are used as-is (full system access).
        - Relative paths are resolved relative to workspace.
        """
        p = Path(path)
        if p.is_absolute():
            return p.resolve()
        return (self.workspace / p).resolve()

    # ── Dispatch ─────────────────────────────────────────────────────

    def execute(self, action: dict) -> str:
        atype = action.get("type", "").upper()
        try:
            if atype == "READ_FILE":    return self.read_file(action["path"])
            if atype == "WRITE_FILE":   return self.write_file(action["path"], action["content"])
            if atype == "EDIT_FILE":    return self.edit_file(action["path"], action["find"], action["replace"])
            if atype == "APPEND_FILE":  return self.append_file(action["path"], action["content"])
            if atype == "DELETE_FILE":  return self.delete_file(action["path"])
            if atype == "MOVE_FILE":    return self.move_file(action["src"], action["dst"])
            if atype == "COPY_FILE":    return self.copy_file(action["src"], action["dst"])
            if atype == "RUN_COMMAND":  return self.run_command(action["command"], action.get("timeout", 120))
            if atype == "LIST_DIR":     return self.list_dir(action.get("path", "."))
            if atype == "SEARCH_FILES": return self.search_files(
                action.get("pattern", "*"),
                action.get("directory", "."),
                action.get("grep", ""),
            )
            if atype == "FIND_FILE":    return self.find_file(action["name"], action.get("root", "/"))
            if atype == "ASK_USER":     return self._ask_user(action["question"])
            if atype == "FINISH":       return f"[DONE] {action.get('summary', '')}"
            return f"[ERROR] Unknown action type: {atype}"
        except KeyError as e:
            return f"[ERROR] Action {atype} missing required field: {e}"
        except Exception as e:
            return f"[ERROR] {atype} failed: {e}"

    # ── File ops ──────────────────────────────────────────────────────

    def read_file(self, path: str) -> str:
        p = self._resolve(path)
        if not p.exists():
            return f"[ERROR] File not found: {p}"
        if not p.is_file():
            return f"[ERROR] Not a file: {p}"
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            numbered = "\n".join(f"{i+1:>4} | {l}" for i, l in enumerate(lines))
            return f"[FILE: {p}] ({len(lines)} lines)\n{numbered}"
        except Exception as e:
            return f"[ERROR] Cannot read {path}: {e}"

    def write_file(self, path: str, content: str) -> str:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"[OK] Written: {p} ({len(content.splitlines())} lines)"

    def edit_file(self, path: str, find: str, replace: str) -> str:
        p = self._resolve(path)
        if not p.exists():
            return f"[ERROR] File not found: {p}"
        content = p.read_text(encoding="utf-8", errors="replace")
        if find not in content:
            return (
                f"[ERROR] Pattern not found in {p}.\n"
                f"Pattern tried: {repr(str(find)[:120])}\n"
                f"Hint: Use READ_FILE first to see exact text."
            )
        p.write_text(content.replace(find, replace, 1), encoding="utf-8")
        return f"[OK] Edited {p}: replaced {len(find)} chars"

    def append_file(self, path: str, content: str) -> str:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)
        return f"[OK] Appended {len(content)} chars to {p}"

    def delete_file(self, path: str) -> str:
        p = self._resolve(path)
        if not p.exists():
            return f"[SKIP] Already gone: {p}"
        if p.is_dir():
            shutil.rmtree(p)
            return f"[OK] Deleted directory tree: {p}"
        p.unlink()
        return f"[OK] Deleted file: {p}"

    def move_file(self, src: str, dst: str) -> str:
        s = self._resolve(src)
        d = self._resolve(dst)
        if not s.exists():
            return f"[ERROR] Source not found: {s}"
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        return f"[OK] Moved: {s} → {d}"

    def copy_file(self, src: str, dst: str) -> str:
        s = self._resolve(src)
        d = self._resolve(dst)
        if not s.exists():
            return f"[ERROR] Source not found: {s}"
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_dir():
            shutil.copytree(str(s), str(d), dirs_exist_ok=True)
        else:
            shutil.copy2(str(s), str(d))
        return f"[OK] Copied: {s} → {d}"

    # ── Shell ─────────────────────────────────────────────────────────

    def run_command(self, command: str, timeout: int = 120) -> str:
        # Use workspace as cwd for relative commands; absolute paths work naturally
        cwd = str(self.workspace)
        shell_cmd = ["powershell", "-Command", command] if self.is_windows else ["bash", "-c", command]
        try:
            result = subprocess.run(
                shell_cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            parts = [f"[EXIT {result.returncode}]"]
            if result.stdout.strip():
                parts.append(f"STDOUT:\n{result.stdout.strip()[:3000]}")
            if result.stderr.strip():
                parts.append(f"STDERR:\n{result.stderr.strip()[:2000]}")
            if not result.stdout.strip() and not result.stderr.strip():
                parts.append("(no output)")
            return "\n".join(parts)
        except subprocess.TimeoutExpired:
            return f"[ERROR] Command timed out after {timeout}s"
        except FileNotFoundError as e:
            return f"[ERROR] Shell not found: {e}"
        except Exception as e:
            return f"[ERROR] Command failed: {e}"

    # ── Directory listing ─────────────────────────────────────────────

    def list_dir(self, path: str = ".") -> str:
        p = self._resolve(path)
        if not p.exists():
            return f"[ERROR] Not found: {p}"
        if not p.is_file() and not p.is_dir():
            return f"[ERROR] Not accessible: {p}"
        if p.is_file():
            return f"[FILE] {p} ({p.stat().st_size} bytes)"

        lines = [f"[DIR: {p}]"]
        try:
            entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
            for e in entries[:100]:
                if e.is_dir():
                    try:
                        n = sum(1 for _ in e.iterdir())
                        lines.append(f"  📁 {e.name}/  ({n} items)")
                    except PermissionError:
                        lines.append(f"  📁 {e.name}/  (permission denied)")
                else:
                    try:
                        sz = e.stat().st_size
                        sz_str = f"{sz/1024:.1f}KB" if sz > 1024 else f"{sz}B"
                    except Exception:
                        sz_str = "?"
                    lines.append(f"  📄 {e.name}  ({sz_str})")
            total = sum(1 for _ in p.iterdir())
            if total > 100:
                lines.append(f"  ... ({total - 100} more items)")
        except PermissionError:
            lines.append("  [Permission denied]")
        return "\n".join(lines)

    # ── Search ────────────────────────────────────────────────────────

    def search_files(self, pattern: str = "*", directory: str = ".", grep: str = "") -> str:
        base = self._resolve(directory)
        matches = []
        SKIP = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".env"}
        try:
            for root, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if d not in SKIP]
                for fname in files:
                    if fnmatch.fnmatch(fname.lower(), pattern.lower()):
                        full = Path(root) / fname
                        if grep:
                            try:
                                text = full.read_text(encoding="utf-8", errors="replace")
                                hits = [
                                    f"    L{i+1}: {l.strip()}"
                                    for i, l in enumerate(text.splitlines())
                                    if grep.lower() in l.lower()
                                ]
                                if hits:
                                    matches.append(f"  {full}\n" + "\n".join(hits[:5]))
                            except Exception:
                                pass
                        else:
                            matches.append(f"  {full}")
        except Exception as e:
            return f"[ERROR] Search failed: {e}"
        if not matches:
            return f"[SEARCH] No matches — pattern={pattern!r} grep={grep!r} in {base}"
        return f"[SEARCH] {len(matches)} result(s):\n" + "\n".join(matches[:50])

    def find_file(self, name: str, root: str = "/") -> str:
        """System-wide recursive file/directory search by name (supports wildcards)."""
        root_p = Path(root)
        SKIP = {".git", "__pycache__", "node_modules", "proc", "sys", "dev"}
        matches = []
        try:
            for dirpath, dirs, files in os.walk(root_p):
                dirs[:] = [d for d in dirs if d not in SKIP]
                all_names = dirs + files
                for n in all_names:
                    if fnmatch.fnmatch(n.lower(), name.lower()):
                        matches.append(str(Path(dirpath) / n))
                        if len(matches) >= 50:
                            break
                if len(matches) >= 50:
                    break
        except (PermissionError, OSError):
            pass
        if not matches:
            return f"[FIND] No files matching {name!r} under {root}"
        return f"[FIND] {len(matches)} match(es):\n" + "\n".join(f"  {m}" for m in matches)

    def _ask_user(self, question: str) -> str:
        print(f"\n[CODING AGENT] Clarification needed:\n  {question}\nYour answer: ", end="", flush=True)
        try:
            return input("").strip()
        except (EOFError, KeyboardInterrupt):
            return "[No answer provided]"
