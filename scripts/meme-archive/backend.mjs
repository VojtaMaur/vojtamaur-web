#!/usr/bin/env node
/** Persistent JSON-lines adapter to the bundled, unmodified raptorq 2.0.1 codec.
 * RFC 6330 OTI and encoding packets are passed through as binary data; base64
 * exists only on this local process pipe, never inside the archive QR codes.
 */
import fs from 'node:fs/promises';
import readline from 'node:readline';

const MAX_TRANSFER = 64 * 1024 * 1024;
const MAX_ESI = 0xffffff;
const { instance } = await WebAssembly.instantiate(await fs.readFile(new URL('./raptorq.wasm', import.meta.url)));
const wasm = instance.exports;
let encoder = null;
let decoder = null;
let decoded = null;

function integer(value, name, low, high) {
  if (!Number.isSafeInteger(value) || value < low || value > high) {
    throw new Error(`${name} must be an integer in ${low}..${high}`);
  }
  return value;
}

function binary(value, name) {
  if (typeof value !== 'string' || value.length > Math.ceil(MAX_TRANSFER / 3) * 4 ||
      value.length % 4 !== 0 || !/^[A-Za-z0-9+/]*={0,2}$/.test(value)) {
    throw new Error(`${name} must be canonical base64`);
  }
  const bytes = Buffer.from(value, 'base64');
  if (bytes.toString('base64') !== value) throw new Error(`${name} must be canonical base64`);
  return bytes;
}

function input(bytes, callback) {
  const pointer = wasm.alloc(bytes.length);
  try {
    new Uint8Array(wasm.memory.buffer, pointer, bytes.length).set(bytes);
    return callback(pointer);
  } finally {
    wasm.dealloc(pointer, bytes.length);
  }
}

function output() {
  return Buffer.from(new Uint8Array(wasm.memory.buffer, wasm.output_ptr(), wasm.output_len()));
}

function counts(length, size, blocks) {
  const total = Math.ceil(length / size);
  const small = Math.floor(total / blocks);
  const largeBlocks = total % blocks;
  return Array.from({ length: blocks }, (_, i) => small + Number(i < largeBlocks));
}

function parseOTI(oti) {
  if (oti.length !== 12) throw new Error('OTI must contain exactly 12 RFC 6330 bytes');
  const length = oti.readUIntBE(0, 5);
  const size = oti.readUInt16BE(6);
  const blocks = oti[8];
  integer(length, 'transfer length', 1, MAX_TRANSFER);
  integer(size, 'symbol size', 1, 65535);
  integer(blocks, 'source blocks', 1, 255);
  if (oti[5] !== 0 || oti.readUInt16BE(9) !== 1 || oti[11] !== 1) {
    throw new Error('Unsupported RFC 6330 OTI profile: reserved=0, N=1, Al=1 required');
  }
  const sourceCounts = counts(length, size, blocks);
  if (Math.min(...sourceCounts) < 1 || Math.max(...sourceCounts) > 56403) {
    throw new Error('OTI source block size is outside RFC 6330 limits');
  }
  return { oti, length, size, blocks, sourceCounts };
}

async function request(message) {
  switch (message.op) {
    case 'init_encoder': {
      const data = binary(message.data, 'data');
      integer(data.length, 'data length', 1, MAX_TRANSFER);
      const size = integer(message.symbol_size, 'symbol_size', 1, 65535);
      const blocks = Math.ceil(Math.ceil(data.length / size) / 1024);
      integer(blocks, 'source blocks', 1, 255);
      input(data, pointer => wasm.init_encoder(pointer, data.length, size, blocks));
      encoder = { ...parseOTI(output()), data };
      return { oti: encoder.oti.toString('base64'), symbol_size: size,
        block_count: blocks, source_counts: encoder.sourceCounts };
    }
    case 'packet': {
      if (!encoder) throw new Error('init_encoder must be called first');
      const index = integer(message.index, 'index', 0, (MAX_ESI + 1) * encoder.blocks - 1);
      const block = index % encoder.blocks;
      const esi = Math.floor(index / encoder.blocks);
      const count = encoder.sourceCounts[block];
      let packet;
      if (esi < count) {
        // N=1/Al=1 makes systematic source symbols contiguous. This avoids
        // materializing every source packet for each individual request.
        packet = Buffer.alloc(4 + encoder.size);
        packet[0] = block;
        packet.writeUIntBE(esi, 1, 3);
        const preceding = encoder.sourceCounts.slice(0, block).reduce((a, b) => a + b, 0);
        const start = (preceding + esi) * encoder.size;
        encoder.data.copy(packet, 4, start, Math.min(start + encoder.size, encoder.data.length));
      } else {
        wasm.packet(block, esi, count);
        packet = output();
      }
      return { packet: packet.toString('base64') };
    }
    case 'init_decoder': {
      decoder = parseOTI(binary(message.oti, 'oti'));
      input(decoder.oti, pointer => wasm.init_decoder(pointer));
      decoded = null;
      return { ok: true, source_counts: decoder.sourceCounts };
    }
    case 'decode': {
      if (!decoder) throw new Error('init_decoder must be called first');
      const packet = binary(message.packet, 'packet');
      if (packet.length !== 4 + decoder.size || packet[0] >= decoder.blocks) {
        throw new Error('Packet length or source block number does not match OTI');
      }
      if (decoded === null && input(packet, pointer => wasm.decode(pointer, packet.length))) {
        decoded = output().toString('base64');
      }
      return { data: decoded };
    }
    default:
      throw new Error(`Unknown operation: ${String(message.op)}`);
  }
}

const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of lines) {
  try {
    if (line.length > Math.ceil(MAX_TRANSFER / 3) * 4 + 1024) throw new Error('Request exceeds backend input limit');
    const message = JSON.parse(line);
    if (!message || typeof message !== 'object' || Array.isArray(message)) throw new Error('Expected JSON object');
    process.stdout.write(`${JSON.stringify(await request(message))}\n`);
  } catch (error) {
    process.stdout.write(`${JSON.stringify({ error: error.message })}\n`);
  }
}
