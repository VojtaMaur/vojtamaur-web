"""Host-only response bindings. No secrets in checkpoints, prompts or reports.

Windows uses DPAPI for the current user. POSIX uses owner-only files; this is
not an OS sandbox against other processes running as the same user.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
from .workspace import _confined

def _dpapi(data, decrypt=False):
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_ubyte))]
    buf=(ctypes.c_ubyte*len(data)).from_buffer_copy(data)
    source=Blob(len(data),buf); target=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    fn=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    fn.restype=wintypes.BOOL
    if not fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):
        raise OSError('Private flow response encryption unavailable')
    try: return ctypes.string_at(target.pbData,target.cbData)
    finally:
        free=ctypes.WinDLL('kernel32').LocalFree
        free.argtypes=[ctypes.c_void_p]; free.restype=ctypes.c_void_p
        free(target.pbData)

def save(run_dir, ident, value):
    raw=json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
    filename=hashlib.sha256(ident.encode()).hexdigest()+'.bin'
    root=Path(run_dir)/'private-flow'
    _confined(Path(run_dir),'private-flow/'+filename)
    root.mkdir(mode=0o700,exist_ok=True)
    if os.name!='nt': os.chmod(root,0o700)
    path=root/filename; temp=root/(filename+'.tmp')
    _confined(Path(run_dir),'private-flow/'+filename+'.tmp')
    blob=b'DPAPI\0'+_dpapi(raw) if os.name=='nt' else b'OWNER\0'+raw
    fd=os.open(temp,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(blob);stream.flush();os.fsync(stream.fileno())
    os.replace(temp,path)
    return {'file':filename,'sha256':hashlib.sha256(raw).hexdigest(),'protection':'DPAPI' if os.name=='nt' else 'owner-only'}

def load(run_dir, receipt):
    path=_confined(Path(run_dir),'private-flow/'+receipt['file'])
    blob=path.read_bytes()
    if blob.startswith(b'DPAPI\0') and os.name=='nt': raw=_dpapi(blob[6:],True)
    elif blob.startswith(b'OWNER\0') and os.name!='nt': raw=blob[6:]
    else: raise ValueError('Private flow response needs its original host/user')
    if hashlib.sha256(raw).hexdigest()!=receipt['sha256']:
        raise ValueError('Private flow response hash changed')
    return json.loads(raw)
