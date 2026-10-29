# Meme Archive transport v1

This document defines the application wrapper **MA1**, not a new fountain code.
RaptorQ is exactly [RFC 6330](https://www.rfc-editor.org/rfc/rfc6330.html),
FEC Encoding ID **6**, with its standard OTI and FEC Payload ID. Integer fields
use network byte order (big endian). QR uses ISO/IEC 18004 byte mode: the bytes
below are embedded directly, without UTF-8 conversion, JSON, URLs or base64.
Base64 is used only on the local Python/Node process pipe.

## QR byte layout

| Offset | Bytes | Meaning |
| --- | ---: | --- |
| 0 | 2 | ASCII `MA` (`4d41`) |
| 2 | 1 | Application format version, `01` |
| 3 | 1 | FEC Encoding ID, `06` = RFC 6330 RaptorQ |
| 4 | 1 | Compression ID, `01` = one gzip member, RFC 1952 |
| 5 | 16 | Opaque edition ID; only combine symbols with identical ID **and OTI** |
| 21 | 12 | RFC 6330 §3.3 OTI, unchanged wire representation |
| 33 | 1 | Source Block Number (SBN), first byte of RFC §3.2 FEC Payload ID |
| 34 | 3 | Encoding Symbol ID (ESI), unsigned 24-bit, remaining FEC Payload ID |
| 37 | T | Exactly one complete RaptorQ encoding symbol, including final padding |
| 37+T | 4 | CRC-32/ISO-HDLC over bytes `[0,37+T)`, big endian |

Total length is **T + 41 bytes**. Default T=512 gives 553 bytes, QR version 18
at ECC M. Receivers MUST reject unknown magic/version/FEC/compression IDs,
invalid CRC, incorrect packet length, invalid OTI or SBN outside its partition.
CRC-32 parameters are those used by `zlib.crc32` and the gzip CRC algorithm in
RFC 1952 (polynomial 0x04C11DB7, reflected 0xEDB88320, init/xorout 0xffffffff).

The unchanged 12-byte OTI consists of:

| OTI offset | Bytes | Meaning |
| --- | ---: | --- |
| 0 | 5 | Transfer Length F in bytes, including the object wrapper below |
| 5 | 1 | Reserved, zero |
| 6 | 2 | Symbol size T |
| 8 | 1 | Source block count Z |
| 9 | 2 | Sub-block count N |
| 11 | 1 | Symbol alignment Al |

MA1 profile fixes **N=1, Al=1**. F, T and Z are present in every QR, so loss of
the first image or external manifest cannot remove decoder configuration.
RFC partitioning and the finite ESI range still apply. The bundled generator
chooses Z=`ceil(ceil(F/T)/1024)`, up to 255. Other encoders may choose a valid Z
within the same profile and RFC source-block limit K≤56403. The bundled decoder
limits F to 64 MiB. No implementation-specific seed is needed by RaptorQ.

## Encoded object

The RaptorQ transfer object (exactly F bytes, before RaptorQ zero padding) is:

```
4 bytes   ASCII MAO1
32 bytes  SHA-256 of original ALL_POSTS.txt bytes
remaining one complete gzip member of those original bytes
```

This adds a one-time 36-byte object wrapper rather than repeating a full hash
in every QR. Gzip uses [RFC 1952](https://www.rfc-editor.org/rfc/rfc1952.html)
and DEFLATE [RFC 1951](https://www.rfc-editor.org/rfc/rfc1951.html). Generation
uses level 9, MTIME=0, OS=255, and no filename/comment/extra fields. Decoders
MUST verify gzip CRC/ISIZE and SHA-256, reject truncated/trailing/multiple gzip
members and apply an explicit decompression limit before writing output. Text
bytes, BOM and line endings are preserved exactly. SHA-256 is specified in
[FIPS 180-4](https://doi.org/10.6028/NIST.FIPS.180-4).

## Edition and order

Edition IDs are opaque to decoders. This generator takes the first 16 bytes
of SHA-256 of a canonical UTF-8 JSON recipe (`sort_keys=True`, no whitespace,
Unicode retained). The recipe includes generator version, seed, archive-object
SHA-256, frozen-catalogue SHA-256, font SHA-256, render settings, rat image weight
and base64 OTI. The random default seed makes independent runs distinct; fixed
seed and identical inputs/settings reproduce the same edition. The timestamp
and start index do not enter the ID. The manifest records the full recipe.

Generator 1.1 includes caption/footer language (`en`, `cs`, `en+cs`) in render
settings and records each caption's language in the frozen catalogue. This is
an edition/rendering choice only: the complete original TXT is still encoded,
and the MA1 binary transport and independent decoder procedure are unchanged.
Legacy 1.0 editions retain their original catalogue, recipe and footer on resume.
Generator 1.1.1 also freezes a footer recovery estimate in those settings:
minimum `ceil(F/T)` and suggested `ceil(F/T) + 2*Z` distinct memes. These are
calculated from the actual RaptorQ object/partition, not from the requested
output count. Enough independent symbols from every block are still required;
the suggested figure is a small repair allowance, not an unconditional guarantee.

Global meme index i starts at zero. Packet SBN=`i mod Z`; ESI=`floor(i/Z)`.
For each block, ESI 0..K-1 are systematic source symbols and ESI≥K are standard
RaptorQ repair symbols. Any QR can be lost, renamed, duplicated or reordered.
Recovery requires enough independent symbols **for every block**; no fixed
count guarantees recovery from an arbitrary unbalanced collection. Stop before
ESI exceeds 0xffffff; never wrap the ID. Continuous generation is bounded by
this RFC namespace and available disk space.

Mixing edition IDs or OTI is an error unless the user explicitly selects one
edition. Duplicates with identical (SBN,ESI) and bytes are ignored; conflicting
payloads with the same key are rejected. CRC and SHA-256 provide integrity
against accidental corruption, not authentication or an author's signature.

## Independent decoder procedure

1. Scan QR byte segments into raw bytes. Do not use a scanner's Unicode text
   value; arbitrary RaptorQ bytes are often invalid UTF-8.
2. Validate the MA1 wrapper and CRC, group by edition ID and OTI, deduplicate
   (SBN,ESI), and feed the RFC FEC Payload ID + T-byte symbol to a standard
   RaptorQ decoder configured with the transmitted OTI.
3. Once exactly F object bytes are recovered, validate `MAO1`, decompress the
   one gzip member under a size limit and compare the full SHA-256.
4. Write the verified original `ALL_POSTS.txt` bytes. No image metadata,
   external service, manifest or original website is needed.

QR ECC is independent of RaptorQ erasure repair. The former corrects damage
inside one QR; the latter recovers missing encoding symbols across images.
The reference renderer uses a separate white footer, four-module quiet zone,
integer pixel scaling and lossless PNG. It never overlays the QR on a photo.
