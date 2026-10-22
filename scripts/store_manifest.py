"""The publisher and synchronizer share one strict manifest/APK contract."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

MAX_APK = 512 * 1024 * 1024
HEX = re.compile(r'^[0-9a-f]{64}$')
PACKAGE = re.compile(r'^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$')

def text(value, maximum, required=True):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError('Invalid manifest text')
    if re.search(r'YOUR[_ -]|REPLACE[_ -]|CHANGEME|TODO|<[^>]+>', value, re.I):
        raise ValueError('Manifest contains a placeholder or markup')
    return value

def https_url(value, allow_empty=False):
    if allow_empty and value == '':
        return value
    text(value, 2048)
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('Only public HTTPS URLs without credentials are allowed')
    if parsed.hostname.lower() in ('localhost', 'localhost.localdomain') or ':' in parsed.hostname or re.fullmatch(r'[0-9.]+', parsed.hostname):
        raise ValueError('Image URLs must use a public DNS hostname')
    return value

def validate_metadata(m):
    for key, maximum in [('name',80),('summary',200),('description',10000),('category',40),('author',80)]:
        text(m.get(key), maximum)
    if not isinstance(m.get('tags'),list) or len(m['tags']) > 12:
        raise ValueError('At most 12 tags are allowed')
    for tag in m['tags']:
        text(tag,40)
    https_url(m.get('iconUrl',''),True)
    if not isinstance(m.get('screenshots'),list) or len(m['screenshots']) > 8:
        raise ValueError('At most 8 screenshots are allowed')
    for url in m['screenshots']:
        https_url(url)
    for url in [m.get('iconUrl',''),*m['screenshots']]:
        if url and not urlsplit(url).path.lower().endswith('.webp'):
            raise ValueError('Publish compressed WebP icons/screenshots before generating a manifest')

def validate_manifest(m, assets, pin, repository):
    validate_metadata(m)
    if m.get('schemaVersion') != 1 or not PACKAGE.fullmatch(m.get('packageName','')):
        raise ValueError('Invalid manifest schema or package name')
    for key in ('sha256','signerSha256'):
        if not isinstance(m.get(key),str) or not HEX.fullmatch(m[key]):
            raise ValueError(f'Invalid {key}')
    for key,limit in [('versionCode',2_100_000_000),('minSdk',1000),('size',MAX_APK)]:
        if type(m.get(key)) is not int or not 0 < m[key] <= limit:
            raise ValueError(f'Invalid {key}')
    text(m.get('versionName'),80)
    if pin and (m['packageName'] != pin['packageName'] or m['signerSha256'] != pin['signerSha256']):
        raise ValueError('Pinned package/signer changed')
    asset = next((a for a in assets if a.get('name') == m.get('asset')),None)
    if not asset or not re.fullmatch(r'[A-Za-z0-9_.-]+\.apk',m.get('asset','')):
        raise ValueError('Manifest APK asset is missing')
    if asset.get('size') != m['size'] or asset.get('digest') != 'sha256:'+m['sha256']:
        raise ValueError('Public GitHub asset size/digest does not match manifest')
    url = asset.get('browser_download_url','')
    if not url.startswith(f'https://github.com/{repository}/releases/download/') or urlsplit(url).query or urlsplit(url).fragment:
        raise ValueError('APK URL does not belong to the trusted repository')
    return dict(m, githubUrl=url)

def sdk_tool(name):
    sdk = os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT')
    if not sdk:
        raise ValueError('Set ANDROID_HOME to the installed Android SDK')
    folders = [p for p in (Path(sdk)/'build-tools').iterdir() if re.fullmatch(r'\d+(?:\.\d+)*',p.name)]
    suffix = '.bat' if name == 'apksigner' and os.name == 'nt' else '.exe' if os.name == 'nt' else ''
    for folder in sorted(folders,key=lambda p:tuple(map(int,p.name.split('.'))),reverse=True):
        path = folder/(name+suffix)
        if path.exists():
            return str(path)
    raise ValueError(f'Android SDK tool not found: {name}')

def inspect_apk(path):
    badging = subprocess.check_output([sdk_tool('aapt'),'dump','badging',str(path)],text=True,encoding='utf-8',errors='replace',timeout=120)
    package = re.search(r"^package: name='([^']+)' versionCode='(\d+)' versionName='([^']*)'",badging,re.M)
    sdk = re.search(r"^sdkVersion:'(\d+)'",badging,re.M)
    certs = subprocess.check_output([sdk_tool('apksigner'),'verify','--verbose','--print-certs',str(path)],text=True,encoding='utf-8',errors='replace',timeout=120)
    signers = sorted(set(re.findall(r'^(?:Signer #\d+|V\d+(?:\.\d+)? Signer:) certificate SHA-256 digest: ([0-9a-fA-F]+)$',certs,re.M)))
    if not package or not sdk or len(signers) != 1 or not re.search(r'^Number of signers: 1$',certs,re.M):
        raise ValueError('APK must be signed by exactly one signer with readable package metadata')
    with open(path,'rb') as apk:
        digest = hashlib.file_digest(apk,'sha256').hexdigest()
    return {'packageName':package[1],'versionCode':int(package[2]),'versionName':package[3],'minSdk':int(sdk[1]),'signerSha256':signers[0].lower(),'sha256':digest,'size':Path(path).stat().st_size}

def publish_manifest(apk, metadata, output):
    m = json.loads(Path(metadata).read_text(encoding='utf-8-sig'))
    validate_metadata(m)
    m = {key:m[key] for key in ('name','summary','description','category','author','tags','iconUrl','screenshots')}
    m.update(inspect_apk(apk),schemaVersion=1,asset=Path(apk).name)
    validate_manifest(m,[{'name':m['asset'],'size':m['size'],'digest':'sha256:'+m['sha256'],'browser_download_url':'https://github.com/local/publisher/releases/download/check/'+m['asset']}],None,'local/publisher')
    Path(output).write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Generate store-manifest.json from an actual signed APK')
    parser.add_argument('--apk',required=True)
    parser.add_argument('--metadata',required=True)
    parser.add_argument('--output',default='store-manifest.json')
    args = parser.parse_args()
    publish_manifest(args.apk,args.metadata,args.output)
