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
    url="https://github.com/QianQianLuLu1/FlashGaze",
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
    package_data={"flashgaze": ["models/brisque/*.yml", "models/brisque/*.md"]},
    include_package_data=True,
    install_requires=[
        # 必须用 headless 版：无头服务器与 CI 环境（如 GitHub ubuntu runner）不装 OpenGL
        # 图形栈，完整版 opencv-python 的 Linux wheel 链接了 libGL.so.1，import cv2 会直接崩。
        # 本项目从不调用任何 OpenCV GUI 函数（imshow/namedWindow/waitKey/destroyAllWindows），
        # headless 与完整版是同一套代码，非 GUI API 完全一致。
        "opencv-python-headless>=4.8.0,<6",
        "Pillow>=10.0.0,<14",
        "numpy>=1.24.0,<3",
        "requests>=2.31.0,<3",
        "pillow-heif>=0.15.0,<2",
    ],
    extras_require={
        "mcp": ["mcp>=1.2.0,<2.0.0"],
        # CV 增强维度（M2/M3/M4/M5）：默认不安装，按需 extras 启用
        "cv-enhanced": ["opencv-contrib-python-headless>=4.8.0,<6"],
        "portrait": ["face_recognition>=1.3.0,<2"],
        "dedup": ["imagededup>=0.2.0,<1"],
        # VLM 多提供商支持（VLM 扩展 M2/M10）：非 qwen 提供商需安装 litellm
        # provider=qwen 走原 requests.post 路径，零新依赖，100% 向后兼容
        "vlm-multi": ["litellm>=1.40,<2"],
        # Web GUI（基于 Gradio）：pip install -e ".[gui]" 后运行 flashgaze-webui
        # 默认不引入主 install_requires，避免拖慢基础安装；纯离线模式仍可用
        "gui": ["gradio>=6.0.0,<7"],
        # EXIF 元数据导出（M2）：仅 JPEG/TIFF，可选依赖
        "exif": ["piexif>=1.1.3,<2"],
        # Excel 清单导出（M3）：openpyxl 默认支持中文，无需额外编码处理
        "xlsx": ["openpyxl>=3.1.0,<4"],
        "all": [
            "opencv-contrib-python-headless>=4.8.0,<6",
            "face_recognition>=1.3.0,<2",
            "imagededup>=0.2.0,<1",
            "litellm>=1.40,<2",
            "gradio>=6.0.0,<7",
            "piexif>=1.1.3,<2",
            "openpyxl>=3.1.0,<4",
        ],
    },
    entry_points={
        "console_scripts": [
            "flashgaze=flashgaze.cli.entry:main",
            # Web GUI 入口：flashgaze-webui [--host 0.0.0.0] [--port 8080] [--dir ./photos]
            "flashgaze-webui=flashgaze.webui.app:main",
        ],
    },
    python_requires=">=3.10",
)
