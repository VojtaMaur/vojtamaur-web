# Bundled RFC 6330 implementation

`../raptorq.wasm` is an offline WebAssembly build of the Apache-2.0
[`raptorq` 2.0.1 crate](https://crates.io/crates/raptorq/2.0.1), by Christopher
Berner, plus the small ABI in `src/lib.rs`. The crate's Rust sources are
unmodified. The adapter merely selects the N=1, Al=1 profile and exposes
arbitrary individual repair symbols. Encoding and decoding use the actual
RaptorQ construction specified by [RFC 6330](https://www.rfc-editor.org/rfc/rfc6330).
The upstream license is in `../RAPTORQ-LICENSE.txt`.

Normal export and recovery need Node.js and Python, with **no npm install,
Rust compiler, native library, or network access**. The complete codec is about
200 KiB. The JSON process interface is implemented in `../backend.mjs`.

To rebuild after changing the adapter, install Rust 1.85 or newer and its WASM
target, then run:

```sh
rustup target add wasm32-unknown-unknown
python scripts/meme-archive/wasm-adapter/build.py
```

The checked-in binary was built on Windows with `rustc 1.99.1
(58cf8f9c3 2026-10-13)`. `MEME_ARCHIVE_CARGO` may select a specific `cargo`
executable. Rebuilding downloads the exact crate archive from crates.io and
verifies SHA-256
`4d4215fb79ef19442a0c71616aabb0715a386e6a16ed9031775ee3e3f20e7502`.
It creates a temporary minimal dependency manifest that omits unused optional
Python, serde, benchmark, and test dependencies. Only the adapter and the
unchanged RFC codec are compiled. No global environment or toolchain settings
are changed by the build script. The compiler version can affect binary bytes;
the transport format and RaptorQ symbols do not depend on that binary layout.

`backend.mjs` accepts one JSON object per input line and returns exactly one
JSON object per output line. `init_encoder` accepts `data` in base64 and an
integer `symbol_size`, returning the standard 12-byte `oti`, `source_counts`,
`symbol_size`, and `block_count`. `packet` accepts `index`; the mapping is
`SBN=index % Z`, `ESI=floor(index/Z)`. `init_decoder` accepts `oti`; `decode`
accepts a base64 RFC encoding `packet` and returns `data: null` until recovery,
then base64 object bytes. Errors return `error` with a message. Base64 is used
only on this local pipe. QR codes carry the compact binary transport.

The encoder keeps the object and its source-block encoder state in memory,
then computes each requested repair symbol independently, without retaining
the preceding symbols or allocating all packets up to that ESI. Source blocks
contain at most 1,024 source symbols. The maximum index is
`Z * 2**24 - 1`, the finite namespace specified by RFC 6330. The current
backend caps the transfer object at 64 MiB and 255 source blocks. Both the
frontend and decoder validate the more restrictive QR transport profile.
