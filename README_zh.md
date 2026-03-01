# AI 旅行电影

> 把原始旅行素材变成电影感短片 —— 零手动剪辑，全程 AI 驱动。

**一条命令。五幕叙事。专业输出。**

```bash
python travel_film.py --config my_trip.json --lang zh
```

## 它做什么

指向你的素材文件夹 → 自动分析每个片段（运动能量、亮度、分辨率、帧率）→ 选出最精彩的瞬间 → 按五幕电影叙事结构编排 → 加入 crossfade 转场、调色、BGM、TTS 旁白 → 输出可直接发布的视频。

### 五幕叙事结构

| 幕 | 作用 | 推荐素材 | 速度 |
|---|------|---------|------|
| **钩子** | 3秒抓住观众 | 无人机航拍 | 0.35x 慢动作 |
| **启程** | 建立期待感 | 航拍/广角 | 1.0x 正常 |
| **在路上** | 路途的运动感 | 运动相机 | 1.0x + 防抖 |
| **高潮** | 时间凝固，情绪顶点 | 4K 相机 | 0.4x 慢动作 |
| **余韵** | 回望与释然 | 航拍远景 | 0.5x 慢动作 |

## 快速开始

### 前置条件

- **Python 3.9+**
- **ffmpeg** 在 PATH 中（`winget install ffmpeg` 或 `brew install ffmpeg`）
- （可选）`pip install edge-tts` 用于 AI 旁白

### 最快上手（零配置）

```bash
# 自动扫描电脑里的视频文件夹
python travel_film.py --auto --lang zh
```

### 自定义配置

```bash
# 1. 复制示例配置
cp example_config.json my_trip.json

# 2. 编辑 my_trip.json，指向你的素材：
# "source_dirs": [
#   ["D:/旅行视频/航拍", "aerial", "大疆无人机"],
#   ["D:/旅行视频/运动相机", "action", "GoPro"],
#   ["D:/旅行视频/相机", "camera", "索尼A7"]
# ]

# 3. 构建
python travel_film.py --config my_trip.json --lang zh

# 4. 竖屏版（抖音/快手）
python travel_film.py --config my_trip.json --lang zh --vertical
```

### 输出文件

```
output/
├── travel_film.mp4          # 成品视频（可直接发布）
├── travel_film.srt          # 字幕文件
├── travel_film_cover.jpg    # 封面图
├── report.json              # 制作报告
└── clips/                   # 提取的精华片段
```

## 素材分类建议

| 类型 | 适合的设备 | 叙事作用 |
|------|-----------|---------|
| `aerial` | 大疆无人机、航拍 | 开场震撼 + 收尾远景 |
| `action` | GoPro、DJI Action、手机 | 在路上的运动感 |
| `camera` | 索尼/佳能/富士相机 | 高潮段的4K慢动作 |

**建议**：把不同设备的素材放在不同文件夹，脚本会根据叙事需要自动选择。

## 配置参数

| 参数 | 说明 |
|------|------|
| `source_dirs` | 素材目录列表，每项 `[路径, 类型, 名称]` |
| `output_dir` | 输出目录 |
| `bgm_path` | BGM 文件路径，留空则自动合成 |
| `trip_dates` | 旅行日期，匹配的素材会被优先选择 |
| `tts_voice` | TTS 语音，中文用 `zh-CN-YunxiNeural` |
| `crf` | 视频质量（17=高, 23=中, 28=低） |

## 免费 BGM 来源

- [Incompetech](https://incompetech.com/music/royalty-free/) — Kevin MacLeod, CC BY 4.0
- [Pixabay Music](https://pixabay.com/music/) — 免费商用
- [Free Music Archive](https://freemusicarchive.org/) — 多种 CC 协议

## 技术原理

```
素材扫描 → 运动分析 → 智能选片 → 提取+调色
    ↓           ↓          ↓           ↓
  59个素材   亮度+运动    5幕叙事    crossfade+
  元数据     评分        结构       curves调色
                                        ↓
                              TTS旁白 → 分幕拼接
                                        ↓
                              BGM混音(loudnorm -16 LUFS)
                                        ↓
                              字幕烧入 → 最终输出
```

**零重依赖**。不需要 moviepy、opencv、tensorflow。只用 Python 标准库 + ffmpeg。

## 协议

MIT — 随便用。

## 致谢

使用 [Windsurf](https://windsurf.com) IDE + Cascade AI 结对编程构建。
