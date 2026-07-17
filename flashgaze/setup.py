from setuptools import setup, find_packages

setup(
    name="flashgaze",
    version="0.1.0",
    description="瞬选灵眸 - AI 辅助图片评分与筛选 CLI + MCP Server",
    long_description=(
        "FlashGaze 是面向摄影师与 AI Agent 的图片评分筛选工具。\n"
        "CV 客观评分（清晰度/曝光度/构图）+ VLM 场景补偿（艺术手法识别），\n"
        "支持 CLI 与 MCP Server 双入口，批量评分、导出精选、工作空间清理。"
    ),
    long_description_content_type="text/plain",
    url="https://github.com/flashgaze/flashgaze",
    license="MIT",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Multimedia :: Graphics",
        "Topic :: Scientific/Engineering :: Image Recognition",
    ],
    packages=find_packages(),
    install_requires=[
        "opencv-python>=4.8.0",
        "Pillow>=10.0.0",
        "numpy>=1.24.0",
        "requests>=2.31.0",
        "pillow-heif>=0.15.0",
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
