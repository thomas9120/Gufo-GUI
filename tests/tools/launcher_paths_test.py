"""A separate upstream checkout supplies defaults without rewriting presets."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/gui"))
from presets import load_document, new_document, resolved_settings
from settings import default_executable


class LauncherPathsTest(unittest.TestCase):
    def test_default_custom_and_incomplete_setup(self):
        with tempfile.TemporaryDirectory() as directory, patch("settings.ROOT", Path(directory)):
            root = Path(directory)
            name, preset = ("gufo.exe", "windows-release") if os.name == "nt" else ("gufo", "release")
            self.assertEqual(default_executable(), str(root / "gufo/build" / preset / name))
            custom = root / "official & spaces"
            state = root / "build/windows-setup.json"
            state.parent.mkdir()
            state.write_text(json.dumps({"GufoPath": str(custom)}), encoding="utf-8-sig")
            self.assertEqual(default_executable(), str(custom / "build" / preset / name))
            engine = custom / "build/release" / name
            engine.parent.mkdir(parents=True)
            engine.touch()
            self.assertEqual(default_executable(), str(engine))
            for invalid in ('{bad json', '[]', '{"GufoPath": "relative"}', '{"GufoPath": null}'):
                state.write_text(invalid, encoding="utf-8")
                self.assertEqual(default_executable(), str(root / "gufo/build" / preset / name))

    @unittest.skipIf(os.name == "nt", "Linux setup state is ignored on Windows")
    def test_linux_setup_state_takes_precedence_on_posix(self):
        with tempfile.TemporaryDirectory() as directory, patch("settings.ROOT", Path(directory)):
            root = Path(directory)
            (root / "build").mkdir()
            (root / "build/windows-setup.json").write_text(json.dumps({"GufoPath": str(root / "windows")}))
            self.assertEqual(default_executable(), str(root / "windows/build/release/gufo"))
            (root / "build/linux-setup.json").write_text(json.dumps({"GufoPath": str(root / "linux")}))
            self.assertEqual(default_executable(), str(root / "linux/build/release/gufo"))

    def test_old_executable_selection_and_file_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "presets.json"
            selected = str(Path(directory) / "old port/gufo.exe")
            path.write_text(json.dumps(new_document({"executable": selected})), encoding="utf-8")
            before = path.read_bytes()
            self.assertEqual(resolved_settings(load_document(path))["executable"], selected)
            self.assertEqual(path.read_bytes(), before)
