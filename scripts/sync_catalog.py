"""Free public-runner catalog synchronization; no private Android/UI source."""
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from store_manifest import MAX_APK, https_url, inspect_apk, validate_manifest
OWNERS=('minia1234','AIProject-k')
MAX_REPOS,MAX_REQUESTS,MAX_TRANSFER=100,4000,8_000_000_000

def choose_latest(versions):
    return max(versions,key=lambda version:version['versionCode'])

def selected_repositories(registry,owners):
    if registry is None:
        return []
    linked=registry.get('linked')
    if registry.get('schemaVersion')!=1 or not isinstance(linked,list) or len(linked)>MAX_REPOS:
        raise ValueError('Invalid repository link registry')
    for repository in linked:
        if not isinstance(repository,str) or not re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+',repository) or repository.split('/')[0].lower() not in {owner.lower() for owner in owners}:
            raise ValueError('Unallowed repository in link registry')
    if len({repository.lower() for repository in linked})!=len(linked):
        raise ValueError('Duplicate repository in link registry')
    return linked

def disabled_repositories(registry,owners):
    disabled=(registry or {}).get('disabled',[])
    if not isinstance(disabled,list) or len(disabled)>2000:
        raise ValueError('Invalid disabled repository list')
    allowed={owner.lower() for owner in owners}
    if any(not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+',name) or name.split('/')[0].lower() not in allowed for name in disabled) or len({name.lower() for name in disabled})!=len(disabled):
        raise ValueError('Invalid disabled repository')
    return {name.lower() for name in disabled}

class GitHub:
    def __init__(self, token):
        self.token, self.calls, self.downloaded = token, 0, 0

    def read(self,url,limit,authenticated=False,allow_next=False):
        self.calls += 1
        if self.calls > MAX_REQUESTS:
            raise ValueError('GitHub request budget exhausted')
        if not url.startswith(('https://api.github.com/','https://github.com/','https://raw.githubusercontent.com/')):
            raise ValueError('Untrusted upstream URL')
        headers = {'User-Agent':'Indi-Store','Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}
        if authenticated:
            if not url.startswith('https://api.github.com/'):
                raise ValueError('Credentials restricted to GitHub API')
            headers['Authorization'] = 'Bearer '+self.token
        # Public asset URLs never carry the API token across the CDN redirect.
        with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=60) as response:
            body = response.read(limit+1)
            self.downloaded += len(body)
            if self.downloaded > MAX_TRANSFER:
                raise ValueError('Upstream transfer budget exhausted')
            if len(body) > limit:
                raise ValueError('GitHub response exceeds limit')
            if not allow_next and 'rel="next"' in response.headers.get('Link',''):
                raise ValueError('Discovery/history exceeds configured bound; no partial catalog publication')
            return body

    def json(self,path,allow_next=False):
        return json.loads(self.read('https://api.github.com'+path,2_000_000,True,allow_next))

    def download(self,url,size,path):
        self.calls += 1
        self.downloaded += size
        if self.calls > MAX_REQUESTS or self.downloaded > MAX_TRANSFER or not 0 < size <= MAX_APK:
            raise ValueError('APK transfer budget exhausted')
        if not url.startswith('https://github.com/'):
            raise ValueError('Untrusted download host')
        digest, received = hashlib.sha256(), 0
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Indi-Store'}),timeout=120) as response, open(path,'wb') as target:
            while chunk := response.read(1024*1024):
                received += len(chunk)
                if received > size:
                    raise ValueError('APK exceeds declared size')
                digest.update(chunk)
                target.write(chunk)
        if received != size:
            raise ValueError('Truncated APK')
        return digest.hexdigest()

def store_origin(value):
    value=value.strip().rstrip('/')
    https_url(value)
    parsed=urlsplit(value)
    if parsed.path or parsed.query or parsed.fragment:
        raise ValueError('STORE_ORIGIN must be a bare HTTPS origin')
    return value

def collect_inventory(github):
    repositories=[]
    seen=set()
    for owner in OWNERS:
        for page in range(1,12):
            batch=github.json(f'/users/{owner}/repos?type=owner&sort=full_name&per_page=100&page={page}',allow_next=True)
            if not isinstance(batch,list) or (page==11 and batch): raise ValueError('Repository inventory exceeds 1,000 per account')
            for repo in batch:
                name=repo['full_name']
                if repo.get('private') or repo['owner']['login'].lower()!=owner.lower() or name.lower() in seen: continue
                seen.add(name.lower())
                repositories.append({'full_name':name,'name':repo['name'],'owner':{'login':repo['owner']['login']},'description':(repo.get('description') or '')[:1000],
                    'html_url':'https://github.com/'+name,'private':False,'archived':bool(repo.get('archived')),'default_branch':repo.get('default_branch') or ''})
            if len(batch)<100: break
    return repositories

def build_catalog(snapshot, github, origin):
    origin=store_origin(origin)
    registry=snapshot['registry']
    selected=selected_repositories(registry,OWNERS)
    disabled=disabled_repositories(registry,OWNERS)
    old={app['repository'].lower():copy.deepcopy(app) for app in snapshot['catalog']['apps']}
    apps={name:app for name,app in old.items() if name in {item.lower() for item in selected}}
    for name,app in apps.items():
        app['disabled']=name in disabled
        app.pop('mediaSources',None)
        for version in app['versions']: version.pop('storageKey',None)
    for selected_name in selected:
        if selected_name.lower() in disabled: continue
        repository=github.json('/repos/'+selected_name)
        name=repository['full_name']
        if repository.get('private') or name.lower()!=selected_name.lower() or repository['owner']['login'].lower() not in {owner.lower() for owner in OWNERS}:
            raise ValueError('Only the selected owners public repositories are allowed')
        previous=old.get(name.lower())
        pin={'packageName':previous['packageName'],'signerSha256':choose_latest(previous['versions'])['signerSha256']} if previous else None
        manifests=[]
        for release in github.json('/repos/'+name+'/releases?per_page=100'):
            if release.get('draft') or release.get('prerelease'): continue
            asset=next((asset for asset in release['assets'] if asset['name']=='store-manifest.json'),None)
            if asset is None: continue
            if not 0 < asset['size'] <= 100_000 or not asset['browser_download_url'].startswith(f'https://github.com/{name}/releases/download/'):
                raise ValueError('Invalid release manifest asset')
            manifest=validate_manifest(json.loads(github.read(asset['browser_download_url'],100_000)),release['assets'],pin,name)
            pin=pin or {'packageName':manifest['packageName'],'signerSha256':manifest['signerSha256']}
            manifest.update(publishedAt=release['published_at'],releaseNotes=(release.get('body') or '')[:10_000],downloadCount=sum(a.get('download_count',0) for a in release['assets'] if a['name']==manifest['asset']))
            manifests.append(manifest)
        if not manifests:
            if previous: raise ValueError('Previously published app has no valid release manifests')
            continue
        latest=choose_latest(manifests)
        if len({m['versionCode'] for m in manifests})!=len(manifests): raise ValueError('Duplicate versionCode')
        previous_versions={v['versionCode']:v for v in previous['versions']} if previous else {}
        if previous and latest['versionCode']<max(previous_versions): raise ValueError('Version regression')
        for manifest in manifests:
            if manifest['versionCode'] in previous_versions and manifest['sha256']!=previous_versions[manifest['versionCode']]['sha256']:
                raise ValueError('A published versionCode was replaced')
        fields=('packageName','versionCode','versionName','minSdk','signerSha256','sha256','size')
        known=previous and previous['packageName']==latest['packageName'] and any(all(v.get(field)==latest[field] for field in fields if field!='packageName') for v in previous['versions'])
        if not known:
            with tempfile.TemporaryDirectory(prefix='minappstore-') as directory:
                apk=Path(directory)/'app.apk'
                if github.download(latest['githubUrl'],latest['size'],apk)!=latest['sha256']: raise ValueError('Downloaded APK hash mismatch')
                actual=inspect_apk(apk)
                if any(actual[field]!=latest[field] for field in fields): raise ValueError('Actual APK identity differs from manifest')
        app={field:latest[field] for field in ('packageName','name','summary','description','category','author','tags','iconUrl','screenshots')}
        versions=[]
        for manifest in sorted(manifests,key=lambda item:item['versionCode'],reverse=True):
            version={field:manifest[field] for field in ('versionCode','versionName','minSdk','sha256','size','githubUrl','publishedAt','releaseNotes','signerSha256')}
            version['downloadUrl']=f"{origin}/downloads/{app['packageName']}/{version['versionCode']}.apk"
            versions.append(version)
        app.update(repository=name,versions=versions,downloadCount=sum(m['downloadCount'] for m in manifests),disabled=False)
        apps[name.lower()]=app
    if len({app['packageName'] for app in apps.values()})!=len(apps): raise ValueError('Package belongs to multiple repositories')
    return {'schemaVersion':1,'updatedAt':datetime.now(timezone.utc).isoformat(),'apps':sorted(apps.values(),key=lambda app:app['packageName'])}

def api(origin,token,method='GET',payload=None):
    body=None if payload is None else json.dumps(payload,ensure_ascii=False).encode()
    if body and len(body)>2_000_000: raise ValueError('Catalog exceeds 2 MB')
    request=urllib.request.Request(origin+'/api/admin/sync',data=body,method=method,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','User-Agent':'MinAppStore-Sync/1.0'})
    try:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs): return None
        with urllib.request.build_opener(NoRedirect).open(request,timeout=60) as response:
            data=response.read(2_000_001)
            if len(data)>2_000_000: raise ValueError('Snapshot exceeds 2 MB')
            return json.loads(data)
    except urllib.error.HTTPError as error:
        raise RuntimeError('Store sync rejected with HTTP '+str(error.code)+'; no credentials were logged') from None

def main():
    origin=store_origin(os.environ['STORE_ORIGIN'])
    token=os.environ['MINAPPSTORE_ADMIN_TOKEN']
    snapshot=api(origin,token)
    github=GitHub(os.environ['GITHUB_TOKEN'])
    inventory=collect_inventory(github)
    catalog=build_catalog(snapshot,github,origin)
    result=api(origin,token,'PUT',{'catalog':catalog,'repositoryInventory':inventory,'expectedCatalogEtag':snapshot['catalogEtag'],'expectedRegistryEtag':snapshot['registryEtag']})
    if result.get('published') is not True: raise RuntimeError('Store did not confirm publication')
    print(f"Published {len(catalog['apps'])} verified apps; APK storage: public GitHub Releases")

if __name__=='__main__': main()
