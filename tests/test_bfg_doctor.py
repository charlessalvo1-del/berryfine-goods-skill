import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "berryfine-goods-skill" / "scripts" / "bfg.py"
SCRIPTS = SCRIPT.parent
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("bfg_doctor_module", SCRIPT)
assert SPEC and SPEC.loader
BFG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BFG)


class _RegistryKey:
    def __init__(self, value: str):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class BfgDoctorTests(unittest.TestCase):
    def run_doctor(
        self,
        *,
        version=(3, 11, 0),
        system="Windows",
        powershell=True,
        excel=True,
        sqlite=True,
    ):
        with (
            patch.object(BFG.sys, "version_info", version),
            patch.object(BFG.platform, "python_version", return_value=".".join(map(str, version[:3]))),
            patch.object(BFG.platform, "system", return_value=system),
            patch.object(BFG.shutil, "which", side_effect=lambda _name: "powershell.exe" if powershell else None),
            patch.object(BFG, "detect_desktop_excel", return_value=(excel, "mock detection")),
            patch.object(BFG, "stdlib_sqlite_available", return_value=sqlite),
        ):
            return BFG.doctor()

    def test_python_below_311_fails_core_readiness(self):
        result = self.run_doctor(version=(3, 10, 14))
        self.assertFalse(result["python_supported"])
        self.assertFalse(result["core_workflow_ready"])
        self.assertEqual(result["status"], "FAIL")

    def test_python_311_or_newer_passes_core_readiness(self):
        result = self.run_doctor(version=(3, 11, 0), system="Linux", powershell=False, excel=False)
        self.assertTrue(result["python_supported"])
        self.assertTrue(result["core_workflow_ready"])
        self.assertFalse(result["exact_excel_builder_ready"])
        self.assertEqual(result["status"], "PASS")

    def test_windows_without_powershell_is_not_excel_builder_ready(self):
        result = self.run_doctor(powershell=False)
        self.assertTrue(result["core_workflow_ready"])
        self.assertFalse(result["exact_excel_builder_ready"])

    def test_windows_without_detectable_excel_is_not_builder_ready(self):
        result = self.run_doctor(excel=False)
        self.assertFalse(result["desktop_excel_available"])
        self.assertFalse(result["exact_excel_builder_ready"])

    def test_windows_with_detectable_excel_is_builder_ready(self):
        result = self.run_doctor(excel=True)
        self.assertTrue(result["desktop_excel_available"])
        self.assertTrue(result["exact_excel_builder_ready"])

    def test_indeterminate_excel_detection_is_preserved(self):
        result = self.run_doctor(excel=None)
        self.assertIsNone(result["desktop_excel_available"])
        self.assertFalse(result["exact_excel_builder_ready"])

    def test_non_windows_detection_does_not_claim_excel(self):
        with patch.object(BFG.platform, "system", return_value="Linux"):
            available, detail = BFG.detect_desktop_excel()
        self.assertFalse(available)
        self.assertIn("only on Windows", detail)

    def test_registry_detection_does_not_launch_excel(self):
        values = {
            r"Excel.Application\CLSID": "{EXCEL-CLSID}",
            r"CLSID\{EXCEL-CLSID}\LocalServer32": r'"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE" /automation',
        }
        fake_winreg = SimpleNamespace(
            HKEY_CLASSES_ROOT=object(),
            OpenKey=lambda _root, name: _RegistryKey(values[name]),
            QueryValueEx=lambda key, _name: (key.value, 1),
        )
        with (
            patch.object(BFG.platform, "system", return_value="Windows"),
            patch.dict(sys.modules, {"winreg": fake_winreg}),
            patch.object(BFG.Path, "is_file", return_value=True),
        ):
            available, detail = BFG.detect_desktop_excel()
        self.assertTrue(available)
        self.assertIn("EXCEL.EXE", detail)

    def test_missing_and_indeterminate_registry_results_are_distinct(self):
        missing = SimpleNamespace(
            HKEY_CLASSES_ROOT=object(),
            OpenKey=lambda *_args: (_ for _ in ()).throw(FileNotFoundError()),
        )
        denied = SimpleNamespace(
            HKEY_CLASSES_ROOT=object(),
            OpenKey=lambda *_args: (_ for _ in ()).throw(PermissionError("denied")),
        )
        with patch.object(BFG.platform, "system", return_value="Windows"), patch.dict(sys.modules, {"winreg": missing}):
            self.assertEqual(BFG.detect_desktop_excel()[0], False)
        with patch.object(BFG.platform, "system", return_value="Windows"), patch.dict(sys.modules, {"winreg": denied}):
            self.assertIsNone(BFG.detect_desktop_excel()[0])


if __name__ == "__main__":
    unittest.main()
