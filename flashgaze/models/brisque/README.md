# BRISQUE 模型文件

本目录存放 BRISQUE 无参考 IQA 评分所需的模型文件。**模型文件现已随包分发**——仓库与 wheel 中都带上了这两个 `.yml`，正常安装后开箱即用，无需手动下载、无需联网。

若文件因故缺失（例如安装环境被裁剪），程序会在首次启用噪点评分时尝试自动下载作为兜底；下载失败则降级为 `noise: null` 并打印 WARNING。

## 必需文件

| 文件 | 用途 | 大小 |
|---|---|---|
| `brisque_model_live.yml` | BRISQUE SVR 模型 | ~570 KB |
| `brisque_range_live.yml` | BRISQUE 特征归一化范围（2×36 矩阵） | ~1.4 KB |

## 获取顺序（程序内部逻辑）

1. **包内目录**（即本目录）——随包分发的主路径，命中即用，不联网。
2. **用户缓存目录** `~/.cache/flashgaze/brisque/`——此前自动下载落盘的位置。
3. **联网自动下载**——仅当上述两处都缺文件时触发，优先写回包目录；包目录只读（如系统级 site-packages）时改写用户缓存目录。

已存在的文件永远不会被覆盖，手动放置的自定义模型不会被自动下载冲掉。

## 手动下载（兜底）

```bash
# 在本目录下执行
BASE=https://raw.githubusercontent.com/opencv/opencv_contrib/master/modules/quality/samples
curl -LO $BASE/brisque_model_live.yml
curl -LO $BASE/brisque_range_live.yml
```

> 注意路径：这两个文件位于 **`opencv_contrib`** 仓库的 `modules/quality/samples/`，**不在 `opencv_extra`**。网上流传的 `opencv_extra/testdata/cv/quality/`（及 `testdata/contrib/quality/`）链接均已失效，会返回 404 的 HTML 页面——若误把该页面存成 `.yml`，文件看着存在却永远加载失败。
>
> 下载后请确认首行为 `%YAML:1.0`：
>
> ```bash
> head -n 1 brisque_model_live.yml   # 预期输出：%YAML:1.0
> ```
>
> 程序内的自动下载同样会校验这一行，非 YAML 内容一律拒绝落盘。

也可浏览器访问 https://github.com/opencv/opencv_contrib/tree/master/modules/quality/samples 手动保存。

## 验证

```bash
python -c "from flashgaze.core.cv_engine import _BRISQUE_API, _BRISQUE_MODEL_DIR; import os; print('api', _BRISQUE_API is not None); print('model', os.path.isfile(_BRISQUE_MODEL_DIR / 'brisque_model_live.yml'))"
```

两行均输出 `True` 即配置完成。

定位本目录（与工作目录无关，按包导入位置解析）：

```bash
python -c "from importlib.resources import files; print(files('flashgaze.models') / 'brisque')"
```

## 依赖

BRISQUE 依赖 `opencv-contrib-python`（基础 `opencv-python` 不含 `cv2.quality` 模块）：

```bash
pip install -e ".[cv-enhanced]"
```

> 注意：`opencv-contrib-python` 与 `opencv-python` 不应同时安装，会冲突。请先卸载 `opencv-python` 再安装 `opencv-contrib-python`。本项目 extras 用的是 headless 变体，与主依赖 `opencv-python-headless` 对应。

## 行为说明

- 文件缺失或依赖未安装时，`compute_noise()` 返回 `None`，不阻塞主流程
- `--enable-noise` 参数仍可传入，但相关字段输出 `null`
- **若 `noise` 返回 `null`，先看启动日志的 `WARNING`**——`CVEngine` 构造时会打印一条排查指引，说明是依赖缺失还是模型文件缺失，以及如何获取（加 `--verbose` 可确保 stderr 可见）
- 该 WARNING 每次构造引擎只打一条，批量评分不会刷屏
- 详见 `flashgaze/models/schemas.py`：`CVResult.noise` 字段定义。

## 许可与来源

模型文件来自 OpenCV 官方仓库 [`opencv/opencv_contrib`](https://github.com/opencv/opencv_contrib)（`modules/quality/samples/`），采用 **Apache License 2.0**（该仓库自 OpenCV 4.x 起的许可，见仓库根目录 `LICENSE`），可随本项目再分发。FlashGaze 自身为 MIT 许可；此处保留对 OpenCV 的来源与许可声明以履行署名义务。
