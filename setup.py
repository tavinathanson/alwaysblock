#!/usr/bin/env python3
"""
alwaysblock setup script
"""
from setuptools import setup, find_packages
from pathlib import Path

# Read the README
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name="alwaysblock",
    version="1.0.0",
    description="Clean, modern DNS-based domain blocker for macOS",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Your Name",
    author_email="your.email@example.com",
    url="https://github.com/yourusername/alwaysblock",
    license="MIT",
    
    # Python version requirement
    python_requires=">=3.8",
    
    # Package discovery
    packages=find_packages(),
    py_modules=[
        "alwaysblockd",
        "dns_proxy",
        "config_manager",
        "db",
        "pf_manager",
        "cli_interface"
    ],
    
    # Dependencies
    install_requires=[
        "dnslib>=0.9.23",
        "pyyaml>=6.0",
    ],
    
    # Entry points
    entry_points={
        "console_scripts": [
            "alwaysblock=alwaysblock:main",
            "alwaysblockd=alwaysblockd:main",
        ],
    },
    
    # Include additional files
    include_package_data=True,
    package_data={
        "": ["*.yaml.example", "*.plist", "*.md"],
    },
    
    # Classifiers
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Environment :: MacOS X",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: MacOS :: MacOS X",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Internet :: Name Service (DNS)",
        "Topic :: System :: Networking :: Firewalls",
        "Topic :: Utilities",
    ],
    
    keywords="dns blocker domain productivity focus macos",
)