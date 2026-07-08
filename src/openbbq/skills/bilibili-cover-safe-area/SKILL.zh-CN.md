---
name: bilibili-cover-safe-area
description: 从已 fetch 的 YouTube 或视频缩略图制作 Bilibili/B站视频封面，尤其适用于用户用中文说“制作B站封面”、“制作bilibili封面”、“做一下B站封面”、“投稿封面”、“视频封面”、“帮我制作一下bilibili的封面吧”，或要求准备 Bilibili 上传封面。仅使用 FFmpeg 将 16:9 缩略图转换成 Bilibili 安全的 1280x960 4:3 图片，在正中保留原始 1280x720 缩略图，并用模糊延展填充上下边。
---

# Bilibili Cover Safe Area

## 概览

用 FFmpeg 把 fetch 下来的 YouTube 封面转换成 Bilibili 兼容封面，确保 4:3 展示和 16:9 中心裁切都可用。

只要用户是在已有 fetch 缩略图或视频封面的前提下要求制作 Bilibili/B站 封面，就使用这个 skill；即使用户没有提到安全区、4:3、模糊补边或缩略图转换，也应当命中。若当前没有现成缩略图或源图片，先要求提供或先 fetch 视频缩略图；本 skill 负责封面格式转换，不负责从零自由设计封面。

默认输出约定：

- 总画布：`1280x960`（`4:3`）
- 中心安全区：`1280x720`（`16:9`）
- 补边：顶部 `120px`，底部 `120px`
- 补边样式：原图模糊延展，不使用纯色边
- 边缘清理：缩放前从原图四边各裁掉 `2px`，去除 fetch 封面常见的边框伪影

## 命令

处理单张 fetch 封面：

```bash
ffmpeg -y -i "thumbnail.webp" -filter_complex "[0:v]crop=iw-4:ih-4:2:2,split=2[bg][fg];[bg]scale=1280:960:force_original_aspect_ratio=increase,crop=1280:960,gblur=sigma=24[bg];[fg]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2[fg];[bg][fg]overlay=0:120,format=yuvj420p[out]" -map "[out]" -frames:v 1 -update 1 -q:v 2 "cover_bilibili_4x3.jpg"
```

输出 PNG 时，把 `format=yuvj420p` 改成 `format=rgb24`：

```bash
ffmpeg -y -i "thumbnail.webp" -filter_complex "[0:v]crop=iw-4:ih-4:2:2,split=2[bg][fg];[bg]scale=1280:960:force_original_aspect_ratio=increase,crop=1280:960,gblur=sigma=24[bg];[fg]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2[fg];[bg][fg]overlay=0:120,format=rgb24[out]" -map "[out]" -frames:v 1 -update 1 "cover_bilibili_4x3.png"
```

## 变体

如果必须完整保留原图边缘像素，去掉第一个 `crop` 滤镜：

```bash
ffmpeg -y -i "thumbnail.webp" -filter_complex "[0:v]split=2[bg][fg];[bg]scale=1280:960:force_original_aspect_ratio=increase,crop=1280:960,gblur=sigma=24[bg];[fg]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2[fg];[bg][fg]overlay=0:120,format=yuvj420p[out]" -map "[out]" -frames:v 1 -update 1 -q:v 2 "cover_bilibili_4x3.jpg"
```

调整 `gblur=sigma=24` 可以改变背景模糊强度。常用范围是 `18-36`。

## 批量处理

Shell 循环示例：

```bash
mkdir -p covers
for f in thumbnails/*.{jpg,jpeg,png,webp}; do
  [ -e "$f" ] || continue
  base="$(basename "${f%.*}")"
  ffmpeg -y -i "$f" -filter_complex "[0:v]crop=iw-4:ih-4:2:2,split=2[bg][fg];[bg]scale=1280:960:force_original_aspect_ratio=increase,crop=1280:960,gblur=sigma=24[bg];[fg]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2[fg];[bg][fg]overlay=0:120,format=yuvj420p[out]" -map "[out]" -frames:v 1 -update 1 -q:v 2 "covers/${base}_bilibili_4x3.jpg"
done
```

## 验证

确认输出尺寸：

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "cover_bilibili_4x3.jpg"
```

预期输出：

```text
1280,960
```

重要上传前，目视检查中心 `1280x720` 区域是否保留目标封面，以及边缘伪影是否已经消失。
