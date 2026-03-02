#!/usr/bin/env node
/**
 * Headless browser helper for Chief (OpenClaw)
 * Usage: node browse.js <url> [action]
 * Actions: screenshot, text, links, title
 */

const { chromium } = require('playwright');

async function browse(url, action = 'text') {
  const browser = await chromium.launch({
    executablePath: '/usr/bin/chromium-browser',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
    headless: true,
  });

  const page = await browser.newPage();
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });

  let result;
  switch (action) {
    case 'screenshot':
      await page.screenshot({ path: '/tmp/screenshot.png', fullPage: false });
      result = 'Screenshot saved to /tmp/screenshot.png';
      break;
    case 'links':
      result = await page.evaluate(() =>
        [...document.querySelectorAll('a[href]')]
          .slice(0, 20)
          .map(a => `${a.innerText.trim()} → ${a.href}`)
          .filter(Boolean)
          .join('\n')
      );
      break;
    case 'title':
      result = await page.title();
      break;
    case 'text':
    default:
      result = await page.evaluate(() => document.body.innerText.slice(0, 3000));
      break;
  }

  await browser.close();
  console.log(result);
}

const [,, url, action] = process.argv;
if (!url) { console.error('Usage: node browse.js <url> [text|links|title|screenshot]'); process.exit(1); }
browse(url, action).catch(e => { console.error(e.message); process.exit(1); });
