'use strict';

const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const readline = require('node:readline');

class BridgeError extends Error {}

const DESKTOP_INSTRUCTIONS = '在 Claude 桌面版請用 upload_local_file 上傳本機檔案，不要使用 curl';
const LOCAL_TOOL = {
  name: 'upload_local_file',
  description: '在 Claude 桌面版上傳本機圖片或影片到草稿，需行銷或管理員權限。參數 post_id 為草稿 ID、path 為本機檔案路徑（可用 ~）；支援 jpg、jpeg、png、mp4、mov，最多 1 GB。回傳伺服器上傳結果；成功後用 get_publish_post 確認媒體。錯誤時下一步：檢查路徑、格式、大小與草稿權限，再重試；上傳不代表同意發佈。',
  inputSchema: { type: 'object', properties: {
    post_id: { type: 'integer', minimum: 1, description: '草稿 ID' },
    path: { type: 'string', minLength: 1, description: '本機圖片或影片路徑' },
  }, required: ['post_id', 'path'], additionalProperties: false },
  annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
};

function workbenchUrl(value) {
  try {
    const url = new URL(value);
    if ((url.protocol !== 'https:' && !(url.protocol === 'http:' &&
        ['127.0.0.1', 'localhost'].includes(url.hostname))) || url.username || url.password ||
        url.search || url.hash || !['', '/'].includes(url.pathname)) throw new Error();
    return url.origin;
  } catch {
    throw new BridgeError('工作檯網址無效；下一步：擴充設定請填內部 https 網址，或本機 http://127.0.0.1:8000（也可用 localhost）。');
  }
}

function redact(value, token) {
  if (typeof value === 'string') return token ? value.split(token).join('[已遮蔽]') : value;
  if (Array.isArray(value)) return value.map(item => redact(item, token));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value)
    .map(([key, item]) => [redact(key, token), redact(item, token)]));
  return value;
}

// Read until the matching response, even when the HTTP SSE connection remains open.
async function sseResponse(response, id, signal) {
  const reader = response.body.getReader(), decoder = new TextDecoder();
  const cancel = () => { reader.cancel().catch(() => {}); };
  signal.addEventListener('abort', cancel, { once: true });
  let pending = '';
  try {
    while (true) {
      const { value, done } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      pending = pending.replace(/\r\n/g, '\n');
      let end;
      while ((end = pending.indexOf('\n\n')) >= 0 || (done && pending.length)) {
        if (end < 0) end = pending.length;
        const event = pending.slice(0, end);
        pending = pending.slice(end + 2);
        const data = event.split('\n').filter(line => line.startsWith('data:'))
          .map(line => line.slice(5).replace(/^ /, '')).join('\n');
        if (!data) continue;
        const message = JSON.parse(data);
        if (message.id === id) return message;
      }
      if (done) throw new BridgeError('工作檯回應不完整；下一步：重試或請管理員檢查 MCP 服務。');
    }
  } finally {
    signal.removeEventListener('abort', cancel);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

async function jsonResponse(response, signal) {
  const reader = response.body.getReader(), decoder = new TextDecoder();
  const cancel = () => { reader.cancel().catch(() => {}); };
  signal.addEventListener('abort', cancel, { once: true });
  let body = '';
  try {
    while (true) {
      const { value, done } = await reader.read();
      body += decoder.decode(value, { stream: !done });
      if (done) return JSON.parse(body);
    }
  } finally {
    signal.removeEventListener('abort', cancel);
    reader.releaseLock();
  }
}

// JSON-RPC 應在幾秒內回應；上傳 1 GB 影片在一般上行頻寬下要好幾分鐘，兩者不能共用期限，
// 否則超過 30 秒的檔案永遠傳不完，一次性上傳碼也白白用掉。
const UPLOAD_TIMEOUT_MS = 30 * 60 * 1000;

function durationLabel(ms) {
  return ms >= 60000 && ms % 60000 === 0 ? `${ms / 60000} 分鐘` : `${Math.round(ms / 1000)} 秒`;
}

function createBridge({ url, token, version, timeoutMs = 30000, uploadTimeoutMs = UPLOAD_TIMEOUT_MS }) {
  let protocolVersion;
  let internalId = 0;

  async function request(target, options, parse, limitMs = timeoutMs) {
    const controller = new AbortController();
    const timeoutMessage = `工作檯連線逾時（${durationLabel(limitMs)}）；下一步：確認工作檯與 Tailscale 連線後重試。`;
    let timer;
    // Race the entire response body as well: abort alone can stall after headers.
    const deadline = new Promise((resolve, reject) => {
      timer = setTimeout(() => {
        reject(new BridgeError(timeoutMessage));
        controller.abort();
      }, limitMs);
    });
    try {
      return await Promise.race([deadline, (async () => {
        const response = await fetch(target, { ...options, signal: controller.signal, redirect: 'error' });
        if (!response.ok) {
          await response.body?.cancel();
          if (response.status === 401) throw new BridgeError('連線權杖無效或已撤銷，請到工作檯重新建立並更新擴充設定');
          throw new BridgeError(`工作檯請求失敗（${response.status}）；下一步：檢查權限與草稿狀態後重試。`);
        }
        return await parse(response, controller.signal);
      })()]);
    } catch (error) {
      if (controller.signal.aborted) throw new BridgeError(timeoutMessage);
      if (error instanceof TypeError) throw new BridgeError('無法連上工作檯；下一步：確認網址、工作檯服務與 Tailscale 連線後重試。');
      throw error;
    } finally { clearTimeout(timer); }
  }

  async function forward(message) {
    const origin = workbenchUrl(url);
    if (!token) throw new BridgeError('尚未設定連線權杖；下一步：在工作檯建立權杖並更新擴充設定。');
    const protocol = message.method === 'initialize' ? message.params?.protocolVersion : protocolVersion;
    const headers = { Authorization: `Bearer ${token}`, Accept: 'application/json, text/event-stream',
      'Content-Type': 'application/json', 'X-MWB-Plugin-Version': version };
    if (protocol) headers['MCP-Protocol-Version'] = protocol;
    return request(origin + '/mcp', { method: 'POST', headers, body: JSON.stringify(message) }, async (response, signal) => {
      if (response.status === 202 && !Object.hasOwn(message, 'id')) return null;
      const result = response.headers.get('content-type')?.includes('text/event-stream')
        ? await sseResponse(response, message.id, signal) : await jsonResponse(response, signal);
      if (message.method === 'initialize' && result.result?.protocolVersion) protocolVersion = result.result.protocolVersion;
      return result;
    });
  }

  async function upload(message) {
    const args = message.params?.arguments;
    if (!args || !Number.isInteger(args.post_id) || args.post_id < 1 || typeof args.path !== 'string' ||
        !args.path || Object.keys(args).some(key => !['post_id', 'path'].includes(key)))
      throw new BridgeError('上傳參數無效；下一步：提供草稿 post_id 與本機檔案 path。');
    const filename = args.path.replace(/^~(?=$|[\\/])/, os.homedir());
    if (!/\.(jpe?g|png|mp4|mov)$/i.test(filename))
      throw new BridgeError('不支援此副檔名；下一步：選擇 jpg、jpeg、png、mp4 或 mov 檔案。');
    // Open the file once so validation and streaming use the same file descriptor.
    let handle;
    let initial;
    try { initial = await fsp.stat(filename); }
    catch { throw new BridgeError('檔案不存在或無法讀取；下一步：確認本機檔案路徑與讀取權限。'); }
    if (!initial.isFile()) throw new BridgeError('路徑不是一般檔案；下一步：選擇圖片或影片檔案，不能上傳目錄。');
    try { handle = await fsp.open(filename, 'r'); }
    catch { throw new BridgeError('檔案不存在或無法讀取；下一步：確認本機檔案路徑與讀取權限。'); }
    try {
      const stat = await handle.stat();
      if (!stat.isFile()) throw new BridgeError('路徑不是一般檔案；下一步：選擇圖片或影片檔案，不能上傳目錄。');
      if (stat.size > 1024 ** 3) throw new BridgeError('檔案超過 1 GB；下一步：縮小檔案後再上傳。');
      const link = await forward({ jsonrpc: '2.0', id: `desktop-upload-${++internalId}`, method: 'tools/call',
        params: { name: 'create_upload_link', arguments: { post_id: args.post_id, filename: path.basename(filename) } } });
      if (link.error) return { ...link, id: message.id };
      if (link.result?.isError) return { jsonrpc: '2.0', id: message.id, result: link.result };
      let content = link.result?.structuredContent;
      if (!content) {
        const text = link.result?.content?.find(item => item.type === 'text')?.text;
        try { content = JSON.parse(text); } catch { /* Invalid link handled below. */ }
      }
      let target;
      try { target = new URL(content?.upload_url); }
      catch { throw new BridgeError('工作檯未提供上傳網址；下一步：重試或請管理員檢查草稿。'); }
      if (target.origin !== workbenchUrl(url) || !/^\/api\/agent\/uploads\/[A-Za-z0-9_-]+$/.test(target.pathname) ||
          target.username || target.password || target.search || target.hash)
        throw new BridgeError('工作檯上傳網址無效；下一步：請管理員檢查內部上傳設定。');
      const stream = handle.createReadStream({ autoClose: false });
      let result;
      try {
        result = await request(target, { method: 'PUT', headers: { 'Content-Type': 'application/octet-stream',
          'Content-Length': String(stat.size) }, body: stream, duplex: 'half' }, jsonResponse, uploadTimeoutMs);
      } finally { stream.destroy(); }
      return { jsonrpc: '2.0', id: message.id, result: { content: [
        { type: 'text', text: JSON.stringify(result) },
        { type: 'text', text: '上傳成功；下一步：用 get_publish_post 確認媒體已加入草稿。' },
      ], structuredContent: result, isError: false } };
    } finally { await handle.close(); }
  }

  return async message => {
    try {
      workbenchUrl(url);
      const response = message.method === 'tools/call' && message.params?.name === 'upload_local_file'
        ? await upload(message) : await forward(message);
      if (!Object.hasOwn(message, 'id')) return null;
      if (message.method === 'tools/list' && response?.result?.tools) {
        response.result.tools = response.result.tools.filter(tool => !['create_upload_link', 'upload_local_file'].includes(tool.name));
        response.result.tools.push(LOCAL_TOOL);
      }
      if (message.method === 'initialize' && response?.result) response.result.instructions =
        [response.result.instructions, DESKTOP_INSTRUCTIONS].filter(Boolean).join('\n');
      return redact(response, token);
    } catch (error) {
      // Never print upstream error bodies, URLs, paths or credentials.
      process.stderr.write('工作檯連線或上傳失敗\n');
      if (!Object.hasOwn(message, 'id')) return null;
      const safe = error instanceof BridgeError ? error.message : '工作檯回應或檔案讀取失敗；下一步：重試或請管理員檢查服務。';
      return redact({ jsonrpc: '2.0', id: message.id, error: { code: -32000, message: safe } }, token);
    }
  };
}

async function main() {
  const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, '../manifest.json'), 'utf8'));
  const version = manifest.version === '${plugin_version}'
    ? JSON.parse(fs.readFileSync(path.join(__dirname, '../../mwb/.claude-plugin/plugin.json'), 'utf8')).version : manifest.version;
  const bridge = createBridge({ url: process.env.MWB_WORKBENCH_URL, token: process.env.MWB_TOKEN, version });
  for await (const line of readline.createInterface({ input: process.stdin, crlfDelay: Infinity })) {
    if (!line.trim()) continue;
    let message;
    try {
      message = JSON.parse(line);
      if (!message || Array.isArray(message) || message.jsonrpc !== '2.0' || typeof message.method !== 'string') throw new Error();
    } catch {
      process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: null, error: { code: -32700,
        message: '訊息格式無效；下一步：重新開始 Claude 對話。' } }) + '\n');
      continue;
    }
    const result = await bridge(message);
    if (result) process.stdout.write(JSON.stringify(result) + '\n');
  }
}

module.exports = { createBridge, workbenchUrl, LOCAL_TOOL, main };
