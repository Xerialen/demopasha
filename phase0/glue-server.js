#!/usr/bin/env node
/**
 * Validator POC Glue Server
 *
 * Orchestrates demo listing, parsing on pinnaclepowerhouse, and staging
 * for FTEQW playback. Runs on localhost:3456.
 *
 * Endpoints:
 *   GET  /demos?source=firehose|local
 *   POST /parse  { source, path }
 */

const http = require('http');
const { execSync, spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

const PORT = 3456;
const LOCAL_DEMOS = '/home/quakeuser/projects/demoparser/data/testdemos';
const PINNACLE_MIMER = '~/demoparser/target/release/mimer';
const PINNACLE_FTEQW_DEMOS = '~/fteqw-web/demos';
const DATA_DIR = path.join(__dirname, 'data');

// Local mvd_analyzer build — produced by `make -C ../external/mvd_analyzer demopasha-extract`.
// When this binary exists and the request opts in (parser=mvd_analyzer or
// strict=true), the parse runs locally instead of via SSH+mimer.
const LOCAL_DEMOPASHA_EXTRACT = path.join(
  __dirname, '..', 'external', 'mvd_analyzer', 'bin', 'demopasha-extract'
);

// ---- Filename parsing ----

/**
 * Parse a firehose QTV filename like:
 *   4on4_blue_vs_red[dm2]20260214-0540.mvd
 *   4on4_blue_vs_pex[e1m2]20260321-0358.mvd
 */
function parseFirehoseFilename(filepath) {
  const basename = path.basename(filepath);
  const info = { filename: basename, path: filepath, source: 'firehose' };

  // Extract map from brackets
  const mapMatch = basename.match(/\[([^\]]+)\]/);
  info.map = mapMatch ? mapMatch[1] : 'unknown';

  // Extract date: YYYYMMDD-HHMM
  const dateMatch = basename.match(/(\d{8})-(\d{4})/);
  if (dateMatch) {
    const d = dateMatch[1];
    const t = dateMatch[2];
    info.date = `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)} ${t.slice(0, 2)}:${t.slice(2, 4)}`;
    info.sortKey = `${d}${t}`;
  } else {
    info.date = '';
    info.sortKey = '0';
  }

  // Extract teams from the part before brackets
  const teamsMatch = basename.match(/^4on4_(.+?)_vs_(.+?)\[/);
  if (teamsMatch) {
    info.team1 = teamsMatch[1];
    info.team2 = teamsMatch[2];
  }

  return info;
}

/**
 * Parse a local testdemo filename like:
 *   dm2_Milton_-s-_vs_Book_20251123_a5fe8c7c.mvd.gz
 *   20260109-2250_4on4_[hx]_vs_ving[schloss].mvd.gz
 */
function parseLocalFilename(filepath) {
  const basename = path.basename(filepath);
  const info = { filename: basename, path: filepath, source: 'local' };

  // Pattern 1: map_player_team_vs_team_YYYYMMDD_hash.mvd.gz
  const p1 = basename.match(/^(\w+)_\w+_(.+?)_vs_(.+?)_(\d{8})_/);
  if (p1) {
    info.map = p1[1];
    info.team1 = p1[2];
    info.team2 = p1[3];
    const d = p1[4];
    info.date = `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`;
    info.sortKey = d;
    return info;
  }

  // Pattern 2: YYYYMMDD-HHMM_4on4_[team]_vs_team[map].mvd.gz
  const p2 = basename.match(/^(\d{8})-(\d{4})_.+?\[([^\]]+)\]\.mvd/);
  if (p2) {
    const d = p2[1];
    const t = p2[2];
    info.date = `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)} ${t.slice(0, 2)}:${t.slice(2, 4)}`;
    info.sortKey = `${d}${t}`;
    // map is the last bracket
    const allBrackets = [...basename.matchAll(/\[([^\]]+)\]/g)];
    info.map = allBrackets.length > 0 ? allBrackets[allBrackets.length - 1][1] : 'unknown';
    return info;
  }

  // Fallback
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
      { timeout: 30000, encoding: 'utf-8' }
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

function listLocalDemos() {
  try {
    const files = fs.readdirSync(LOCAL_DEMOS).filter(
      f => f.endsWith('.mvd') || f.endsWith('.mvd.gz')
    );
    const demos = files.map(f => parseLocalFilename(path.join(LOCAL_DEMOS, f)));
    demos.sort((a, b) => b.sortKey.localeCompare(a.sortKey));
    return demos;
  } catch (err) {
    console.error('Error listing local demos:', err.message);
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

  const duration = snapshots.length > 0 ? snapshots[snapshots.length - 1].t : 0;

  // Extract map name from data or filename
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
    // Reasonable defaults for unknown maps
    return {
      world_mins: [-4096, -4096, -512],
      world_maxs: [4096, 4096, 512],
      topdown_image: null,
    };
  }
}

// ---- Parse endpoint ----

function spawnOrThrow(bin, args, label, opts = {}) {
  const proc = spawnSync(bin, args, {
    timeout: opts.timeout ?? 60000,
    encoding: 'utf-8',
    maxBuffer: opts.maxBuffer ?? 100 * 1024 * 1024,
    stdio: opts.stdio,
  });
  if (proc.error) {
    throw new Error(`${label}: ${proc.error.message}`);
  }
  if (proc.status !== 0) {
    const stderr = (proc.stderr || '').toString().trim();
    throw new Error(`${label}: exit ${proc.status}${stderr ? ` — ${stderr}` : ''}`);
  }
  return proc;
}

function parseDemoOnPinnacle(source, demoPath, opts = {}) {
  const parserChoice = opts.parser === 'mvd_analyzer' ? 'mvd_analyzer' : 'mimer';
  const strict = !!opts.strict;
  if (strict && parserChoice !== 'mvd_analyzer') {
    // strict only has meaning when the local mvd_analyzer parser is in use;
    // refusing the request is safer than echoing strict: true while running
    // a parser that cannot honour it.
    const err = new Error('strict=true requires parser="mvd_analyzer"; mimer cannot enforce hard-fail semantics');
    err.statusCode = 400;
    throw err;
  }

  const basename = path.basename(demoPath);
  const tmpFile = path.join(os.tmpdir(), `glue_${Date.now()}_${basename}`);
  const remoteDest = `${PINNACLE_FTEQW_DEMOS}/${basename}`;

  try {
    // Step 1: Fetch the demo into a local temp file. Both paths use spawnSync
    // with argv arrays so filename metacharacters (quotes, $, etc.) cannot
    // alter the executed command.
    if (source === 'firehose') {
      const fd = fs.openSync(tmpFile, 'w');
      try {
        spawnOrThrow('ssh', ['servexeri', '--', 'cat', demoPath], 'ssh servexeri cat', {
          stdio: ['ignore', fd, 'pipe'],
          timeout: 60000,
        });
      } finally {
        fs.closeSync(fd);
      }
    } else {
      fs.copyFileSync(demoPath, tmpFile);
    }

    // Step 2: Stage the demo on pinnacle so the dashboard's Replay tab (FTEQW)
    // can find it. Required for both parser paths — the mvd_analyzer path
    // runs locally but playback is still pinnacle-side.
    spawnOrThrow('scp', [tmpFile, `pinnaclepowerhouse:${remoteDest}`], 'scp to pinnacle', { timeout: 60000 });

    let parseResult;
    if (parserChoice === 'mvd_analyzer') {
      if (!fs.existsSync(LOCAL_DEMOPASHA_EXTRACT)) {
        throw new Error(`mvd_analyzer requested but ${LOCAL_DEMOPASHA_EXTRACT} not built — run: (cd external/mvd_analyzer && make demopasha-extract)`);
      }
      const args = strict ? ['-strict', tmpFile] : [tmpFile];
      const proc = spawnOrThrow(LOCAL_DEMOPASHA_EXTRACT, args, 'demopasha-extract', { timeout: 120000 });
      parseResult = proc.stdout;
    } else {
      // SSH/exec form: argv-array invocation of `ssh pinnaclepowerhouse <cmd>`.
      // The remote shell still parses its argv, so we shell-escape the
      // remote args as a defence in depth — basename is already safe via
      // path.basename but we don't trust it implicitly.
      const remoteCmd = `${PINNACLE_MIMER} ${shellEscape(remoteDest)} --dump-analysis`;
      const proc = spawnOrThrow('ssh', ['pinnaclepowerhouse', '--', remoteCmd], 'ssh pinnacle mimer', { timeout: 120000 });
      parseResult = proc.stdout;
    }

    const parsed = JSON.parse(parseResult);
    const demo = transformMimerJson(parseResult, basename);
    demo.parser = parserChoice;
    const map = loadMapMeta(demo.map);
    const quality_metrics = (parsed.position_timeline || {}).quality_metrics || null;
    const data_quality = parsed.data_quality || null;

    return { map, demo, quality_metrics, data_quality, parser: parserChoice, strict };
  } finally {
    try { fs.unlinkSync(tmpFile); } catch {}
  }
}

// shellEscape wraps an argument in single quotes for /bin/sh, escaping
// any embedded single quotes. Used on the remote side of SSH where the
// argv vector becomes a shell command line again.
function shellEscape(s) {
  return `'${String(s).replace(/'/g, "'\\''")}'`;
}

// ---- HTTP Server ----

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
  // CORS preflight
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

  // GET / — serve the dashboard so it lives on the same origin as the
  // /demos and /parse endpoints (avoids file:// fetch failures).
  if (req.method === 'GET' && (url.pathname === '/' || url.pathname === '/dashboard.html')) {
    try {
      const html = fs.readFileSync(path.join(__dirname, 'dashboard.html'), 'utf-8');
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(html);
    } catch (err) {
      sendError(res, 500, `dashboard.html not readable: ${err.message}`);
    }
    return;
  }

  // GET /data/<...> — passthrough for static map images (topdown PNGs etc.)
  if (req.method === 'GET' && url.pathname.startsWith('/data/')) {
    const safePath = path.normalize(url.pathname.slice(1));
    if (safePath.startsWith('..') || path.isAbsolute(safePath)) {
      sendError(res, 400, 'invalid path');
      return;
    }
    const fp = path.join(__dirname, safePath);
    try {
      const buf = fs.readFileSync(fp);
      const ext = path.extname(fp).toLowerCase();
      const ct = ext === '.png' ? 'image/png'
        : ext === '.json' ? 'application/json'
        : 'application/octet-stream';
      res.writeHead(200, { 'Content-Type': ct });
      res.end(buf);
    } catch (err) {
      sendError(res, 404, `not found: ${safePath}`);
    }
    return;
  }

  // GET /demos
  if (req.method === 'GET' && url.pathname === '/demos') {
    const source = url.searchParams.get('source');
    if (source === 'firehose') {
      const demos = listFirehoseDemos();
      sendJson(res, 200, demos);
    } else if (source === 'local') {
      const demos = listLocalDemos();
      sendJson(res, 200, demos);
    } else {
      sendError(res, 400, 'source must be "firehose" or "local"');
    }
    return;
  }

  // POST /parse
  if (req.method === 'POST' && url.pathname === '/parse') {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      try {
        const { source, path: demoPath, parser, strict } = JSON.parse(body);
        if (!source || !demoPath) {
          sendError(res, 400, 'source and path are required');
          return;
        }
        const opts = { parser: parser === 'mvd_analyzer' ? 'mvd_analyzer' : 'mimer', strict: !!strict };
        console.log(`[parse] source=${source} parser=${opts.parser} strict=${opts.strict} path=${demoPath}`);
        const startTime = Date.now();
        const result = parseDemoOnPinnacle(source, demoPath, opts);
        const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
        console.log(`[parse] done in ${elapsed}s via ${opts.parser} — ${result.demo.map} / ${result.demo.snapshots.length} snapshots / ${result.demo.kills.length} kills`);
        sendJson(res, 200, result);
      } catch (err) {
        console.error('[parse] error:', err.message);
        sendError(res, err.statusCode || 500, err.message);
      }
    });
    return;
  }

  sendError(res, 404, 'Not found');
});

// Bind to 0.0.0.0 so LAN-side tooling (Playwright on pinnacle, dashboard
// served from another host) can reach the glue. CORS is already wide open.
server.listen(PORT, '0.0.0.0', () => {
  console.log(`Glue server running at http://localhost:${PORT}`);
  console.log(`  GET  /demos?source=firehose|local`);
  console.log(`  POST /parse { source, path, parser?: "mimer"|"mvd_analyzer", strict?: bool }`);
  if (fs.existsSync(LOCAL_DEMOPASHA_EXTRACT)) {
    console.log(`  ✓ mvd_analyzer extract binary found at ${LOCAL_DEMOPASHA_EXTRACT}`);
  } else {
    console.log(`  ! mvd_analyzer extract not built — defaults to mimer over SSH`);
  }
});
