#!/usr/bin/env python3
"""Package Tessera plugins for distribution.

1. Copy lib/tessera_common/*.py into each standalone plugin's infrastructure/ folder
2. For the main plugin, resolve symlinks to actual file copies
3. ZIP each plugin directory for QGIS plugin manager upload

Usage:
    python scripts/package.py [--output-dir dist/]
"""
import argparse
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


def vendor_shared_lib(lib_dir: Path, target_dir: Path) -> None:
    """Copy shared library files into target infrastructure directory.

    Args:
        lib_dir: Path to lib/tessera_common/
        target_dir: Path to plugin's infrastructure/ directory
    """
    if not lib_dir.exists():
        raise FileNotFoundError(f"Shared library not found: {lib_dir}")

    if not target_dir.exists():
        raise FileNotFoundError(f"Target directory not found: {target_dir}")

    # Copy all Python files from shared lib
    shared_files = ["__init__.py", "crs_manager.py", "feature_builder.py", "geometry_helpers.py"]

    for filename in shared_files:
        source_file = lib_dir / filename
        target_file = target_dir / filename

        if not source_file.exists():
            raise FileNotFoundError(f"Shared library file not found: {source_file}")

        # Copy file (overwrite if exists)
        shutil.copy2(source_file, target_file)
        print(f"  Vendored: {filename} -> {target_dir.name}/")


def resolve_symlinks_in_directory(source_dir: Path, target_dir: Path) -> None:
    """Recursively copy directory, resolving symlinks to actual files.

    Args:
        source_dir: Source plugin directory (may contain symlinks)
        target_dir: Target directory (will contain resolved files)
    """
    for item in source_dir.iterdir():
        target_item = target_dir / item.name

        # Skip __pycache__ directories
        if item.name == "__pycache__":
            continue

        if item.is_dir():
            target_item.mkdir(exist_ok=True)
            resolve_symlinks_in_directory(item, target_item)
        elif item.is_symlink():
            # Resolve symlink and copy actual file
            real_file = item.resolve()
            shutil.copy2(real_file, target_item)
        else:
            # Regular file
            shutil.copy2(item, target_item)


def create_plugin_zip(plugin_dir: Path, output_path: Path) -> None:
    """Create a ZIP file of the plugin directory.

    Args:
        plugin_dir: Path to plugin directory
        output_path: Path where ZIP file should be created
    """
    plugin_name = plugin_dir.name

    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file_path in plugin_dir.rglob('*'):
            # Skip __pycache__ and .pyc files
            if '__pycache__' in file_path.parts or file_path.suffix == '.pyc':
                continue

            if file_path.is_file():
                # Archive path should be relative to plugin parent, including plugin name
                arcname = plugin_name / file_path.relative_to(plugin_dir)
                zf.write(file_path, arcname=str(arcname))

    print(f"Created: {output_path}")


def package_standalone_plugin(plugin_dir: Path, lib_dir: Path, output_dir: Path, license_file: Path) -> None:
    """Package a standalone plugin by vendoring shared lib and creating ZIP.

    Args:
        plugin_dir: Path to plugin directory
        lib_dir: Path to lib/tessera_common/
        output_dir: Output directory for ZIP files
        license_file: Path to LICENSE file to include
    """
    plugin_name = plugin_dir.name
    print(f"\nPackaging standalone plugin: {plugin_name}")

    # Vendor shared library into infrastructure/
    infra_dir = plugin_dir / "infrastructure"
    if not infra_dir.exists():
        raise FileNotFoundError(f"Infrastructure directory not found: {infra_dir}")

    vendor_shared_lib(lib_dir, infra_dir)

    # Copy LICENSE file
    if license_file.exists():
        shutil.copy2(license_file, plugin_dir / "LICENSE")
        print(f"  Copied LICENSE")

    # Create ZIP
    zip_path = output_dir / f"{plugin_name}.zip"
    create_plugin_zip(plugin_dir, zip_path)


def package_main_plugin(plugin_dir: Path, output_dir: Path, license_file: Path) -> None:
    """Package main plugin by resolving symlinks and creating ZIP.

    Args:
        plugin_dir: Path to main plugin directory
        output_dir: Output directory for ZIP files
        license_file: Path to LICENSE file to include
    """
    plugin_name = plugin_dir.name
    print(f"\nPackaging main plugin: {plugin_name}")

    # Create temporary directory with resolved symlinks
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_plugin = Path(tmpdir) / plugin_name
        tmp_plugin.mkdir()

        print(f"  Resolving symlinks...")
        resolve_symlinks_in_directory(plugin_dir, tmp_plugin)

        # Copy LICENSE file
        if license_file.exists():
            shutil.copy2(license_file, tmp_plugin / "LICENSE")
            print(f"  Copied LICENSE")

        # Create ZIP from temp directory
        zip_path = output_dir / f"{plugin_name}.zip"
        create_plugin_zip(tmp_plugin, zip_path)


def main(argv=None):
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Package Tessera plugins for distribution")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dist"),
        help="Output directory for ZIP files (default: dist/)"
    )

    args = parser.parse_args(argv)

    # Determine project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    lib_dir = project_root / "lib" / "ideogis_common"
    plugins_dir = project_root / "plugins"
    license_file = project_root / "LICENSE"
    output_dir = args.output_dir

    # Validate paths
    if not lib_dir.exists():
        print(f"ERROR: Shared library not found: {lib_dir}", file=sys.stderr)
        return 1

    if not plugins_dir.exists():
        print(f"ERROR: Plugins directory not found: {plugins_dir}", file=sys.stderr)
        return 1

    if not license_file.exists():
        print(f"WARNING: LICENSE file not found: {license_file}", file=sys.stderr)

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {output_dir.absolute()}")

    # Package standalone plugins
    standalone_plugins = ["percentage_split", "stripe_hatching"]
    for plugin_name in standalone_plugins:
        plugin_dir = plugins_dir / plugin_name
        if plugin_dir.exists():
            package_standalone_plugin(plugin_dir, lib_dir, output_dir, license_file)
        else:
            print(f"WARNING: Plugin directory not found: {plugin_dir}", file=sys.stderr)

    # Package main plugin
    main_plugin_dir = plugins_dir / "tessera"
    if main_plugin_dir.exists():
        package_main_plugin(main_plugin_dir, output_dir, license_file)
    else:
        print(f"WARNING: Main plugin directory not found: {main_plugin_dir}", file=sys.stderr)

    print(f"\n✓ Packaging complete. ZIPs in: {output_dir.absolute()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
