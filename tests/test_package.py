"""Tests for scripts/package.py packaging script."""
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent
PACKAGE_SCRIPT = PROJECT_ROOT / "scripts" / "package.py"
LIB_COMMON = PROJECT_ROOT / "lib" / "ideogis_common"
PLUGINS_DIR = PROJECT_ROOT / "plugins"


def test_package_script_is_executable():
    """Verify package.py exists and is syntactically valid."""
    assert PACKAGE_SCRIPT.exists(), "scripts/package.py does not exist"

    # Check Python syntax
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(PACKAGE_SCRIPT)],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"Syntax error in package.py: {result.stderr}"


def test_vendor_copies_shared_files():
    """Verify vendoring function copies all 4 shared library files."""
    # Import the package module to test vendor function
    import importlib.util
    spec = importlib.util.spec_from_file_location("package", PACKAGE_SCRIPT)
    package_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package_mod)

    with tempfile.TemporaryDirectory() as tmpdir:
        target_dir = Path(tmpdir) / "infrastructure"
        target_dir.mkdir()

        # Call vendor function
        package_mod.vendor_shared_lib(LIB_COMMON, target_dir)

        # Verify all 4 files copied
        expected_files = ["__init__.py", "crs_manager.py", "feature_builder.py", "geometry_helpers.py"]
        for filename in expected_files:
            target_file = target_dir / filename
            assert target_file.exists(), f"{filename} was not vendored"
            assert target_file.is_file(), f"{filename} is not a regular file"

            # Verify it's a copy, not a symlink
            assert not target_file.is_symlink(), f"{filename} is still a symlink"

            # Verify content matches source
            source_file = LIB_COMMON / filename
            assert target_file.read_text() == source_file.read_text(), \
                f"{filename} content doesn't match source"


def test_zip_excludes_pycache():
    """Verify __pycache__ directories are not included in ZIP."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("package", PACKAGE_SCRIPT)
    package_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package_mod)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)

        # Create a test plugin directory with __pycache__
        test_plugin = output_dir / "test_plugin"
        test_plugin.mkdir()
        (test_plugin / "metadata.txt").write_text("[general]\nname=Test\n")
        (test_plugin / "__init__.py").write_text("")

        pycache_dir = test_plugin / "__pycache__"
        pycache_dir.mkdir()
        (pycache_dir / "test.pyc").write_text("compiled")

        # Create ZIP
        zip_path = output_dir / "test_plugin.zip"
        package_mod.create_plugin_zip(test_plugin, zip_path)

        # Verify __pycache__ not in ZIP
        with zipfile.ZipFile(zip_path, 'r') as zf:
            namelist = zf.namelist()
            pycache_files = [n for n in namelist if '__pycache__' in n or n.endswith('.pyc')]
            assert len(pycache_files) == 0, f"ZIP contains __pycache__: {pycache_files}"


def test_zip_contains_expected_files():
    """Verify ZIP contains required plugin files."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("package", PACKAGE_SCRIPT)
    package_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package_mod)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)

        # Create a minimal plugin directory
        test_plugin = output_dir / "test_plugin"
        test_plugin.mkdir()
        (test_plugin / "metadata.txt").write_text("[general]\nname=Test Plugin\n")
        (test_plugin / "__init__.py").write_text("# Test plugin init")
        (test_plugin / "main.py").write_text("# Main module")

        subdir = test_plugin / "algorithms"
        subdir.mkdir()
        (subdir / "processor.py").write_text("# Processor")

        # Create ZIP
        zip_path = output_dir / "test_plugin.zip"
        package_mod.create_plugin_zip(test_plugin, zip_path)

        # Verify expected files in ZIP
        with zipfile.ZipFile(zip_path, 'r') as zf:
            namelist = zf.namelist()

            # All files should be under test_plugin/ directory
            expected_files = [
                "test_plugin/metadata.txt",
                "test_plugin/__init__.py",
                "test_plugin/main.py",
                "test_plugin/algorithms/processor.py"
            ]

            for expected in expected_files:
                assert expected in namelist, f"Missing {expected} in ZIP"

            # Verify metadata.txt has correct content
            with zf.open("test_plugin/metadata.txt") as f:
                content = f.read().decode('utf-8')
                assert "name=Test Plugin" in content


def test_package_main_creates_all_zips(tmp_path):
    """Integration test: verify main() creates all three plugin ZIPs."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("package", PACKAGE_SCRIPT)
    package_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package_mod)

    output_dir = tmp_path / "dist"

    # Run packaging
    package_mod.main(["--output-dir", str(output_dir)])

    # Verify all ZIPs created
    expected_zips = ["tessera.zip", "percentage_split.zip", "stripe_hatching.zip"]
    for zip_name in expected_zips:
        zip_path = output_dir / zip_name
        assert zip_path.exists(), f"{zip_name} was not created"
        assert zip_path.stat().st_size > 0, f"{zip_name} is empty"

        # Verify ZIP is valid
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Should have metadata.txt and __init__.py at minimum
            namelist = zf.namelist()
            plugin_name = zip_name.replace('.zip', '')
            assert f"{plugin_name}/metadata.txt" in namelist
            assert f"{plugin_name}/__init__.py" in namelist
