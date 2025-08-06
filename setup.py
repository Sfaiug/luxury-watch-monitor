"""Setup script for Watch Monitor package."""

from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
readme_path = Path(__file__).parent / "README.md"
long_description = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

# Read requirements
requirements_path = Path(__file__).parent / "requirements.txt"
requirements = []
if requirements_path.exists():
    requirements = [
        line.strip() 
        for line in requirements_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

setup(
    name="watch-monitor",
    version="2.0.0",
    author="Watch Monitor Team", 
    author_email="team@watchmonitor.dev",
    description="Production-ready luxury watch monitoring system",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourorg/watch-monitor",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Internet :: WWW/HTTP :: Indexing/Search",
        "Topic :: Office/Business :: Financial :: Investment",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
        "Framework :: AsyncIO",
        "Typing :: Typed",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0", 
            "pytest-mock>=3.10.0",
            "pytest-cov>=4.0.0",
            "mypy>=1.0.0",
            "ruff>=0.1.0",
            "black>=23.0.0",
        ],
        "test": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "pytest-mock>=3.10.0",
            "pytest-cov>=4.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "watch-monitor=watch_monitor_refactored.main:main",
        ],
    },
    include_package_data=True,
    package_data={
        "watch_monitor_refactored": [
            "*.md",
            "*.txt",
            "*.example",
        ],
    },
    keywords=[
        "watches", "luxury", "monitoring", "scraping", "notifications",
        "discord", "rolex", "omega", "patek-philippe", "retail"
    ],
    project_urls={
        "Bug Reports": "https://github.com/yourorg/watch-monitor/issues",
        "Source": "https://github.com/yourorg/watch-monitor",
        "Documentation": "https://github.com/yourorg/watch-monitor/blob/main/README.md",
    },
)