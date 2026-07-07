---
name: bilibili-cover-safe-area
description: 仅使用 FFmpeg 将 YouTube 或其他 16:9 视频封面处理成适合 Bilibili 上传的 1280x960 4:3 封面，并在正中保留完整 1280x720 16:9 安全区，上下用原图模糊延展补边。适用于 Bilibili 封面、4:3 画布加 16:9 安全区、模糊补边、YouTube thumbnail 转换、批量处理 fetch 后的视频封面。
---

# Bilibili Cover Safe Area

## 概览

用 FFmpeg 把 fetch 下来的 YouTube 封面转换成 Bilibili 兼容封面，确保 4:3 展示和 16:9 中心裁切都可用。

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
