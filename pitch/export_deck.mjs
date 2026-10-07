import { spawn } from 'node:child_process';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';

import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PITCH_DIR = __dirname;
const SLIDES_DIR = path.join(PITCH_DIR, 'slides');
const PDF_OUTPUT_PITCH = path.join(PITCH_DIR, 'Legible_Pitch.pdf');
const PDF_OUTPUT_ROOT = path.resolve(PITCH_DIR, '..', 'Legible_Pitch.pdf');
const SWIFT_SCRIPT = path.join(PITCH_DIR, 'compile_pdf.swift');

fs.mkdirSync(SLIDES_DIR, { recursive: true });

// 1. Start HTTP server to serve pitch deck
const server = http.createServer((req, res) => {
  let reqPath = decodeURI(req.url.split('?')[0]);
  if (reqPath === '/' || reqPath === '') reqPath = '/index.html';
  const filePath = path.join(PITCH_DIR, reqPath);

  if (!fs.existsSync(filePath)) {
    res.writeHead(404);
    return res.end('Not found');
  }

  const stat = fs.statSync(filePath);
  if (stat.isDirectory()) {
    res.writeHead(404);
    return res.end('Not found');
  }

  const ext = path.extname(filePath).toLowerCase();
  const mimeMap = {
    '.html': 'text/html',
    '.css': 'text/css',
    '.js': 'application/javascript',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
    '.woff2': 'font/woff2'
  };

  res.writeHead(200, { 'Content-Type': mimeMap[ext] || 'application/octet-stream' });
  fs.createReadStream(filePath).pipe(res);
});

await new Promise(r => server.listen(0, '127.0.0.1', r));
const serverPort = server.address().port;
console.log(`Pitch deck server running on port ${serverPort}`);

// 2. Launch headless Chrome
const cdpPort = 9228;
const tmpUserData = `/tmp/chrome-pitch-${Date.now()}`;
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', [
  '--headless',
  '--disable-gpu',
  '--no-first-run',
  '--no-default-browser-check',
  `--remote-debugging-port=${cdpPort}`,
  `--user-data-dir=${tmpUserData}`,
  'about:blank'
], { stdio: 'ignore' });

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function run() {
  try {
    let wsUrl = null;
    for (let i = 0; i < 30; i++) {
      try {
        const res = await fetch(`http://127.0.0.1:${cdpPort}/json/version`);
        if (res.ok) {
          wsUrl = (await res.json()).webSocketDebuggerUrl;
          break;
        }
      } catch (e) {
        await sleep(200);
      }
    }
    if (!wsUrl) throw new Error('Could not connect to Chrome debugging port');

    const newPageRes = await fetch(`http://127.0.0.1:${cdpPort}/json/new?http://127.0.0.1:${serverPort}/index.html`, { method: 'PUT' });
    const newPage = await newPageRes.json();
    const ws = new WebSocket(newPage.webSocketDebuggerUrl);

    let id = 1;
    const callbacks = new Map();
    ws.onmessage = evt => {
      const msg = JSON.parse(evt.data);
      if (msg.id && callbacks.has(msg.id)) {
        const { resolve, reject } = callbacks.get(msg.id);
        callbacks.delete(msg.id);
        if (msg.error) reject(msg.error);
        else resolve(msg.result);
      }
    };
    const send = (method, params = {}) => new Promise((resolve, reject) => {
      const reqId = id++;
      callbacks.set(reqId, { resolve, reject });
      ws.send(JSON.stringify({ id: reqId, method, params }));
    });
    await new Promise(r => ws.onopen = r);

    await send('Page.enable');
    await send('Runtime.enable');

    // 1600x900 viewport, 2x scale for Retina sharpness
    await send('Emulation.setDeviceMetricsOverride', {
      width: 1600,
      height: 900,
      deviceScaleFactor: 2,
      mobile: false
    });

    // Wait for fonts and assets to finish loading
    await sleep(2000);

    // Prepare page styling for export (hide overlay hints, disable animation delays)
    await send('Runtime.evaluate', {
      expression: `(() => {
        const style = document.createElement('style');
        style.id = 'export-deck-styles';
        style.textContent = \`
          #help, .navzone, #notes { display: none !important; }
          .slide.active .r { animation: none !important; opacity: 1 !important; transform: none !important; }
          .slide.active .rl > span { animation: none !important; transform: none !important; }
          .skyline i { animation: none !important; transform: none !important; }
          .card .art .d { stroke-dashoffset: 0 !important; animation: none !important; }
          .arrow b { animation: none !important; opacity: 1 !important; transform: none !important; }
          .mod { animation: none !important; opacity: 1 !important; transform: none !important; }
          .chip { opacity: 1 !important; transform: none !important; }
        \`;
        document.head.appendChild(style);
      })()`
    });

    // Define slide sequence
    // Slides 0 through 12, with sub-steps for slide 7 (id s-ask, 3 steps) and slide 8 (id s-check, 2 steps)
    const slideItems = [
      { slideIndex: 0, step: null, label: '01 · Title' },
      { slideIndex: 1, step: null, label: '02 · Why' },
      { slideIndex: 2, step: null, label: '03 · Voices' },
      { slideIndex: 3, step: null, label: '04 · LLMs get the speaker wrong' },
      { slideIndex: 4, step: null, label: '05 · Sweep' },
      { slideIndex: 5, step: null, label: '06 · Solution' },
      { slideIndex: 6, step: null, label: '07 · How it works' },
      { slideIndex: 7, step: 0, label: '08 · Live app: ask (Step 1)' },
      { slideIndex: 7, step: 1, label: '08 · Live app: ask (Step 2)' },
      { slideIndex: 7, step: 2, label: '08 · Live app: ask (Step 3)' },
      { slideIndex: 8, step: 0, label: '09 · Live app: check a draft (Step 1)' },
      { slideIndex: 8, step: 1, label: '09 · Live app: check a draft (Step 2)' },
      { slideIndex: 9, step: null, label: '10 · Benchmarks' },
      { slideIndex: 10, step: null, label: '11 · Trust metrics' },
      { slideIndex: 11, step: null, label: '12 · Built in a day' },
      { slideIndex: 12, step: null, label: '13 · Close' }
    ];

    const totalPages = slideItems.length;
    const capturedImages = [];

    for (let pageNum = 1; pageNum <= totalPages; pageNum++) {
      const item = slideItems[pageNum - 1];
      console.log(`Rendering [${pageNum}/${totalPages}] ${item.label}...`);

      await send('Runtime.evaluate', {
        expression: `(() => {
          const slides = document.querySelectorAll('.slide');
          slides.forEach(s => s.classList.remove('active'));
          const currentSlide = slides[${item.slideIndex}];
          currentSlide.classList.add('active');
          document.getElementById('stage').classList.toggle('dark-on', currentSlide.classList.contains('dark'));
          
          const prog = document.getElementById('progress');
          if (prog) prog.style.width = '${(pageNum / totalPages) * 100}%';

          const count = document.getElementById('ccount');
          if (count) count.textContent = '${String(pageNum).padStart(2, '0')} / ${String(totalPages).padStart(2, '0')}';

          ${item.step !== null ? `
            // Set step
            const imgs = currentSlide.querySelectorAll('.view img');
            const lis = currentSlide.querySelectorAll('.steps li[data-step]');
            imgs.forEach(im => im.classList.toggle('on', +im.dataset.step === ${item.step}));
            lis.forEach(li => li.classList.toggle('on', +li.dataset.step === ${item.step}));
          ` : ''}

          // Trigger / complete all dynamic states
          if (currentSlide.id === 's-red') {
            const rhl = currentSlide.querySelector('#redhl');
            if (rhl) rhl.classList.add('on');
          }
          if (currentSlide.id === 's-rg') {
            currentSlide.querySelectorAll('.hb i').forEach(b => {
              if (b.dataset.w) b.style.width = b.dataset.w + '%';
            });
            currentSlide.querySelectorAll('#rg .cell.g, #rg .cell.p').forEach(c => {
              c.className = 'cell p';
              c.textContent = 'P';
            });
          }
        })()`
      });

      await sleep(150);

      const shot = await send('Page.captureScreenshot', { format: 'png' });
      const imgPath = path.join(SLIDES_DIR, `slide-${String(pageNum).padStart(2, '0')}.png`);
      fs.writeFileSync(imgPath, Buffer.from(shot.data, 'base64'));
      capturedImages.push(imgPath);
    }

    console.log(`Captured all ${totalPages} slides as PNG.`);
    ws.close();

    // 3. Compile slides into PDF using Swift CoreGraphics
    console.log('Compiling slides into PDF presentation...');
    const swiftProc = spawn('/usr/bin/swift', [
      SWIFT_SCRIPT,
      PDF_OUTPUT_PITCH,
      ...capturedImages
    ]);

    await new Promise((resolve, reject) => {
      swiftProc.on('close', code => {
        if (code === 0) resolve();
        else reject(new Error(`Swift compile exited with code ${code}`));
      });
    });

    // Also copy to root for easy Slack drag & drop
    fs.copyFileSync(PDF_OUTPUT_PITCH, PDF_OUTPUT_ROOT);

    const stats = fs.statSync(PDF_OUTPUT_PITCH);
    console.log(`SUCCESS! Pitch PDF exported to:`);
    console.log(`  - ${PDF_OUTPUT_PITCH} (${(stats.size / 1024 / 1024).toFixed(2)} MB)`);
    console.log(`  - ${PDF_OUTPUT_ROOT}`);
  } finally {
    server.close();
    chrome.kill();
    await sleep(300);
    fs.rmSync(tmpUserData, { recursive: true, force: true });
  }
}

run().catch(err => {
  console.error('Export failed:', err);
  server.close();
  chrome.kill();
  process.exit(1);
});
