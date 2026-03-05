# PokeClaw

[English](README_EN.md) | [中文](README.md)

![PokeClaw Demo](assets/screenshots/picture_demo.jpg)

<video src="https://github.com/raphaelxiao/pizero-openclaw/raw/main/assets/screenshots/video_demo.mp4" controls="controls" width="800"></video>

PokeClaw 是一个基于 Raspberry Pi Zero W 搭配 [PiSugar WhisPlay 扩展板](https://www.pisugar.com) 构建的语音控制 AI 桌面机器人。按下实体按键即可语音对话，它不仅能通过屏幕实时显示流式回复，还会配以生动的角色动画（默认角色包含卡比与龙虾）以及语音播报。

**PokeClaw** 脱胎于开源项目 [pizero-openclaw](https://github.com/sebastianvkl/pizero-openclaw)，在此 特别感谢原作者 [sebastianvkl](https://github.com/sebastianvkl) 的 MIT 开源贡献，为本项目提供了扎实的硬件驱动和通信基础框架！

## 工作原理

```
按下按键 → 录制音频 → 语音转文字 (OpenAI/Gemini/GLM) → 流式输出大模型回复 (OpenClaw) → 实时滚动显示在 1.54寸 LCD 屏幕上
                                                                                                  ↓
                                                                                        (可选) 文字转语音 (TTS) 播报
```

1. **长按** 实体按键，通过 ALSA 驱动录制您的声音
2. **松开** 按键 — 录音会被发送至 OpenAI, Gemini, 或智谱 GLM 进行极速语音识别 (约需 0.7秒)
3. 识别出的文字会发送至您的 **[OpenClaw](https://openclaw.ai) 网关** 获取大模型回复
4. 大模型的回复将像打字机一样 **实时流式滚动** 显示在屏幕上，并支持像素级的自动换行
5. _(可选)_ 支持通过 TTS 当句子完结时同步 **语音播报**
6. 待机界面会显示时钟、日期、电池电量和 Wi-Fi 状态
7. 角色动画会根据当前状态流利地在 听(listening)、思考(thinking) 和 说话(talking) 之间平滑切换。说话时还会**根据 TTS 播报音量实时对口型**！

设备本身集成了 **静音过滤**（纯背景底噪不会发给云端），而在云端则支持通过内置的 Session 机制自动记住您的**上下文聊天历史**。

## 硬件清单

- **Raspberry Pi Zero 2 W** (或 Pi Zero W)
- **[PiSugar WhisPlay 扩展板](https://www.pisugar.com)** — 自带 1.54寸 LCD屏幕 (240x240)、对讲实体按键、LED灯、扬声器和麦克风
- **PiSugar 电池** (可选) — 屏幕支持直接读取并显示剩余电量

## 安装配置

### 系统要求

- Raspberry Pi OS (强烈建议 Bookworm 或以上版本)
- Python 3.11+
- 大模型 API 的密钥（支持 OpenAI, Google Gemini, 或 智谱 GLM 的 STT 与 TTS）
- 部署在网络上可访问的 [OpenClaw](https://openclaw.ai) 路由网关

### 安装依赖包

> [!IMPORTANT]
> 此项目支持在屏幕上渲染中文回复，因此**必须**安装中文字体库 (`fonts-wqy-microhei`) 以防出现乱码。

```bash
sudo apt install python3-numpy python3-pil fonts-wqy-microhei
pip install requests python-dotenv
```

此外，请务必根据 [PiSugar WhisPlay 官方指南](https://github.com/PiSugar/whisplay-ai-chatbot) 正确安装和加载屏幕及声卡驱动。

### 环境变量配置

复制附带的配置模板并填入您的 API 密钥：

```bash
cp .env.example .env
```

编辑 `.env`：

```bash
export OPENAI_API_KEY="sk-your-openai-api-key"
export AUDIO_PROVIDER="glm" # 语音引擎选项: "openai", "gemini", 或者是 "glm"
export DISPLAY_CHARACTER="lobster" # 默认自带了 "kirby" 卡比和 "lobster" 龙虾两个角色
export PI_USER="pi" # 如果您的树莓派默认用户名不是 pi，请在此修改
export GLM_API_KEY="your-glm-api-key"
export OPENCLAW_TOKEN="your-openclaw-gateway-token"
```

### 运行程序

```bash
python3 -m core.main
```

或者使用下方的守护进程脚本一键部署在后台。

## 高级环境变量速查表

部分高级配置依赖环境变量，你可以通过修改根目录的 `.env` 以及编辑代码库中的 `core/config.py` 来灵活配置：

| 变量名 | 默认值 | 用途说明 |
|---|---|---|
| `AUDIO_PROVIDER` | `openai` | STT & TTS 服务提供商 (`openai`, `gemini`, `glm`) |
| `DISPLAY_CHARACTER` | `kirby` | 屏幕使用的默认角色动画集合 (`kirby`, `lobster`) |
| `OPENAI_API_KEY` | _(如果用 openai 则必填)_ | OpenAI 开发者密钥 |
| `GEMINI_API_KEY` | _(如果用 gemini 则必填)_ | Google Gemini 开发者密钥 |
| `GLM_API_KEY`    | _(如果用 glm 则必填)_    | 智谱大模型开发者密钥 |
| `OPENCLAW_TOKEN` | _(必填)_ | OpenClaw 网关的认证密钥 |
| `OPENCLAW_BASE_URL` | `https://...` | 您的私有 OpenClaw 网关地址 |
| `ENABLE_TTS` | `false` | 是否开启机器人的语音朗读功能 |
| `LCD_BACKLIGHT` | `70` | 屏幕背光亮度 (0–100) |
| `SILENCE_RMS_THRESHOLD` | `200` | 环境音量低于此时过滤不上报云端 |

*(更多冷门配置请参阅 `.env.example` 中的详细注释)*

## TO-DO 计划任务

- [ ] 接入并支持更多底层模型 API
- [ ] 开发更多角色动画，并支持更丰富的情感表情支持（开心、生气、伤心等）

## License 许可

MIT License

本项目最初 Fork 自 [pizero-openclaw](https://github.com/sebastianvkl/pizero-openclaw)，感谢原开源社区的支持！
