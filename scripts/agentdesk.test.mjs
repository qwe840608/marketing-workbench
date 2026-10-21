import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { createBridge, workbenchUrl } = require('../plugin/desktop/server/bridge.js');
const root = fileURLToPath(new URL('../', import.meta.url));
const entry = path.join(root, 'plugin/desktop/server/index.js');
const version = require('../plugin/mwb/.claude-plugin/plugin.json').version;
const token = 'mwb_synthetic_desktop_secret';
const rpc = (id, method, params) => ({ jsonrpc: '2.0', id, method, ...(params ? { params } : {}) });
const upload = (id, filename) => rpc(id, 'tools/call', { name: 'upload_local_file', arguments: { post_id: 7, path: filename } });

async function endpoint(t, handler) {
  const received = [];
  const server = http.createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const bytes = Buffer.concat(chunks);
    const body = req.url === '/mcp' ? JSON.parse(bytes) : bytes;
    received.push({ method: req.method, url: req.url, headers: req.headers, body });
    await handler(req, res, body, received);
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(() => { server.closeAllConnections(); server.close(); });
  return { url: `http://127.0.0.1:${server.address().port}`, received };
}

function json(res, message, result) {
  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ jsonrpc: '2.0', id: message.id, result }));
}

async function desktop(t, url, messages, { timeout = 10000, extraEnv = {} } = {}) {
  const child = spawn(process.execPath, [entry], { cwd: root,
    env: { ...process.env, MWB_WORKBENCH_URL: url, MWB_TOKEN: token, ...extraEnv },
    stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true });
  t.after(() => { if (child.exitCode === null) child.kill(); });
  let stdout = '', stderr = '';
  child.stdout.setEncoding('utf8').on('data', value => { stdout += value; });
  child.stderr.setEncoding('utf8').on('data', value => { stderr += value; });
  const timer = setTimeout(() => child.kill(), timeout);
  child.stdin.end(messages.map(message => typeof message === 'string' ? message : JSON.stringify(message)).join('\n') + '\n');
  const [code] = await once(child, 'close');
  clearTimeout(timer);
  assert.equal(code, 0, JSON.stringify({ stdout, stderr }));
  assert.ok(!stdout.includes(token), 'stdout must redact the synthetic token');
  assert.ok(!stderr.includes(token), 'stderr must redact the synthetic token');
  return { rows: stdout.trim() ? stdout.trim().split('\n').map(line => JSON.parse(line)) : [], stdout, stderr };
}

test('stdio forwards original messages, headers and negotiated protocol; hides upload link and decorates initialize', async t => {
  const remoteTools = [{ name: 'create_upload_link' }, { name: 'get_publish_post', description: '確認草稿' }];
  const fake = await endpoint(t, (req, res, message) => {
    if (!Object.hasOwn(message, 'id')) { res.writeHead(202); res.end(); return; }
    if (message.method === 'initialize') json(res, message, { protocolVersion: '2025-11-25', instructions: '原有指示', capabilities: {} });
    else if (message.method === 'tools/list') json(res, message, { tools: remoteTools });
    else json(res, message, { reflected: token, [token]: token, nested: [token], content: [] });
  });
  const messages = [rpc(1, 'initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'synthetic', version: '1' } }),
    { jsonrpc: '2.0', method: 'notifications/initialized' }, rpc(0, 'tools/list'),
    rpc('compat', 'tools/call', { name: 'create_upload_link', arguments: { post_id: 7, filename: 'image.jpg' } })];
  const result = await desktop(t, fake.url, messages);
  assert.equal(result.rows.length, 3);
  assert.equal(result.stderr, '');
  assert.match(result.rows[0].result.instructions, /^原有指示\n在 Claude 桌面版請用 upload_local_file 上傳本機檔案，不要使用 curl$/);
  assert.deepEqual(result.rows[1].result.tools.map(tool => tool.name), ['get_publish_post', 'upload_local_file']);
  const local = result.rows[1].result.tools[1];
  assert.deepEqual(local.inputSchema.required, ['post_id', 'path']);
  assert.match(local.description, /回傳.*下一步/);
  assert.equal(local.annotations.readOnlyHint, false);
  assert.equal(result.rows[2].result.reflected, '[已遮蔽]');
  assert.deepEqual(fake.received.map(row => row.body), messages);
  for (const [index, row] of fake.received.entries()) {
    assert.equal(row.method, 'POST');
    assert.equal(row.headers.authorization, `Bearer ${token}`);
    assert.equal(row.headers['x-mwb-plugin-version'], version);
    assert.equal(row.headers.accept, 'application/json, text/event-stream');
    assert.equal(row.headers['content-type'], 'application/json');
    assert.equal(row.headers['mcp-protocol-version'], index ? '2025-11-25' : '2025-06-18');
  }
});

test('notification 202 emits no stdout; malformed input does not crash the process', async t => {
  const fake = await endpoint(t, (req, res, message) => {
    if (!Object.hasOwn(message, 'id')) { res.writeHead(202); res.end(); }
    else json(res, message, {});
  });
  assert.equal((await desktop(t, fake.url, [{ jsonrpc: '2.0', method: 'notifications/initialized' }])).stdout, '');
  const result = await desktop(t, fake.url, ['{invalid', rpc(9, 'ping')]);
  assert.equal(result.rows[0].error.code, -32700);
  assert.equal(result.rows[1].id, 9);
});

test('SSE parses split UTF-8, multiline data, CRLF and skips notifications without waiting for EOF', async t => {
  const fake = await endpoint(t, async (req, res, message) => {
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    const bytes = Buffer.from(': keepalive\r\n\r\ndata: {"jsonrpc":"2.0","method":"notifications/progress"}\r\n\r\n' +
      `event: message\r\ndata: {"jsonrpc":"2.0","id":${message.id},\r\ndata: "result":{"text":"中文回應"}}\r\n\r\n`);
    for (let index = 0; index < bytes.length; index += 2) res.write(bytes.subarray(index, index + 2));
    // Intentionally leave this stream open to verify completion at the matching id.
  });
  const result = await desktop(t, fake.url, [rpc(3, 'ping')]);
  assert.deepEqual(result.rows[0], { jsonrpc: '2.0', id: 3, result: { text: '中文回應' } });
});

async function files(t) {
  const parent = path.join(root, '.runtime/agentdesk-node');
  await fs.mkdir(parent, { recursive: true });
  const folder = await fs.mkdtemp(path.join(parent, 'files-'));
  t.after(async () => {
    assert.equal(path.dirname(path.resolve(folder)), path.resolve(parent));
    await fs.rm(folder, { recursive: true, force: true });
  });
  return folder;
}

test('local upload creates capability then streams PUT, returns server result and confirms next step; expands ~', async t => {
  const folder = await files(t);
  const payload = Buffer.from('synthetic media bytes');
  const filename = path.join(folder, '媒體.JPG');
  await fs.writeFile(filename, payload);
  const fake = await endpoint(t, (req, res, message) => {
    if (req.url === '/mcp') json(res, message, { structuredContent: { upload_url: fake.url + '/api/agent/uploads/synthetic_capability' } });
    else { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ id: 42, filename: '媒體.JPG' })); }
  });
  const result = await desktop(t, fake.url, [upload(4, filename), upload(5, '~/媒體.JPG')],
    { extraEnv: { USERPROFILE: folder, HOME: folder } });
  assert.equal(result.rows[0].result.isError, false);
  assert.deepEqual(result.rows[0].result.structuredContent, { id: 42, filename: '媒體.JPG' });
  assert.match(result.rows[0].result.content[1].text, /get_publish_post/);
  assert.equal(result.rows[1].result.isError, false);
  assert.equal(fake.received.length, 4);
  for (const [link, put] of [[fake.received[0], fake.received[1]], [fake.received[2], fake.received[3]]]) {
    assert.equal(link.body.params.name, 'create_upload_link');
    assert.deepEqual(link.body.params.arguments, { post_id: 7, filename: '媒體.JPG' });
    assert.equal(put.method, 'PUT');
    assert.deepEqual(put.body, payload);
    assert.equal(put.headers.authorization, undefined);
    assert.equal(put.headers.cookie, undefined);
    assert.equal(put.headers['content-length'], String(payload.length));
  }
});

test('invalid extension, directory, missing file, >1 GB, symlink to nonfile, invalid params reject before network', async t => {
  const folder = await files(t), directory = path.join(folder, 'directory.png');
  await fs.mkdir(directory);
  const large = path.join(folder, 'large.mp4');
  const handle = await fs.open(large, 'w');
  await handle.truncate(1024 ** 3 + 1);
  await handle.close();
  const fake = await endpoint(t, (req, res, message) => json(res, message, {}));
  const cases = [[path.join(folder, 'bad.txt'), /副檔名/], [directory, /一般檔案/],
    [path.join(folder, 'missing.jpg'), /不存在/], [large, /超過 1 GB/]];
  const linked = path.join(folder, 'link.png');
  await fs.symlink(directory, linked, process.platform === 'win32' ? 'junction' : 'dir');
  cases.push([linked, /一般檔案/]);
  const result = await desktop(t, fake.url, [...cases.map(([name], index) => upload(index, name)),
    rpc(7, 'tools/call', { name: 'upload_local_file', arguments: { post_id: -1, path: 'a.png' } })]);
  for (const [index, [, error]] of cases.entries()) assert.match(result.rows[index].error.message, error);
  assert.match(result.rows.at(-1).error.message, /參數無效/);
  assert.equal(fake.received.length, 0);
});

test('401 and refusal are Chinese RPC errors and the process can continue', async t => {
  let count = 0;
  const fake = await endpoint(t, (req, res, message) => {
    if (++count === 1) { res.writeHead(401); res.end(token); }
    else json(res, message, {});
  });
  const result = await desktop(t, fake.url, [rpc(1, 'ping'), rpc(2, 'ping')]);
  assert.match(result.rows[0].error.message, /連線權杖無效或已撤銷，請到工作檯重新建立並更新擴充設定/);
  assert.deepEqual(result.rows[1], { jsonrpc: '2.0', id: 2, result: {} });
  const closed = http.createServer();
  closed.listen(0, '127.0.0.1');
  await once(closed, 'listening');
  const url = `http://127.0.0.1:${closed.address().port}`;
  await new Promise(resolve => closed.close(resolve));
  assert.match((await desktop(t, url, [rpc(1, 'ping')])).rows[0].error.message, /無法連上工作檯.*下一步/);
});

test('default deadline is 30 seconds, handles hanging response body and does not crash', { timeout: 40000 }, async t => {
  const fake = await endpoint(t, (req, res, message) => {
    if (message.id === 1) { res.writeHead(200, { 'Content-Type': 'application/json' }); res.write('{'); }
    else json(res, message, {});
  });
  const start = Date.now();
  const result = await desktop(t, fake.url, [rpc(1, 'ping'), rpc(2, 'ping')], { timeout: 38000 });
  assert.ok(Date.now() - start >= 29500 && Date.now() - start < 36000);
  assert.match(result.rows[0].error.message, /逾時（30 秒）.*下一步/);
  assert.deepEqual(result.rows[1], { jsonrpc: '2.0', id: 2, result: {} });
});

test('upload deadline, upstream tool errors and foreign/redirect capability never upload', async t => {
  const folder = await files(t), filename = path.join(folder, 'image.png');
  await fs.writeFile(filename, 'synthetic');
  let mode = 'error';
  const fake = await endpoint(t, async (req, res, message) => {
    if (req.url !== '/mcp') {
      if (mode === 'redirect') { res.writeHead(302, { Location: 'http://127.0.0.1:1/forbidden' }); res.end(); }
      else if (mode === 'slow') {
        // 慢於 JSON-RPC 期限但在上傳期限內：大檔上傳不能套用 30 秒的呼叫期限。
        await new Promise(resolve => setTimeout(resolve, 400));
        res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ media_id: 9 }));
      } else { res.writeHead(200); res.write('{'); }
    } else if (mode === 'error') json(res, message, { isError: true, content: [{ type: 'text', text: '草稿不存在；下一步：檢查 ID' }] });
    else json(res, message, { structuredContent: { upload_url: mode === 'foreign'
      ? 'https://other.example.test/api/agent/uploads/capability' : fake.url + '/api/agent/uploads/capability' } });
  });
  const bridge = createBridge({ url: fake.url, token, version, timeoutMs: 100, uploadTimeoutMs: 300 });
  assert.equal((await bridge(upload(1, filename))).result.isError, true);
  mode = 'foreign';
  assert.match((await bridge(upload(2, filename))).error.message, /上傳網址無效/);
  assert.ok(fake.received.every(row => row.url === '/mcp'));
  mode = 'timeout';
  const started = Date.now();
  assert.match((await bridge(upload(3, filename))).error.message, /逾時/);
  assert.ok(Date.now() - started >= 250, 'upload must use its own deadline, not the 100 ms JSON-RPC one');
  mode = 'redirect';
  assert.match((await bridge(upload(4, filename))).error.message, /無法連上/);
  mode = 'slow';
  const patient = createBridge({ url: fake.url, token, version, timeoutMs: 100, uploadTimeoutMs: 10000 });
  const slow = await patient(upload(5, filename));
  assert.equal(slow.result?.isError, false, JSON.stringify(slow));
  assert.deepEqual(slow.result.structuredContent, { media_id: 9 });
});

test('only https or literal loopback http origin is accepted, invalid settings redact token', async t => {
  for (const url of ['https://office.example.test', 'http://127.0.0.1:8000', 'http://localhost:8000/']) assert.ok(workbenchUrl(url));
  for (const url of ['http://office.example.test', 'http://192.168.1.1', 'ftp://localhost',
    'http://[::1]', `https://${token}@office.example.test`, `http://${token}.example.test`,
    'https://office.example.test/mcp', 'https://office.example.test?token=value']) {
    assert.throws(() => workbenchUrl(url), /網址無效.*https/);
    assert.match((await desktop(t, url, [rpc(1, 'ping')])).rows[0].error.message, /網址無效.*下一步/);
  }
});
