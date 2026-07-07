const { chromium } = require('playwright');
const url = process.argv[2] || 'https://deploy-life-alpha.vercel.app';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', err => errors.push('PAGE: ' + err.message));
  page.on('console', msg => { if (msg.type() === 'error') errors.push('CONSOLE: ' + msg.text()); });

  await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(4000);

  const title = await page.title();
  const count = await page.textContent('#count');
  const canvases = await page.$$('canvas');
  const circles = await page.$$('circle');
  const labels = await page.$$('div.css2d-label');

  const realErrors = errors.filter(e => !e.includes('GPU stall') && !e.includes('WebGL'));
  const ok = realErrors.length === 0;

  console.log(JSON.stringify({
    ok, title, count,
    canvases: canvases.length,
    nodes3d: circles.length,
    labels: labels.length,
    errors: realErrors
  }, null, 2));

  process.exit(ok ? 0 : 1);
})();
