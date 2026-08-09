# BRISQUE 模型文件

本目录存放 BRISQUE 无参考 IQA 评分所需的模型文件。**模型文件不随源码分发**，需用户自行下载。

## 必需文件

| 文件 | 用途 |
|---|---|
| `brisque_model_live.yml` | BRISQUE SVR 模型 |
| `brisque_range_live.yml` | BRISQUE 特征归一化范围 |

## 下载方法

### 方法 1：从 OpenCV 官方仓库下载

```bash
# 在本目录下执行
curl -LO https://github.com/opencv/opencv_extra/raw/master/testdata/cv/quality/brisque_model_live.yml
curl -LO https://github.com/opencv/opencv_extra/raw/master/testdata/cv/quality/brisque_range_live.yml
```

### 方法 2：手动下载

访问 https://github.com/opencv/opencv_extra/tree/master/testdata/cv/quality ，将上述两个文件下载到本目录。

## 验证

```bash
python -c "from flashgaze.core.cv_engine import _BRISQUE_API, _BRISQUE_MODEL_DIR; print('available:', _BRISQUE_API is not None and _BRISQUE_MODEL_DIR is not None)"
```

输出 `available: True` 即配置完成。

定位本目录（与工作目录无关，按包导入位置解析）：

```bash
python -c "from importlib.resources import files; print(files('flashgaze.models') / 'brisque')"
```

## 依赖

BRISQUE 依赖 `opencv-contrib-python`（基础 `opencv-python` 不含 `cv2.quality` 模块）：

```bash
pip install opencv-contrib-python>=4.8
```

> 注意：`opencv-contrib-python` 与 `opencv-python` 不应同时安装，会冲突。请先卸载 `opencv-python` 再安装 `opencv-contrib-python`。

## 行为说明

- 文件缺失或依赖未安装时，`compute_noise()` 返回 `None`，不阻塞主流程
- `--enable-noise` 参数仍可传入，但相关字段输出 `null`
- 详见 `flashgaze/models/schemas.py`：`CVResult.noise` 字段定义。