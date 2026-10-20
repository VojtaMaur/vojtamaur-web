"""Portable RS payload prototype. Preserves raw bytes; no print/scan or custody claim.

Dependency/API reference: https://pypi.org/project/reedsolo/1.7.0/
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib
from reedsolo import RSCodec, ReedSolomonError

MAGIC=b'MWRS\x01'
MAX_BYTES=128*1024*1024


def encode(raw,parity=32):
    if not 2<=parity<=128 or len(raw)>MAX_BYTES:raise ValueError('Unsupported parity or payload size')
    body=bytes(RSCodec(parity).encode(zlib.compress(raw,9)))
    header={'format':'metaweb-rs-payload-v1','codec':'reedsolo-1.7.0','parity':parity,'codeword_bytes':255,
        'raw_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'crc32':zlib.crc32(raw),'body_bytes':len(body)}
    meta=json.dumps(header,sort_keys=True,separators=(',',':')).encode('ascii')
    return MAGIC+struct.pack('>I',len(meta))+meta+body


def parts(card):
    if not card.startswith(MAGIC) or len(card)<9:raise ValueError('Invalid header')
    size=struct.unpack('>I',card[5:9])[0]
    if not 1<=size<=4096 or len(card)<9+size:raise ValueError('Invalid header length')
    header=json.loads(card[9:9+size]);body=card[9+size:]
    if header.get('format')!='metaweb-rs-payload-v1' or header.get('codeword_bytes')!=255:raise ValueError('Unsupported format')
    if type(header.get('parity')) is not int or not 2<=header['parity']<=128:raise ValueError('Invalid parity')
    if type(header.get('raw_bytes')) is not int or not 0<=header['raw_bytes']<=MAX_BYTES:raise ValueError('Invalid payload size')
    if len(body)!=header.get('body_bytes'):raise ValueError('Missing unframed bytes; supply indexed erasure slots rather than deleting bytes')
    return header,body,9+size


def decode(card,erase_positions=None,expected_sha256=None):
    header,body,_=parts(card)
    positions=list(erase_positions or [])
    if any(type(p) is not int or not 0<=p<len(body) for p in positions) or len(set(positions))!=len(positions):raise ValueError('Invalid body-relative erasure positions')
    by_block={}
    for position in positions:by_block.setdefault(position//255,[]).append(position%255)
    codec=RSCodec(header['parity'])
    repaired=b''.join(bytes(codec.decode(body[start:start+255],erase_pos=by_block.get(start//255,[]))[0])
                      for start in range(0,len(body),255))
    decompressor=zlib.decompressobj()
    raw=decompressor.decompress(repaired,header['raw_bytes']+1)
    if len(raw)!=header['raw_bytes'] or not decompressor.eof or decompressor.unused_data:raise ValueError('Invalid compressed payload')
    digest=hashlib.sha256(raw).hexdigest()
    if digest!=header['sha256'] or zlib.crc32(raw)!=header['crc32']:raise ValueError('Recovered integrity mismatch')
    if expected_sha256 and digest!=expected_sha256:raise ValueError('Independent source digest mismatch')
    return raw


def damage(card,count,known_erasures=False):
    header,body,start=parts(card);altered=bytearray(body);positions=[]
    # Each codeword has independent correction capacity; retain byte positions.
    for block in range(0,len(body),255):
        for index in range(min(count,len(body)-block)):
            position=block+index;altered[position]^=0xA5;positions.append(position)
    return card[:start]+bytes(altered),positions if known_erasures else []


def verify(input_path,output_dir):
    raw=Path(input_path).read_bytes();destination=Path(output_dir);destination.mkdir(parents=True,exist_ok=True)
    card=encode(raw);(destination/'encoded.mwrs').write_bytes(card)
    loaded=(destination/'encoded.mwrs').read_bytes()
    decoded=decode(loaded)
    assert decoded==raw
    damaged,_=damage(loaded,8);(destination/'damaged.mwrs').write_bytes(damaged)
    recovered=decode((destination/'damaged.mwrs').read_bytes())
    assert recovered==raw
    (destination/'recovered.bin').write_bytes(recovered)
    erased,positions=damage(loaded,24,known_erasures=True)
    (destination/'erasures.mwrs').write_bytes(erased)
    (destination/'erasures.json').write_text(json.dumps(positions),encoding='utf-8')
    assert decode((destination/'erasures.mwrs').read_bytes(),positions)==raw
    excessive,_=damage(loaded,40)
    rejected=False
    try:decode(excessive)
    except (ReedSolomonError,ValueError,zlib.error):rejected=True
    assert rejected,'Beyond-capacity corruption was silently accepted'
    malformed_rejected=False
    try:decode(b'not-a-valid-frame')
    except ValueError:malformed_rejected=True
    assert malformed_rejected
    report={'original_bytes':len(raw),'encoded_bytes':len(card),'original_sha256':hashlib.sha256(raw).hexdigest(),
        'round_trip':True,'eight_unknown_errors_per_codeword_recovered':True,
        'twenty_four_indexed_erasures_per_codeword_recovered':True,'beyond_capacity_rejected':rejected,
        'malformed_header_rejected':malformed_rejected,
        'limitations':'No print/scan test; header is not error-corrected; no arbitrary unindexed deletion recovery, adversarial authentication or external custody.'}
    (destination/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    for command in ('encode','decode','verify'):
        child=sub.add_parser(command);child.add_argument('input');child.add_argument('output')
        if command=='decode':child.add_argument('--erasures');child.add_argument('--expected-sha256')
    args=parser.parse_args()
    if args.command=='verify':verify(args.input,args.output)
    elif args.command=='encode':Path(args.output).write_bytes(encode(Path(args.input).read_bytes()))
    else:
        erasures=json.loads(Path(args.erasures).read_text()) if args.erasures else []
        Path(args.output).write_bytes(decode(Path(args.input).read_bytes(),erasures,args.expected_sha256))
