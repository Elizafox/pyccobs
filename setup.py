"""Build the bundled ctypes library with its native CMake project."""

import os
import subprocess
from pathlib import Path

from setuptools import Extension, setup
from setuptools.command.bdist_wheel import bdist_wheel
from setuptools.command.build_ext import build_ext


class CMakeExtension(Extension):
    """A native library built by CMake rather than setuptools's compiler."""

    def __init__(self, name: str) -> None:
        super().__init__(name, sources=[])


class CMakeBuild(build_ext):
    """Configure, build, and install ccobs into the staged Python package."""

    def build_extension(self, ext: Extension) -> None:
        source_dir = Path(__file__).resolve().parent
        build_dir = Path(self.build_temp).resolve() / ext.name
        extension_path = Path(self.get_ext_fullpath(ext.name)).resolve()
        install_root = extension_path.parents[1]
        config = "Debug" if self.debug else "Release"

        # Don't let stale artifacts from previous builds leak into the wheel.
        extension_path.unlink(missing_ok=True)
        build_dir.mkdir(parents=True, exist_ok=True)
        configure_command = [
            "cmake",
            "-S",
            str(source_dir),
            "-B",
            str(build_dir),
            f"-DCMAKE_BUILD_TYPE={config}",
        ]
        generator = os.environ.get("CMAKE_GENERATOR")
        if generator:
            configure_command.extend(["-G", generator])
        if (
            os.name == "nt"
            and (not generator or generator.startswith("Visual Studio"))
            and "CMAKE_GENERATOR_PLATFORM" not in os.environ
        ):
            architecture = {
                "win32": "Win32",
                "win-amd64": "x64",
                "win-arm64": "ARM64",
            }.get(self.plat_name)
            if architecture:
                configure_command.extend(["-A", architecture])

        subprocess.run(configure_command, check=True)
        subprocess.run(
            ["cmake", "--build", str(build_dir), "--config", config], check=True
        )
        subprocess.run(
            [
                "cmake",
                "--install",
                str(build_dir),
                "--config",
                config,
                "--prefix",
                str(install_root),
            ],
            check=True,
        )


class PlatformWheel(bdist_wheel):
    """Tag the ctypes wheel as Python-independent but platform-specific."""

    def get_tag(self) -> tuple[str, str, str]:
        _, _, platform = super().get_tag()
        return "py3", "none", platform


setup(
    ext_modules=[CMakeExtension("ccobs._ccobs")],
    cmdclass={"build_ext": CMakeBuild, "bdist_wheel": PlatformWheel},
)
