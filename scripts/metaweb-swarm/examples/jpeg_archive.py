"""Embed real file bytes in JPEG APP13 blocks; stdlib only, no image re-encoding.

CLI: jpeg_archive.py COVER.jpg SOURCE_EXPORT OUTPUT.jpg
Recovery uses the separate jpeg_extract_independent.py and only OUTPUT.jpg.
Custom MWJ1 payload format, not IPTC, XMP or an Adobe-registered resource.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile

MAX_BYTES=64_000_000
CHUNK_BYTES=60_000
RESOURCE_ID=0xBEEF
RESOURCE_NAME=b'Metaweb archive v1'
PS_HEADER=b'Photoshop 3.0\x00'


def header_segments(data):
    if not data.startswith(b'\xff\xd8') or not data.endswith(b'\xff\xd9'):
        raise ValueError('Cover needs JPEG SOI/EOI')
    offset=2;frame=False
    while offset<len(data):
        start=offset
        if data[offset]!=255:raise ValueError('Invalid JPEG marker boundary')
        while offset<len(data) and data[offset]==255:offset+=1
        if offset>=len(data):raise ValueError('Truncated JPEG marker')
        marker=data[offset];offset+=1
        if marker in (0,0xD8,0xD9) or 0xD0<=marker<=0xD7:raise ValueError('Unexpected marker before scan')
        if marker==1:continue
        if offset+2>len(data):raise ValueError('Truncated JPEG segment length')
        length=int.from_bytes(data[offset:offset+2],'big');end=offset+length
        if length<2 or end>len(data):raise ValueError('Truncated JPEG segment')
        body=data[offset+2:end]
        if marker in {0xC0,0xC1,0xC2,0xC3,0xC5,0xC6,0xC7,0xC9,0xCA,0xCB,0xCD,0xCE,0xCF}:frame=True
        if marker==0xDA:
            if not frame:raise ValueError('JPEG has no image frame')
            yield marker,body,start,end
            return
        yield marker,body,start,end
        offset=end
    raise ValueError('JPEG has no image scan')


def segment(marker,body):
    if len(body)>65533:raise ValueError('JPEG segment too large')
    return b'\xff'+bytes([marker])+struct.pack('>H',len(body)+2)+body


def resource(index,count,body):
    name=bytes([len(RESOURCE_NAME)])+RESOURCE_NAME
    if len(name)%2:name+=b'\x00'
    payload=b'MWJ1'+struct.pack('>II',index,count)+body
    block=b'8BIM'+struct.pack('>H',RESOURCE_ID)+name+struct.pack('>I',len(payload))+payload
    if len(payload)%2:block+=b'\x00'
    return segment(0xED,PS_HEADER+block)


def pack(cover,payload,filename):
    if not 0<len(payload)<=MAX_BYTES or len(cover)>MAX_BYTES:raise ValueError('Input exceeds bounded prototype capacity')
    if not filename or len(filename.encode('utf-8'))>255 or Path(filename).name!=filename:
        raise ValueError('Store only a bounded export basename')
    headers=list(header_segments(cover))
    if any(m==0xED and RESOURCE_NAME in b and b'MWJ1' in b for m,b,_,_ in headers):
        raise ValueError('Cover already contains a Metaweb archive')
    count=(len(payload)+CHUNK_BYTES-1)//CHUNK_BYTES
    manifest={'format':'metaweb-jpeg-archive-v1','filename':filename,'bytes':len(payload),
              'sha256':hashlib.sha256(payload).hexdigest(),'chunks':count,'chunk_bytes':CHUNK_BYTES}
    encoded=json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    blocks=[resource(0,count,encoded)]
    blocks.extend(resource(n+1,count,payload[n*CHUNK_BYTES:(n+1)*CHUNK_BYTES]) for n in range(count))
    note=('Metaweb archive v1; APP13/8BIM custom resource 0xBEEF; MWJ1 sequence 0 is JSON, '
          '1..N are raw export chunks; SHA256='+manifest['sha256']+'; https://vojtamaur.cz/').encode('ascii')
    blocks.append(segment(0xFE,note))
    insertion=headers[-1][2]  # Before SOS; preserve original image stream exactly.
    result=cover[:insertion]+b''.join(blocks)+cover[insertion:]
    if len(result)>MAX_BYTES:raise ValueError('Result exceeds prototype output bound')
    return result,manifest


def atomic_write(path,body):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    name=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as stream:
            name=stream.name;stream.write(body)
        os.replace(name,path);name=None
    finally:
        if name:Path(name).unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cover');parser.add_argument('source');parser.add_argument('output')
    args=parser.parse_args()
    try:
        cover=Path(args.cover);source=Path(args.source);output=Path(args.output)
        if output.resolve() in {cover.resolve(),source.resolve()}:raise ValueError('Output must differ from both inputs')
        if cover.stat().st_size>MAX_BYTES or source.stat().st_size>MAX_BYTES:raise ValueError('Input too large')
        body,manifest=pack(cover.read_bytes(),source.read_bytes(),source.name)
        atomic_write(output,body)
        print(json.dumps(dict(manifest,carrier_bytes=len(body)),ensure_ascii=False))
    except (ValueError,OSError) as error:parser.exit(2,str(error)+'\n')


if __name__=='__main__':main()
