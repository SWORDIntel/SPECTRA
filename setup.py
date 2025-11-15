"""setup.py for SPECTRA - Telegram Network Discovery & Archiving System

Builds and distributes SPECTRA as a single installable Python package.

For the best experience, use the bootstrap script:
    ./bootstrap
Or use the Makefile:
    make bootstrap

For detailed setup instructions, see: docs/INSTALLATION_GUIDE.md
"""
from __future__ import annotations

from pathlib import Path
from setuptools import setup, find_packages

# ---------------------------------------------------------------------
# Version from package
# -----------------------------------------------------------------------
root = Path(__file__).parent
version = "1.0.0"  # Default version

# Try to get version from package __init__.py
init_file = root / "tgarchive" / "__init__.py"
if init_file.exists():
    for line in init_file.read_text().splitlines():
        if line.startswith("__version__"):
            try:
                # Extract version from __version__ = "x.x.x" (ignoring comments)
                version_part = line.split("=")[1].strip()
                # Remove comment if present
                version_part = version_part.split("#")[0].strip()
                # Remove quotes
                version = version_part.strip('"\'')
            except (IndexError, ValueError):
                pass
            break

# ---------------------------------------------------------------------
# Helper for requirements
# ---------------------------------------------------------------------

def list_requirements() -> list[str]:
    req_file = root / "requirements.txt"
    if req_file.exists():
        return [r.strip() for r in req_file.read_text().splitlines() if r.strip() and not r.startswith("#")]
    # inline fallback
    return [
        "telethon>=1.34",
        "rich>=13",
        "tqdm>=4",
        "pyyaml>=6",
        "Pillow>=10",
        "npyscreen>=4.10",
        "jinja2>=3",
        "networkx>=3.0",
        "matplotlib>=3.6",
        "pandas>=1.5",
        "python-magic>=0.4.27",
        "pyaes>=1.6.1",
        "pyasn1>=0.6.0",
        "rsa>=4.9",
        "feedgen>=0.9.0",
        "lxml>=4.9.2",
    ]

# ---------------------------------------------------------------------
# Long description from README
# ---------------------------------------------------------------------
long_description = (root / "README.md").read_text() if (root / "README.md").exists() else "SPECTRA archive toolkit."

# ---------------------------------------------------------------------
# Setup call
# ---------------------------------------------------------------------
setup(
    name="spectra-archive",
    version=version,
    description="Telegram archiving & discovery toolkit (SPECTRA)",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="John (SWORD-EPI)",
    author_email="n/a",
    url="https://github.com/SWORDIntel/SPECTRA002",
    packages=find_packages(include=["tgarchive*"]),
    install_requires=list_requirements(),
    include_package_data=True,
    license="MIT",
    python_requires=">=3.10",
    entry_points={
        "console_scripts": [
            "spectra = tgarchive.__main__:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Topic :: Communications :: Chat",
        "Topic :: Internet :: WWW/HTTP :: Site Management",
        "Environment :: Console",
        "Development Status :: 4 - Beta",
        "Intended Audience :: Information Technology",
        "Intended Audience :: Science/Research",
    ],
)
