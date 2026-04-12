#!/usr/bin/env node
/**
 * demopasha dashboard — pinnacle-native glue server
 *
 * Runs directly on pinnaclepowerhouse. Serves the dashboard, proxies
 * FTEQW static files via /fte/, lists demos from firehose and curated
 * sources, and parses demos using the local mimer binary.
 *
 * Endpoints:
 *   GET  /                      — serves dashboard.html
 *   GET  /<static>              — static files from ~/demopasha-dashboard/static/
 *   GET  /fte/<path>            — proxied static files from ~/fteqw-web/
 *   GET  /demos?source=firehose|curated
 *   POST /parse  { source, path }
 */

const http = require('http');
const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

const PORT = 3456;
const HOST = '0.0.0.0';
const HOME = os.homedir();
const STATIC_DIR = path.join(HOME, 'demopasha-dashboard', 'static');
const FTEQW_DIR = path.join(HOME, 'fteqw-web');
const CURATED_DIR = path.join(FTEQW_DIR, 'demos', 'curated');
const MIMER_BIN = path.join(HOME, 'demoparser', 'target', 'release', 'mimer');
const DATA_DIR = path.join(STATIC_DIR, 'data');

// ---- Filename parsing ----

function parseFirehoseFilename(filepath) {
  const basename = path.basename(filepath);
  const info = { filename: basename, path: filepath, source: 'firehose' };

  const mapMatch = basename.match(/\[([^\]]+)\]/);
  info.map = mapMatch ? mapMatch[1] : 'unknown';

  const dateMatch = basename.match(/(\d{8})-(\d{4})/);
  if (dateMatch) {
    const d = dateMatch[1], t = dateMatch[2];
    info.date = `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)} ${t.slice(0,2)}:${t.slice(2,4)}`;
    info.sortKey = `${d}${t}`;
  } else {
    info.date = '';
    info.sortKey = '0';
  }

  const teamsMatch = basename.match(/^4on4_(.+?)_vs_(.+?)\[/);
  if (teamsMatch) {
    info.team1 = teamsMatch[1];
    info.team2 = teamsMatch[2];
  }

  return info;
}

function parseCuratedFilename(filepath) {
  const basename = path.basename(filepath);
  const info = { filename: basename, path: filepath, source: 'curated' };

  const p1 = basename.match(/^(\w+)_\w+_(.+?)_vs_(.+?)_(\d{8})_/);
  if (p1) {
    info.map = p1[1];
    info.team1 = p1[2];
    info.team2 = p1[3];
    const d = p1[4];
    info.date = `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}`;
    info.sortKey = d;
    return info;
  }

  const p2 = basename.match(/^(\d{8})-(\d{4})_.+?\[([^\]]+)\]\.mvd/);
  if (p2) {
    const d = p2[1], t = p2[2];
    info.date = `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)} ${t.slice(0,2)}:${t.slice(2,4)}`;
    info.sortKey = `${d}${t}`;
    const brackets = [...basename.matchAll(/\[([^\]]+)\]/g)];
    info.map = brackets.length > 0 ? brackets[brackets.length-1][1] : 'unknown';
    return info;
  }

  const mapGuess = basename.match(/^(\w+?)_/);
  info.map = mapGuess ? mapGuess[1] : 'unknown';
  info.date = '';
  info.sortKey = '0';
  return info;
}

// ---- Demo listing ----

function listFirehoseDemos() {
  try {
    const result = execSync(
      "ssh servexeri \"find /mnt/usb-ssd/mimer-demo-watcher/data/firehose -name '*.mvd' -o -name '*.mvd.gz'\"",
      { timeout: 30000, encoding: 'utf-8', maxBuffer: 10 * 1024 * 1024 }
    );
    const lines = result.trim().split('\n').filter(Boolean);
    const demos = lines.map(parseFirehoseFilename);
    demos.sort((a, b) => b.sortKey.localeCompare(a.sortKey));
    return demos;
  } catch (err) {
    console.error('Error listing firehose demos:', err.message);
    return [];
  }
}

function listCuratedDemos() {
  try {
    if (!fs.existsSync(CURATED_DIR)) return [];
    const files = fs.readdirSync(CURATED_DIR).filter(
      f => f.endsWith('.mvd') || f.endsWith('.mvd.gz')
    );
    const demos = files.map(f => parseCuratedFilename(path.join(CURATED_DIR, f)));
    demos.sort((a, b) => b.sortKey.localeCompare(a.sortKey));
    return demos;
  } catch (err) {
    console.error('Error listing curated demos:', err.message);
    return [];
  }
}

// ---- Transform mimer JSON to dashboard format ----

function transformMimerJson(raw, filename) {
  const data = JSON.parse(raw);
  const pt = data.position_timeline || {};
  const playersMeta = pt.players || [];
  const snapshotsRaw = pt.snapshots || [];

  const playerLookup = {};
  for (const p of playersMeta) {
    playerLookup[p.num] = { name: p.name, team: p.team };
  }

  const teams = {};
  for (const p of playersMeta) {
    if (!teams[p.team]) teams[p.team] = [];
    teams[p.team].push(p.name);
  }

  const snapshots = [];
  for (const snap of snapshotsRaw) {
    const positions = {};
    for (const entry of snap.p) {
      const num = entry[0];
      if (!playerLookup[num]) continue;
      const pinfo = playerLookup[num];
      positions[pinfo.name] = {
        x: entry[1], y: entry[2], z: entry[3],
        alive: !!entry[4],
        health: entry[5], armor: entry[6],
        flags: entry[7] || 0,
        pitch: (entry[8] || 0) / 10,
        yaw: (entry[9] || 0) / 10,
      };
    }
    snapshots.push({ t: Math.round(snap.t * 10) / 10, positions });
  }

  const kills = [];
  for (const k of (data.kill_events || [])) {
    kills.push({
      t: Math.round(k.time * 10) / 10,
      killer: k.killer,
      victim: k.victim,
      weapon: k.weapon,
      killer_pos: k.killer_pos || null,
      victim_pos: k.victim_pos || null,
    });
  }

  const duration = snapshots.length > 0 ? snapshots[snapshots.length-1].t : 0;
  const mapName = (data.map || '').toLowerCase()
    || filename.match(/\[([^\]]+)\]/)?.[1]
    || filename.match(/^(\w+?)_/)?.[1]
    || 'unknown';

  return {
    filename,
    map: mapName,
    duration,
    teams: Object.entries(teams).map(([name, players]) => ({ name, players })),
    players: playersMeta.map(p => ({ name: p.name, team: p.team, num: p.num })),
    snapshots,
    kills,
    itemEvents: pt.item_events || [],
    staticItems: pt.static_items || [],
  };
}

function loadMapMeta(mapName) {
  const metaPath = path.join(DATA_DIR, mapName, 'bsp_meta.json');
  try {
    const meta = JSON.parse(fs.readFileSync(metaPath, 'utf-8'));
    return {
      world_mins: meta.world_mins,
      world_maxs: meta.world_maxs,
      topdown_image: `${mapName}/${mapName}_topdown.png`,
    };
  } catch {
    return {
      world_mins: [-4096, -4096, -512],
      world_maxs: [4096, 4096, 512],
      topdown_image: null,
    };
  }
}

// ---- Demo parsing (local on pinnacle) ----

function parseDemoLocal(source, demoPath) {
  const basename = path.basename(demoPath);
  const tmpFile = path.join(os.tmpdir(), `glue_${Date.now()}_${basename}`);

  try {
    if (source === 'firehose') {
      execSync(`ssh servexeri "cat '${demoPath}'" > "${tmpFile}"`, { timeout: 60000 });
    } else {
      fs.copyFileSync(demoPath, tmpFile);
    }

    const parseResult = execSync(
      `"${MIMER_BIN}" "${tmpFile}" --dump-analysis`,
      { timeout: 120000, encoding: 'utf-8', maxBuffer: 200 * 1024 * 1024 }
    );

    const parsed = JSON.parse(parseResult);
    const demo = transformMimerJson(parseResult, basename);
    const map = loadMapMeta(demo.map);
    const quality_metrics = (parsed.position_timeline || {}).quality_metrics || null;
    const data_quality = parsed.data_quality || null;

    return { map, demo, quality_metrics, data_quality };
  } finally {
    try { fs.unlinkSync(tmpFile); } catch {}
  }
}

// ---- Static file serving ----

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js':   'application/javascript; charset=utf-8',
  '.css':  'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png':  'image/png',
  '.jpg':  'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.svg':  'image/svg+xml',
  '.wasm': 'application/wasm',
  '.bin':  'application/octet-stream',
  '.mvd':  'application/octet-stream',
  '.gz':   'application/gzip',
  '.fmf':  'application/octet-stream',
  '.mdl':  'application/octet-stream',
  '.bsp':  'application/octet-stream',
  '.pak':  'application/octet-stream',
  '.cfg':  'text/plain; charset=utf-8',
  '.txt':  'text/plain; charset=utf-8',
  '.ico':  'image/x-icon',
};

function serveStaticFile(res, filePath) {
  fs.stat(filePath, (err, stats) => {
    if (err || !stats.isFile()) {
      console.log(`[static] 404 ${filePath}${err ? ' — ' + err.message : ''}`);
      res.writeHead(404, { 'Content-Type': 'text/plain' });
      res.end('Not found');
      return;
    }
    const ext = path.extname(filePath).toLowerCase();
    const contentType = MIME[ext] || 'application/octet-stream';
    res.writeHead(200, {
      'Content-Type': contentType,
      'Content-Length': stats.size,
      'Cache-Control': 'no-cache',
      'Access-Control-Allow-Origin': '*',
    });
    fs.createReadStream(filePath).pipe(res);
  });
}

function resolveSafeFile(baseDir, requestPath) {
  // Decode + strip query, prevent path traversal
  const decoded = decodeURIComponent(requestPath.split('?')[0]);
  const normalized = path.normalize(decoded).replace(/^(\.\.[/\\])+/, '');
  const resolved = path.resolve(baseDir, '.' + (normalized.startsWith('/') ? normalized : '/' + normalized));
  if (!resolved.startsWith(path.resolve(baseDir))) return null;
  return resolved;
}

// ---- HTTP server ----

function sendJson(res, statusCode, data) {
  const body = JSON.stringify(data);
  res.writeHead(statusCode, {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  });
  res.end(body);
}

function sendError(res, statusCode, message) {
  sendJson(res, statusCode, { error: message });
}

const server = http.createServer((req, res) => {
  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    });
    res.end();
    return;
  }

  const url = new URL(req.url, `http://localhost:${PORT}`);
  const pathname = url.pathname;

  // GET /demos
  if (req.method === 'GET' && pathname === '/demos') {
    const source = url.searchParams.get('source');
    if (source === 'firehose') {
      sendJson(res, 200, listFirehoseDemos());
    } else if (source === 'curated') {
      sendJson(res, 200, listCuratedDemos());
    } else {
      sendError(res, 400, 'source must be "firehose" or "curated"');
    }
    return;
  }

  // POST /parse
  if (req.method === 'POST' && pathname === '/parse') {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      try {
        const { source, path: demoPath } = JSON.parse(body);
        if (!source || !demoPath) {
          sendError(res, 400, 'source and path are required');
          return;
        }
        console.log(`[parse] source=${source} path=${demoPath}`);
        const startTime = Date.now();
        const result = parseDemoLocal(source, demoPath);
        const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
        console.log(`[parse] done in ${elapsed}s — ${result.demo.map} / ${result.demo.snapshots.length} snaps / ${result.demo.kills.length} kills`);
        sendJson(res, 200, result);
      } catch (err) {
        console.error('[parse] error:', err.message);
        sendError(res, 500, err.message);
      }
    });
    return;
  }

  // GET /fte/* — proxied static files from ~/fteqw-web/
  if (req.method === 'GET' && pathname.startsWith('/fte/')) {
    const rel = pathname.slice(5) || 'index.html';
    const filePath = resolveSafeFile(FTEQW_DIR, rel);
    if (!filePath) {
      sendError(res, 403, 'forbidden');
      return;
    }
    serveStaticFile(res, filePath);
    return;
  }

  // GET / — serve dashboard.html
  if (req.method === 'GET' && (pathname === '/' || pathname === '/index.html')) {
    serveStaticFile(res, path.join(STATIC_DIR, 'dashboard.html'));
    return;
  }

  // GET /<static> — serve from STATIC_DIR
  if (req.method === 'GET') {
    const filePath = resolveSafeFile(STATIC_DIR, pathname);
    if (!filePath) {
      sendError(res, 403, 'forbidden');
      return;
    }
    serveStaticFile(res, filePath);
    return;
  }

  sendError(res, 404, 'Not found');
});

server.listen(PORT, HOST, () => {
  console.log(`demopasha dashboard at http://${HOST}:${PORT}`);
  console.log(`  Dashboard:  http://localhost:${PORT}/`);
  console.log(`  API:        GET /demos?source=firehose|curated`);
  console.log(`              POST /parse { source, path }`);
  console.log(`  Static:     ${STATIC_DIR}`);
  console.log(`  FTEQW:      ${FTEQW_DIR} (proxied via /fte/)`);
  console.log(`  Curated:    ${CURATED_DIR}`);
});
