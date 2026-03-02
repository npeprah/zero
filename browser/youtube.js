#!/usr/bin/env node
/**
 * YouTube transcript fetcher using yt-dlp
 * Usage: node youtube.js <youtube-url-or-video-id>
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

function extractVideoId(input) {
  const patterns = [
    /youtube\.com\/watch\?v=([^&\s]+)/,
    /youtu\.be\/([^?\s]+)/,
    /youtube\.com\/shorts\/([^?\s]+)/,
  ];
  for (const p of patterns) {
    const m = input.match(p);
    if (m) return m[1];
  }
  return input; // assume it's already an ID
}

function parseTtml(content) {
  // Extract text from TTML subtitle file
  return content
    .replace(/<[^>]+>/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, ' ')
    .trim();
}

async function getTranscript(input) {
  const videoId = extractVideoId(input);
  const tmpDir = os.tmpdir();
  const outBase = path.join(tmpDir, `yt_${videoId}`);

  // Clean up any existing files
  for (const ext of ['.en.ttml', '.en.vtt', '.en.srt']) {
    try { fs.unlinkSync(outBase + ext); } catch {}
  }

  try {
    execSync(
      `yt-dlp --write-auto-sub --sub-lang en --skip-download --sub-format ttml -o "${outBase}" "https://www.youtube.com/watch?v=${videoId}" --quiet`,
      { timeout: 30000 }
    );
  } catch (e) {
    // Try VTT as fallback
    try {
      execSync(
        `yt-dlp --write-auto-sub --sub-lang en --skip-download --sub-format vtt -o "${outBase}" "https://www.youtube.com/watch?v=${videoId}" --quiet`,
        { timeout: 30000 }
      );
    } catch (e2) {
      console.error('Could not fetch subtitles:', e2.message);
      process.exit(1);
    }
  }

  // Find the downloaded subtitle file
  const files = fs.readdirSync(tmpDir).filter(f => f.startsWith(`yt_${videoId}`));
  if (!files.length) {
    console.error('No subtitle file found — video may not have captions.');
    process.exit(1);
  }

  const content = fs.readFileSync(path.join(tmpDir, files[0]), 'utf8');
  const text = parseTtml(content);

  // Truncate for context window
  const maxLen = 8000;
  console.log(text.slice(0, maxLen));
  if (text.length > maxLen) {
    console.log(`\n...[transcript truncated at ${maxLen} chars, full length: ${text.length}]`);
  }

  // Cleanup
  files.forEach(f => { try { fs.unlinkSync(path.join(tmpDir, f)); } catch {} });
}

const input = process.argv[2];
if (!input) {
  console.error('Usage: node youtube.js <youtube-url-or-id>');
  process.exit(1);
}

getTranscript(input).catch(e => {
  console.error('Error:', e.message);
  process.exit(1);
});
