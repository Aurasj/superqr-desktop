"""Bounded-memory package preparation for the V7 Phase 2 modem sender."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib,mimetypes,os,struct,tempfile,zlib
from pathlib import Path
PACKAGE_MAGIC=b"S7PK";PACKAGE_VERSION=1;PACKAGE_HEADER=struct.Struct(">4sBBHHHQQ32sI");PACKAGE_HEADER_SIZE=64
COMPRESSION_NONE=0;COMPRESSION_DEFLATE_RAW=1;MAX_FILENAME_BYTES=1024;MAX_MIME_BYTES=255
READ_CHUNK=1024*1024;SAMPLE_BYTES=256*1024;MIN_COMPRESSION_SAVINGS=4096;MIN_COMPRESSION_SAVINGS_RATIO=.02
class PackageSourceError(ValueError):pass
@dataclass(frozen=True)
class PackageSourceInfo:
    filename:str;mime_type:str;compression_id:int;original_size:int;stored_size:int;original_sha256:str;package_size:int;source_path:str;stored_path:str
class PreparedPackageSource:
    """Persistent random-access `S7PK` source without whole-file RAM buffering."""
    def __init__(self,*,source_path:str,stored_path:str,owns_stored_path:bool,prefix:bytes,info:PackageSourceInfo,original_stat:tuple[int,int]):
        self.source_path=source_path;self.stored_path=stored_path;self._owns=owns_stored_path;self.prefix=prefix;self.info=info;self._original_stat=original_stat;self._handle=open(stored_path,'rb');self._closed=False
    @classmethod
    def prepare(cls,path:str,*,allow_compression:bool=True)->"PreparedPackageSource":
        source=Path(path)
        if not source.is_file():raise PackageSourceError("selected file does not exist")
        stat=source.stat();original_stat=(stat.st_size,stat.st_mtime_ns);filename=source.name;name_b=filename.encode();mime=mimetypes.guess_type(filename)[0] or 'application/octet-stream';mime_b=mime.encode()
        if not 1<=len(name_b)<=MAX_FILENAME_BYTES:raise PackageSourceError("filename UTF-8 length outside 1..1024")
        if len(mime_b)>MAX_MIME_BYTES:raise PackageSourceError("MIME UTF-8 length exceeds 255")
        sha=hashlib.sha256();original_size=stat.st_size;candidate=allow_compression and original_size>=1024 and _sample_suggests_compression(source,original_size);temp_path=None;compression_id=COMPRESSION_NONE;stored_size=original_size
        try:
            if candidate:
                temp=tempfile.NamedTemporaryFile(prefix='superqr-v7-',suffix='.deflate',delete=False);temp_path=temp.name;compressor=zlib.compressobj(level=1,wbits=-15);stored_size=0
                with source.open('rb') as src,temp:
                    while chunk:=src.read(READ_CHUNK):
                        sha.update(chunk);encoded=compressor.compress(chunk)
                        if encoded:temp.write(encoded);stored_size+=len(encoded)
                    tail=compressor.flush();temp.write(tail);stored_size+=len(tail)
                savings=original_size-stored_size;required=max(MIN_COMPRESSION_SAVINGS,int(original_size*MIN_COMPRESSION_SAVINGS_RATIO))
                if savings>=required:compression_id=COMPRESSION_DEFLATE_RAW;stored_path=temp_path
                else:os.unlink(temp_path);temp_path=None;stored_path=str(source);stored_size=original_size
            else:
                with source.open('rb') as src:
                    while chunk:=src.read(READ_CHUNK):sha.update(chunk)
                stored_path=str(source)
            digest=sha.digest();now=source.stat()
            if (now.st_size,now.st_mtime_ns)!=original_stat:raise PackageSourceError("source file changed during preparation")
            zero=PACKAGE_HEADER.pack(PACKAGE_MAGIC,PACKAGE_VERSION,compression_id,0,len(name_b),len(mime_b),original_size,stored_size,digest,0);crc=zlib.crc32(mime_b,zlib.crc32(name_b,zlib.crc32(zero[:60])))&0xffffffff
            header=PACKAGE_HEADER.pack(PACKAGE_MAGIC,PACKAGE_VERSION,compression_id,0,len(name_b),len(mime_b),original_size,stored_size,digest,crc);prefix=header+name_b+mime_b;info=PackageSourceInfo(filename,mime,compression_id,original_size,stored_size,digest.hex().upper(),len(prefix)+stored_size,str(source),stored_path)
            return cls(source_path=str(source),stored_path=stored_path,owns_stored_path=temp_path is not None,prefix=prefix,info=info,original_stat=original_stat)
        except Exception:
            if temp_path and os.path.exists(temp_path):os.unlink(temp_path)
            raise
    @property
    def size(self)->int:return self.info.package_size
    def read_at(self,offset:int,length:int)->bytes:
        if self._closed:raise RuntimeError("package source is closed")
        if offset<0 or length<0:raise ValueError("offset/length must be non-negative")
        if offset>=self.size or length==0:return b''
        end=min(self.size,offset+length);out=bytearray();prefix_len=len(self.prefix)
        if offset<prefix_len:
            stop=min(end,prefix_len);out+=self.prefix[offset:stop];offset=stop
        if offset<end:
            self._handle.seek(offset-prefix_len);chunk=self._handle.read(end-offset)
            if len(chunk)!=end-offset:raise IOError("prepared package backing store changed or became unreadable")
            out+=chunk
        return bytes(out)
    def assert_source_unchanged(self)->None:
        stat=os.stat(self.source_path)
        if (stat.st_size,stat.st_mtime_ns)!=self._original_stat:raise PackageSourceError("source file changed after preparation")
    def close(self)->None:
        if self._closed:return
        self._closed=True;self._handle.close()
        if self._owns:
            try:os.unlink(self.stored_path)
            except FileNotFoundError:pass
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
def _sample_suggests_compression(path:Path,size:int)->bool:
    positions={0,max(0,size//2-SAMPLE_BYTES//2),max(0,size-SAMPLE_BYTES)};sample=bytearray()
    with path.open('rb') as fh:
        for pos in sorted(positions):fh.seek(pos);sample+=fh.read(min(SAMPLE_BYTES,size-pos))
    if not sample:return False
    c=zlib.compressobj(level=1,wbits=-15);compressed=c.compress(bytes(sample))+c.flush();return len(compressed)+128<len(sample)*.97
