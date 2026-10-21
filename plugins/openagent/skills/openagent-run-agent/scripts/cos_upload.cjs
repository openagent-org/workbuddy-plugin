#!/usr/bin/env node
'use strict';

// 使用随插件分发的腾讯 COS Node SDK 上传一个已准备的附件。
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const zlib = require('node:zlib');

class CosSdkUnavailable extends Error {}
class SourceChanged extends Error {}
class CheckpointCleanupError extends Error {}
const resourcePattern = /^cosfile_[a-f0-9]{32}$/;
const hashPattern = /^[a-f0-9]{64}$/;
const sha256 = data => crypto.createHash('sha256').update(data).digest('hex');
let sdk;
let sdkPath;

function lstat(file) {
  try { return fs.lstatSync(file); }
  catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}

function privateDirectory(directory) {
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  const info = fs.lstatSync(directory);
  if (!info.isDirectory() || info.isSymbolicLink()) throw new Error('invalid SDK cache directory');
}

function loadSdk() {
  try {
    if (Number(process.versions.node.split('.')[0]) < 20) throw new Error('unsupported Node version');
    const lock = JSON.parse(fs.readFileSync(path.join(__dirname, 'cos_sdk.lock.json'), 'utf8'));
    const { bundle } = lock;
    if (lock.format !== 'openagent-cos-node-sdk-v1' || lock.minimum_node !== 20
        || bundle?.file !== 'cos_sdk.cjs.gz'
        || !hashPattern.test(bundle.sha256) || !hashPattern.test(bundle.uncompressed_sha256)
        || !Number.isSafeInteger(bundle.uncompressed_size)
        || bundle.uncompressed_size <= 0) throw new Error('invalid SDK metadata');
    const archive = fs.readFileSync(path.join(__dirname, bundle.file));
    if (archive.length !== bundle.size || sha256(archive) !== bundle.sha256) {
      throw new Error('SDK checksum mismatch');
    }
    const root = path.join(__dirname, '.cos-sdk');
    privateDirectory(root);
    // 第三方 bundle 按依赖加载，避免 Node 将其旧 API 当作应用代码报告弃用。
    const modules = path.join(root, 'node_modules');
    privateDirectory(modules);
    const directory = path.join(modules, bundle.sha256);
    privateDirectory(directory);
    const file = path.join(directory, 'cos_sdk.cjs');
    const info = lstat(file);
    if (info && (!info.isFile() || info.isSymbolicLink())) throw new Error('invalid SDK cache file');
    if (!info || info.size !== bundle.uncompressed_size
        || sha256(fs.readFileSync(file)) !== bundle.uncompressed_sha256) {
      const content = zlib.gunzipSync(archive, { maxOutputLength: bundle.uncompressed_size });
      if (content.length !== bundle.uncompressed_size || sha256(content) !== bundle.uncompressed_sha256) {
        throw new Error('SDK bundle checksum mismatch');
      }
      const temporary = path.join(directory, `.extract-${process.pid}-${crypto.randomUUID()}`);
      try {
        fs.writeFileSync(temporary, content, { flag: 'wx', mode: 0o600 });
        fs.renameSync(temporary, file);
      } finally {
        fs.rmSync(temporary, { force: true });
      }
    }
    // 完整校验后才加载；不从宿主 node_modules 搜索 SDK。
    if (sdk && sdkPath === file) return sdk;
    delete require.cache[require.resolve(file)];
    sdk = require(file);
    if (typeof sdk !== 'function') throw new Error('invalid SDK export');
    sdkPath = file;
    return sdk;
  } catch {
    throw new CosSdkUnavailable();
  }
}

function requirePrivateGrant(file) {
  const info = fs.lstatSync(file);
  if (!info.isFile() || info.isSymbolicLink()) throw new Error('upload grant must be a private regular file');
  if (process.platform !== 'win32') {
    if (info.uid !== process.getuid() || (info.mode & 0o077)) {
      throw new Error('upload grant must be a private regular file');
    }
    return;
  }
}

function checkpointPath(resourceId) {
  if (!resourcePattern.test(resourceId)) throw new Error('invalid resource ID');
  return path.join(os.homedir(), '.openagent', 'cos-upload', `${resourceId}.json`);
}

async function checkSource(file, resourceId, key) {
  const digest = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(file)) digest.update(chunk);
  const fingerprint = digest.digest('hex');
  const expected = { key, size_bytes: fs.statSync(file).size, sha256: fingerprint };
  const checkpoint = checkpointPath(resourceId);
  fs.mkdirSync(path.dirname(checkpoint), { recursive: true, mode: 0o700 });
  try {
    fs.writeFileSync(checkpoint, JSON.stringify(expected), { flag: 'wx', mode: 0o600 });
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
    const previous = JSON.parse(fs.readFileSync(checkpoint, 'utf8'));
    if (Object.keys(previous).length !== 3 || previous.key !== expected.key
        || previous.size_bytes !== expected.size_bytes || previous.sha256 !== expected.sha256) {
      throw new SourceChanged();
    }
  }
  return fingerprint;
}

async function upload(file, prepared, { createClient } = {}) {
  const resourceId = prepared?.resource_id;
  const attachment = prepared?.attachment;
  const grant = prepared?.cos;
  if (prepared?.view !== 'openagent_file_upload' || prepared?.status !== 'pending'
      || typeof resourceId !== 'string' || !resourcePattern.test(resourceId)
      || !attachment || !grant || typeof attachment !== 'object' || typeof grant !== 'object') {
    throw new Error('invalid upload grant');
  }
  if (attachment.type !== 'file' || attachment.title !== path.basename(file)
      || attachment.resource_uri !== `oasn-resource://cos-files/${resourceId}`
      || typeof attachment.mime_type !== 'string' || !Number.isSafeInteger(attachment.size_bytes)
      || attachment.size_bytes !== fs.statSync(file).size) throw new Error('file does not match upload grant');
  for (const field of ['bucket', 'region', 'key', 'tmp_secret_id', 'tmp_secret_key', 'session_token']) {
    if (typeof grant[field] !== 'string' || !grant[field]) throw new Error('incomplete upload grant');
  }
  if (!grant.key.startsWith(`uploads/${resourceId}/`) || !Number.isSafeInteger(grant.expired_time)
      || grant.expired_time <= Date.now() / 1000 + 60) throw new Error('expired or invalid upload grant');
  const fingerprint = await checkSource(file, resourceId, grant.key);
  const options = {
    SecretId: grant.tmp_secret_id, SecretKey: grant.tmp_secret_key, SecurityToken: grant.session_token,
    Protocol: 'https:', StrictSsl: true, Timeout: 30000, ChunkParallelLimit: 2,
    UploadCheckContentMd5: false, UploadIdCacheLimit: 0, ConfCwd: path.dirname(checkpointPath(resourceId)),
  };
  const client = createClient ? createClient(options) : new (loadSdk())(options);
  await new Promise((resolve, reject) => client.uploadFile({
    Bucket: grant.bucket, Region: grant.region, Key: grant.key, FilePath: file,
    ContentType: attachment.mime_type, SliceSize: 8 * 1024 * 1024, ChunkSize: 8 * 1024 * 1024,
  }, error => error ? reject(error) : resolve()));
  if (await checkSource(file, resourceId, grant.key) !== fingerprint) throw new SourceChanged();
  return resourceId;
}

async function main(argv = process.argv.slice(2), options = {}) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) {
    const name = argv[i];
    if (!['--file', '--grant-file', '--forget-resource-id'].includes(name)
        || typeof argv[i + 1] !== 'string' || !argv[i + 1] || args[name]) throw new Error('invalid arguments');
    args[name] = argv[i + 1];
  }
  if (args['--forget-resource-id']) {
    if (args['--file'] || args['--grant-file']) throw new Error('invalid cleanup request');
    const checkpoint = checkpointPath(args['--forget-resource-id']);
    try { fs.rmSync(checkpoint, { force: true }); }
    catch { throw new CheckpointCleanupError(); }
    return;
  }
  if (!args['--file'] || !args['--grant-file']) throw new Error('file and grant file are required');
  const grantFile = path.resolve(args['--grant-file']);
  requirePrivateGrant(grantFile);
  let prepared;
  try { prepared = JSON.parse(fs.readFileSync(grantFile, 'utf8')); }
  finally { fs.unlinkSync(grantFile); }
  const file = fs.realpathSync(args['--file']);
  if (!fs.statSync(file).isFile()) throw new Error('upload source must be a file');
  const resourceId = await upload(file, prepared, options);
  process.stdout.write(JSON.stringify({ resource_id: resourceId, upload_returned: true }) + '\n');
}

function reportError(error) {
  if (error instanceof CheckpointCleanupError) {
    process.stderr.write('COS checkpoint cleanup did not complete; upload result is unchanged.\n');
  } else if (error instanceof CosSdkUnavailable) {
    process.stderr.write('COS_UPLOAD_SDK_UNAVAILABLE: use Node.js 20+, ensure scripts/.cos-sdk is writable, and repair or reinstall the plugin with its bundled SDK files.\n');
  } else if (error instanceof SourceChanged) {
    process.stderr.write('COS_UPLOAD_SOURCE_CHANGED: stop this upload; use a new upload key for the changed file.\n');
  } else {
    // SDK 异常可能含签名或临时凭据，只保留已知错误码和HTTP状态。
    process.stderr.write('COS upload did not complete; do not start the Agent Run.\n');
    const allowedCodes = new Set([
      'ETIMEDOUT', 'ESOCKETTIMEDOUT', 'ECONNRESET', 'ECONNREFUSED', 'EPIPE', 'ENOTFOUND', 'EAI_AGAIN',
      'ERR_TLS_CERT_ALTNAME_INVALID', 'DEPTH_ZERO_SELF_SIGNED_CERT', 'SELF_SIGNED_CERT_IN_CHAIN',
      'UNABLE_TO_VERIFY_LEAF_SIGNATURE', 'UNABLE_TO_GET_ISSUER_CERT_LOCALLY', 'CERT_HAS_EXPIRED',
      'EACCES', 'EPERM', 'ENOENT', 'EIO',
      'AccessDenied', 'SignatureDoesNotMatch', 'RequestTimeTooSkewed', 'InvalidAccessKeyId',
      'ExpiredToken', 'InvalidToken', 'NoSuchBucket', 'NoSuchUpload', 'RequestTimeout',
      'InternalError', 'ServiceUnavailable', 'SlowDown',
    ]);
    const code = [error?.code, error?.error?.code, error?.error?.Code].find(value => allowedCodes.has(value));
    const status = error?.statusCode;
    const details = [];
    if (code) details.push(`code=${code}`);
    if (Number.isInteger(status) && status >= 400 && status <= 599) details.push(`http_status=${status}`);
    if (details.length) process.stderr.write(`COS_UPLOAD_ERROR: ${details.join(' ')}\n`);
  }
  process.exitCode = 1;
}

module.exports = { loadSdk, requirePrivateGrant, checkpointPath, checkSource, upload, main, reportError,
  SourceChanged, CosSdkUnavailable };
if (require.main === module) main().catch(reportError);
