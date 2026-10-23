"""Independent stdlib reader for the documented MWJ1 JPEG prototype.

No encoder imports, original export, sidecar manifest or encoder globals.
CLI: jpeg_extract_independent.py CARRIER.jpg OUTPUT_FILE
Checks completeness and integrity, not authenticity of the self-contained hash.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile

LIMIT=64_000_000


def extract(carrier):
    if not 4<=len(carrier)<=LIMIT or carrier[:2]!=b'\xff\xd8' or carrier[-2:]!=b'\xff\xd9':
        raise ValueError('Not a bounded JPEG carrier')
    stream=io.BytesIO(carrier);stream.seek(2)
    pieces={};counts=set();has_frame=False;has_scan=False
    while stream.tell()<len(carrier):
        if stream.read(1)!=b'\xff':raise ValueError('Invalid marker boundary')
        code=stream.read(1)
        while code==b'\xff':code=stream.read(1)
        if len(code)!=1 or code in (b'\x00',b'\xd8',b'\xd9') or 0xD0<=code[0]<=0xD7:
            raise ValueError('Unexpected JPEG marker')
        if code==b'\x01':continue
        length_bytes=stream.read(2)
        if len(length_bytes)!=2:raise ValueError('Missing segment length')
        length=int.from_bytes(length_bytes,'big')
        if length<2:raise ValueError('Invalid segment length')
        block=stream.read(length-2)
        if len(block)!=length-2:raise ValueError('Truncated segment')
        if code[0] in (0xC0,0xC1,0xC2,0xC3,0xC5,0xC6,0xC7,0xC9,0xCA,0xCB,0xCD,0xCE,0xCF):has_frame=True
        if code==b'\xda':has_scan=True;break
        if code!=b'\xed' or not block.startswith(b'Photoshop 3.0\x00'):continue
        cursor=14
        while cursor<len(block):
            if block[cursor:cursor+4]!=b'8BIM' or cursor+7>len(block):raise ValueError('Malformed resource block')
            ident=int.from_bytes(block[cursor+4:cursor+6],'big');cursor+=6
            namelen=block[cursor];name=block[cursor+1:cursor+1+namelen]
            if len(name)!=namelen:raise ValueError('Truncated resource name')
            cursor+=(namelen+2)//2*2
            if cursor+4>len(block):raise ValueError('Missing resource size')
            size=int.from_bytes(block[cursor:cursor+4],'big');cursor+=4
            body=block[cursor:cursor+size]
            if len(body)!=size:raise ValueError('Truncated resource data')
            cursor+=size+(size%2)
            if cursor>len(block):raise ValueError('Missing resource padding')
            if ident!=0xBEEF or name!=b'Metaweb archive v1':continue
            if len(body)<12 or body[:4]!=b'MWJ1':raise ValueError('Invalid archive frame')
            index=int.from_bytes(body[4:8],'big');count=int.from_bytes(body[8:12],'big')
            if not 1<=count<=1100 or not 0<=index<=count or index in pieces:raise ValueError('Invalid or duplicate archive sequence')
            counts.add(count);pieces[index]=body[12:]
    if not has_frame or not has_scan:raise ValueError('Carrier has no image frame/scan')
    if len(counts)!=1 or 0 not in pieces:raise ValueError('Archive manifest absent/inconsistent')
    count=counts.pop()
    if set(pieces)!=set(range(count+1)):raise ValueError('Archive chunk missing')
    try:manifest=json.loads(pieces.pop(0).decode('utf-8'))
    except (ValueError,UnicodeError) as error:raise ValueError('Invalid embedded manifest') from error
    if not isinstance(manifest,dict):raise ValueError('Manifest must be an object')
    if (manifest.get('format')!='metaweb-jpeg-archive-v1' or type(manifest.get('bytes')) is not int
            or not 1<=manifest['bytes']<=LIMIT or type(manifest.get('chunks')) is not int
            or manifest['chunks']!=count or type(manifest.get('chunk_bytes')) is not int
            or manifest['chunk_bytes']!=60000 or (manifest['bytes']+59999)//60000!=count
            or not isinstance(manifest.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',manifest['sha256'])):
        raise ValueError('Manifest fields inconsistent')
    name=manifest.get('filename')
    if not isinstance(name,str) or not 1<=len(name.encode('utf-8'))<=255 or '/' in name or '\\' in name or '\x00' in name:
        raise ValueError('Invalid original basename')
    for index,body in pieces.items():
        expected=60000 if index<count else manifest['bytes']-(count-1)*60000
        if len(body)!=expected:raise ValueError('Chunk size mismatch')
    result=b''.join(pieces[index] for index in range(1,count+1))
    if len(result)!=manifest['bytes'] or hashlib.sha256(result).hexdigest()!=manifest['sha256']:
        raise ValueError('Recovered payload hash/length mismatch')
    return result,manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('carrier');parser.add_argument('output');args=parser.parse_args()
    temporary=None
    try:
        source=Path(args.carrier);target=Path(args.output)
        if source.resolve()==target.resolve():raise ValueError('Do not overwrite the carrier')
        if source.stat().st_size>LIMIT:raise ValueError('Carrier exceeds bounded prototype capacity')
        payload,manifest=extract(source.read_bytes())
        target.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as stream:
            temporary=stream.name;stream.write(payload)
        os.replace(temporary,target);temporary=None
        print(json.dumps(manifest,ensure_ascii=False))
    except (ValueError,OSError) as error:parser.exit(2,str(error)+'\n')
    finally:
        if temporary:Path(temporary).unlink(missing_ok=True)


if __name__=='__main__':main()
