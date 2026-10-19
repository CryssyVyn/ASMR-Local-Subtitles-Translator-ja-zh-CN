# 第三方来源与许可证

本项目新增的应用代码、启动器和作者整理的 312 条词库采用根目录的 MIT 许可证。下列第三方内容保持各自版权和许可，不因本项目使用 MIT 而变更。

## 随源码附带的第三方代码

**Whispering Tiger / Sharrnah**

- 来源：https://github.com/Sharrnah/whispering
- 固定提交：`9750c19a1eb4dde8309af6ee74888b28d0e27907`
- 内容：`vendor/whispering_tiger/transcription_queue.py` 中的 `RouteTranscriptionQueue`。
- MIT；原版权声明和完整许可保留在 [vendor/whispering_tiger/LICENSE](vendor/whispering_tiger/LICENSE)。
- 来源记录：[SOURCE.txt](vendor/whispering_tiger/SOURCE.txt)。

## 安装时单独下载的模型与运行时

| 组件 | 来源与固定版本 | 上游许可 |
| --- | --- | --- |
| llama.cpp | [ggml-org/llama.cpp b11515](https://github.com/ggml-org/llama.cpp/tree/b11515)；Windows Vulkan / CUDA 12.4 | [MIT](https://github.com/ggml-org/llama.cpp/blob/b11515/LICENSE)；运行时内的其他许可文件一并保留 |
| 日语识别模型 | [Systran/faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small)，提交 `536b0662742c02347bc0e980a01041f333bce120` | [模型卡标注 MIT](https://huggingface.co/Systran/faster-whisper-small/blob/536b0662742c02347bc0e980a01041f333bce120/README.md)，保留 Whisper 上游适用的版权与许可声明 |
| 中文翻译模型 | [mmis1000/asmr-qwen3.5-9b-zh-cn-echo-gguf-v0.1](https://huggingface.co/mmis1000/asmr-qwen3.5-9b-zh-cn-echo-gguf-v0.1)，提交 `0a8504759b493c53bc7a8d57b4ae6b9d00d13b7e`，Q4_K_M | 模型卡标注 Apache-2.0；遵循其基座模型及上游适用许可 |

模型权重、CUDA DLL 和 llama.cpp 二进制没有打入本源码包；安装脚本从官方项目或原作者仓库获取。它们不属于本项目自有模型或代码。重新打包包含这些内容的便携版本时，需同时保留相应许可证、版权声明及适用的 NOTICE。

## Python 与 Python 依赖

Python 需由使用者自行安装，遵循 Python Software Foundation 许可。本项目通过 pip 安装 `requirements-lock.txt` 中的固定版本，不随源码包附带虚拟环境或 wheel 文件。

主要依赖包括 faster-whisper、CTranslate2、PyAudioWPatch、NumPy、SciPy、ONNX Runtime、PyAV 及 Hugging Face Hub。各包许可证和包内第三方声明由 pip 安装包保留；不能将它们统一视为本项目 MIT。将依赖打入新的可执行发行包前，需要按实际打包内容保留这些声明。

## 词库

`词库_保守版_ja_zh.json` 共 312 条，由项目作者整理并授权公开，适用本项目 MIT 许可证。个人作品背景、已保存设备和显示偏好、其他词库文件均未随源码包发布。
