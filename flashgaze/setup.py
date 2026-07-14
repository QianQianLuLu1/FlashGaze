from setuptools import setup, find_packages

setup(
    name="flashgaze",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "opencv-python>=4.8.0",
        "Pillow>=10.0.0",
        "numpy>=1.24.0",
        "requests>=2.31.0",
    ],
    extras_require={
        "mcp": ["mcp>=1.0.0"],
    },
    entry_points={
        "console_scripts": [
            "flashgaze=flashgaze.cli.entry:main",
        ],
    },
    python_requires=">=3.10",
)
