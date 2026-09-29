"""Read-only integration check: python scripts/tests/check_built_dist.py dist [--usb]."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile


def check(dist, usb=False):
    dist = dist.resolve()
    manifest = (dist / 'SHA256SUMS.txt').read_bytes()
    digest = hashlib.sha256(manifest).hexdigest()
    assert (dist / 'BUILD_SHA256.txt').read_text().strip() == digest + '  SHA256SUMS.txt'
    integrity = json.loads((dist / 'integrity.json').read_text())
    assert integrity['buildHash'] == digest
    assert integrity['buildType'] == ('usb' if usb else 'web')
    covered = set()
    for line in manifest.decode().splitlines():
        expected, name = line.split('  ', 1)
        file = dist.joinpath(*name.split('/')).resolve()
        assert file.is_relative_to(dist)
        assert hashlib.sha256(file.read_bytes()).hexdigest() == expected, name
        covered.add(name)
    with zipfile.ZipFile(dist / 'source/vojtamaur-web-source.zip') as archive:
        assert 'MEDIA_MANIFEST.json' in archive.namelist()
        assert 'MEDIA_SHA256SUMS.txt' in archive.namelist()
        assert archive.read('BUILD_HASH_HISTORY.txt') == (dist / 'BUILD_HASH_HISTORY.txt').read_bytes()
        assert 'scripts/enrich-sitemap.mjs' in archive.namelist()
    assert not (dist / 'MEDIA_MANIFEST.json').exists()
    assert not (dist / 'MEDIA_SHA256SUMS.txt').exists()
    if usb:
        assert not list(dist.glob('sitemap*.xml'))
        assert (dist / 'en/koncepty.html').exists()
        print(f'USB OK: {len(covered)} hashes, source ZIP, no sitemap')
        return
    spec = importlib.util.spec_from_file_location('wayback', Path(__file__).resolve().parents[1] / 'export-wayback-snapshots.py')
    wayback = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wayback)
    urls, errors = wayback.collect_urls(dist=dist)
    assert errors == 0 and urls
    assert len(urls) == len(set(urls))
    counts = Counter(wayback.url_type(url) for url in urls)
    assert all(counts[kind] > 0 for kind in wayback.TYPES), counts
    assert 'https://vojtamaur.cz/ns/' in urls
    for url in urls:
        urlpath = unquote(urlsplit(url).path).lstrip('/')
        if urlpath.endswith('/') or not urlpath:
            urlpath += 'index.html'
        file = dist.joinpath(*urlpath.split('/')).resolve()
        assert file.is_relative_to(dist) and file.is_file(), url
    ns = {'s': wayback.SITEMAP_NS, 'image': wayback.IMAGE_NS}
    index = ET.parse(dist / 'sitemap-index.xml')
    children = [el.text for el in index.findall('s:sitemap/s:loc', ns)]
    assert children == ['https://vojtamaur.cz/sitemap-0.xml'], children
    assert 'sitemap-index.xml' in covered
    tree = ET.parse(dist / 'sitemap-0.xml')
    assert 'sitemap-0.xml' in covered
    images = tree.findall('s:url/image:image/image:loc', ns)
    assert images
    for entry in tree.findall('s:url', ns):
        image_urls = entry.findall('image:image/image:loc', ns)
        assert len(image_urls) <= 1000
        assert len(image_urls) == len({el.text for el in image_urls})
    print(f'Web OK: {len(covered)} hashes, {len(images)} image associations, {dict(counts)}, {len(urls)} unique capture URLs')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dist', type=Path)
    parser.add_argument('--usb', action='store_true')
    args = parser.parse_args()
    check(args.dist, args.usb)
