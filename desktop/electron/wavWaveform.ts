import { readFileSync } from "node:fs";

import type { WaveformBar } from "../src/lib/types.js";

type WavFormat = {
  bitsPerSample: number;
  blockAlign: number;
  channels: number;
  format: number;
};

type WavData = {
  dataOffset: number;
  dataSize: number;
  format: WavFormat;
};

const pcmFormat = 1;
const audibleNoiseFloor = 10 ** (-45 / 20);
const minAudibleLevel = 4;
const maxLevel = 96;

export function waveformFromPcm16WavFile(filePath: string, barCount: number): WaveformBar[] | null {
  try {
    return waveformFromPcm16Wav(readFileSync(filePath), barCount);
  } catch {
    return null;
  }
}

export function waveformFromPcm16Wav(buffer: Buffer, barCount: number): WaveformBar[] | null {
  const wav = parseWav(buffer);
  if (!wav || wav.format.format !== pcmFormat || wav.format.bitsPerSample !== 16 || wav.format.channels <= 0) {
    return null;
  }

  const count = Math.max(1, Math.floor(barCount));
  const frameSize = wav.format.blockAlign;
  const frameCount = Math.floor(wav.dataSize / frameSize);
  if (frameCount <= 0) {
    return null;
  }

  const rmsLevels = Array.from({ length: count }, (_, index) => {
    const startFrame = Math.floor((index / count) * frameCount);
    const endFrame = Math.max(startFrame + 1, Math.floor(((index + 1) / count) * frameCount));
    let sampleCount = 0;
    let squareTotal = 0;

    for (let frame = startFrame; frame < endFrame && frame < frameCount; frame += 1) {
      const frameOffset = wav.dataOffset + frame * frameSize;
      for (let channel = 0; channel < wav.format.channels; channel += 1) {
        const sampleOffset = frameOffset + channel * 2;
        if (sampleOffset + 2 > buffer.length) {
          continue;
        }
        const normalized = buffer.readInt16LE(sampleOffset) / 32768;
        squareTotal += normalized * normalized;
        sampleCount += 1;
      }
    }

    return sampleCount > 0 ? Math.sqrt(squareTotal / sampleCount) : 0;
  });

  const peak = Math.max(...rmsLevels);
  if (peak <= audibleNoiseFloor) {
    return rmsLevels.map((_, index) => waveformBar(index, 0));
  }

  return rmsLevels.map((rms, index) => {
    if (rms <= audibleNoiseFloor) {
      return waveformBar(index, 0);
    }

    const normalized = (rms - audibleNoiseFloor) / Math.max(peak - audibleNoiseFloor, Number.EPSILON);
    const ratio = Math.sqrt(Math.min(1, Math.max(0, normalized)));
    return waveformBar(index, Math.round(minAudibleLevel + ratio * (maxLevel - minAudibleLevel)));
  });
}

function parseWav(buffer: Buffer): WavData | null {
  if (buffer.length < 44 || buffer.toString("ascii", 0, 4) !== "RIFF" || buffer.toString("ascii", 8, 12) !== "WAVE") {
    return null;
  }

  let offset = 12;
  let format: WavFormat | null = null;
  let dataOffset = -1;
  let dataSize = 0;

  while (offset + 8 <= buffer.length) {
    const chunkId = buffer.toString("ascii", offset, offset + 4);
    const chunkSize = buffer.readUInt32LE(offset + 4);
    const chunkStart = offset + 8;
    const chunkEnd = chunkStart + chunkSize;
    if (chunkEnd > buffer.length) {
      return null;
    }

    if (chunkId === "fmt ") {
      if (chunkSize < 16) {
        return null;
      }
      format = {
        format: buffer.readUInt16LE(chunkStart),
        channels: buffer.readUInt16LE(chunkStart + 2),
        bitsPerSample: buffer.readUInt16LE(chunkStart + 14),
        blockAlign: buffer.readUInt16LE(chunkStart + 12)
      };
    } else if (chunkId === "data") {
      dataOffset = chunkStart;
      dataSize = chunkSize;
    }

    offset = chunkEnd + (chunkSize % 2);
  }

  if (!format || dataOffset < 0 || dataSize <= 0) {
    return null;
  }

  return { dataOffset, dataSize, format };
}

function waveformBar(index: number, level: number): WaveformBar {
  return {
    id: `bar-${index.toString().padStart(3, "0")}`,
    level
  };
}
