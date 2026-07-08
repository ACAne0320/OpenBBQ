---
name: bilibili-cover-safe-area
description: Make Bilibili/B站 video covers from fetched YouTube or video thumbnails, especially when the user asks in Chinese for “制作B站封面”, “制作bilibili封面”, “做一下B站封面”, “投稿封面”, “视频封面”, “帮我制作一下bilibili的封面吧”, or asks to prepare a cover for Bilibili upload. Convert 16:9 thumbnails into Bilibili-safe 1280x960 4:3 images using FFmpeg only, preserving the original 1280x720 thumbnail in the exact center with blurred padding above and below.
---

# Bilibili Cover Safe Area

## Overview

Use FFmpeg to convert fetched YouTube thumbnails into Bilibili-compatible cover images that work for both 4:3 display and 16:9 center cropping.

Use this skill whenever the user asks to make a Bilibili/B站 cover for a video that already has a fetched thumbnail, even if they do not mention safe area, 4:3, blur padding, or thumbnail conversion. If there is no existing thumbnail or source image, first ask for or fetch the video thumbnail; this skill is for cover-format conversion, not freeform cover design from scratch.

The output contract is:

- Full canvas: `1280x960` (`4:3`)
- Safe center: `1280x720` (`16:9`)
- Padding: `120px` top and `120px` bottom
- Padding style: blurred extension from the source image, not solid color
- Edge cleanup: crop `2px` from each source edge before resizing to remove common fetched-thumbnail border artifacts

## Command

Use this command for one fetched thumbnail:

```bash
ffmpeg -y -i "thumbnail.webp" -filter_complex "[0:v]crop=iw-4:ih-4:2:2,split=2[bg][fg];[bg]scale=1280:960:force_original_aspect_ratio=increase,crop=1280:960,gblur=sigma=24[bg];[fg]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2[fg];[bg][fg]overlay=0:120,format=yuvj420p[out]" -map "[out]" -frames:v 1 -update 1 -q:v 2 "cover_bilibili_4x3.jpg"
```

Use `format=rgb24` instead of `format=yuvj420p` when writing PNG:

```bash
ffmpeg -y -i "thumbnail.webp" -filter_complex "[0:v]crop=iw-4:ih-4:2:2,split=2[bg][fg];[bg]scale=1280:960:force_original_aspect_ratio=increase,crop=1280:960,gblur=sigma=24[bg];[fg]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2[fg];[bg][fg]overlay=0:120,format=rgb24[out]" -map "[out]" -frames:v 1 -update 1 "cover_bilibili_4x3.png"
```

## Variants

Preserve every source edge pixel exactly by removing the first crop filter:

```bash
ffmpeg -y -i "thumbnail.webp" -filter_complex "[0:v]split=2[bg][fg];[bg]scale=1280:960:force_original_aspect_ratio=increase,crop=1280:960,gblur=sigma=24[bg];[fg]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2[fg];[bg][fg]overlay=0:120,format=yuvj420p[out]" -map "[out]" -frames:v 1 -update 1 -q:v 2 "cover_bilibili_4x3.jpg"
```

Tune blur strength by changing `gblur=sigma=24`. Values around `18-36` usually work well.

## Batch

For a shell loop:

```bash
mkdir -p covers
for f in thumbnails/*.{jpg,jpeg,png,webp}; do
  [ -e "$f" ] || continue
  base="$(basename "${f%.*}")"
  ffmpeg -y -i "$f" -filter_complex "[0:v]crop=iw-4:ih-4:2:2,split=2[bg][fg];[bg]scale=1280:960:force_original_aspect_ratio=increase,crop=1280:960,gblur=sigma=24[bg];[fg]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2[fg];[bg][fg]overlay=0:120,format=yuvj420p[out]" -map "[out]" -frames:v 1 -update 1 -q:v 2 "covers/${base}_bilibili_4x3.jpg"
done
```

## Verification

Confirm output dimensions:

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "cover_bilibili_4x3.jpg"
```

Expected output:

```text
1280,960
```

For critical uploads, visually inspect that the central `1280x720` region preserves the intended cover and that no source-edge border remains.
