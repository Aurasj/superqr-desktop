"""PHY-agnostic SuperQR V7 Phase 2 modem encoder primitives.

Canonical semantics live in superqr-protocol/contracts/v7_modem_contract.json.
This module intentionally contains no grid/color/QR assumptions.
"""
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
import math, struct, zlib
from typing import Sequence
PACKET_MAGIC=b"SQM7"; PACKET_VERSION=1; OUTER_CODEC_DENSE_XOR=1; INNER_CODEC_RS255=1; FLAG_SYSTEMATIC=1
PACKET_HEADER=struct.Struct(">4sBBBBIIIIHHI"); PACKET_HEADER_SIZE=PACKET_HEADER.size; PACKET_OVERHEAD=PACKET_HEADER_SIZE+4
DEFAULT_PARITY_RATIO=.15; DEFAULT_GENERATION_TARGET_BYTES=128*1024; MAX_SOURCE_SYMBOLS=256; MASK64=(1<<64)-1
class V7ModemError(ValueError): pass
@dataclass(frozen=True)
class InnerFecPlan:
    channel_bytes:int; parity_bytes:int; data_bytes:int; blocks:tuple[tuple[int,int],...]; interleave_stride:int
@dataclass(frozen=True)
class GenerationPlan:
    generation_id:int; offset:int; payload_len:int; source_count:int; symbol_bytes:int

def _splitmix64_next(state:int)->tuple[int,int]:
    state=(state+0x9E3779B97F4A7C15)&MASK64; z=state; z=((z^(z>>30))*0xBF58476D1CE4E5B9)&MASK64; z=((z^(z>>27))*0x94D049BB133111EB)&MASK64; return state,(z^(z>>31))&MASK64

def coefficient_words(session_id:int,generation_id:int,symbol_id:int,source_count:int)->tuple[int,...]:
    if not 1<=source_count<=MAX_SOURCE_SYMBOLS: raise V7ModemError("source_count must be 1..256")
    if min(session_id,generation_id,symbol_id)<0: raise V7ModemError("ids must be non-negative")
    count=(source_count+63)//64
    if symbol_id<source_count:
        words=[0]*count; words[symbol_id>>6]=1<<(symbol_id&63); return tuple(words)
    state=(0x53514D3700000000^((session_id&0xffffffff)<<16)^(generation_id&0xffffffff)^((symbol_id&0xffffffff)*0xD6E8FEB86659FD93))&MASK64; words=[]
    for _ in range(count): state,value=_splitmix64_next(state); words.append(value)
    last_bits=source_count-(count-1)*64
    if last_bits<64: words[-1]&=(1<<last_bits)-1
    if sum(w.bit_count() for w in words)<2 and source_count>1:
        for bit in ((symbol_id-source_count)%source_count,(symbol_id-source_count+source_count//2+1)%source_count): words[bit>>6]|=1<<(bit&63)
    elif source_count==1: words[0]=1
    return tuple(words)

def encode_fountain_symbol(source_symbols:Sequence[bytes],session_id:int,generation_id:int,symbol_id:int)->bytes:
    if not source_symbols: raise V7ModemError("empty generation")
    size=len(source_symbols[0])
    if size<1 or any(len(x)!=size for x in source_symbols): raise V7ModemError("source symbols must have one fixed size")
    # Big-int XOR executes the byte-wide combination in C instead of a Python
    # byte loop. This helper is primarily reference/test-facing; V7ModemSender
    # caches the converted source integers once per resident generation.
    value=0
    for word_index,word in enumerate(coefficient_words(session_id,generation_id,symbol_id,len(source_symbols))):
        while word:
            low=word&-word; value^=int.from_bytes(source_symbols[word_index*64+low.bit_length()-1],"little"); word^=low
    return value.to_bytes(size,"little")

def build_modem_packet(*,session_id:int,generation_id:int,total_generations:int,symbol_id:int,source_count:int,generation_payload_len:int,payload:bytes)->bytes:
    if not 1<=session_id<=0xffffffff: raise V7ModemError("invalid session id")
    if not 0<=generation_id<total_generations<=0xffffffff: raise V7ModemError("invalid generation numbering")
    if not 0<=symbol_id<=0xffffffff or not 1<=source_count<=256 or not 1<=len(payload)<=0xffff: raise V7ModemError("invalid modem packet field")
    if not 0<generation_payload_len<=source_count*len(payload): raise V7ModemError("invalid generation payload length")
    flags=FLAG_SYSTEMATIC if symbol_id<source_count else 0
    header=PACKET_HEADER.pack(PACKET_MAGIC,PACKET_VERSION,flags,OUTER_CODEC_DENSE_XOR,INNER_CODEC_RS255,session_id,generation_id,total_generations,symbol_id,source_count,len(payload),generation_payload_len)
    crc=zlib.crc32(payload,zlib.crc32(header))&0xffffffff; return header+payload+struct.pack(">I",crc)

_GF_EXP=[0]*512; _GF_LOG=[0]*256; _x=1
for _i in range(255):
    _GF_EXP[_i]=_x; _GF_LOG[_x]=_i; _x<<=1
    if _x&0x100:_x^=0x11D
for _i in range(255,512):_GF_EXP[_i]=_GF_EXP[_i-255]
def _gf_mul(a:int,b:int)->int:return 0 if a==0 or b==0 else _GF_EXP[_GF_LOG[a]+_GF_LOG[b]]
def _poly_mul(a:Sequence[int],b:Sequence[int])->list[int]:
    out=[0]*(len(a)+len(b)-1)
    for i,x in enumerate(a):
        if x:
            for j,y in enumerate(b):
                if y:out[i+j]^=_gf_mul(x,y)
    return out
@lru_cache(maxsize=64)
def _generator(parity:int)->tuple[int,...]:
    g=[1]
    for i in range(parity):g=_poly_mul(g,[1,_GF_EXP[i]])
    return tuple(g)
@lru_cache(maxsize=64)
def _generator_mul_tables(parity:int)->tuple[bytes,...]:
    # One 256-byte lookup table per non-leading generator coefficient. Typical
    # balanced Phase-2 blocks use only ~30-40 parity bytes, so the cache is tiny.
    return tuple(bytes(_gf_mul(coefficient,value) for value in range(256)) for coefficient in _generator(parity)[1:])
def rs_encode(message:bytes,parity:int)->bytes:
    if not 1<=parity<255 or not 1<=len(message)<=255-parity: raise V7ModemError("invalid shortened RS block")
    tables=_generator_mul_tables(parity);work=bytearray(message);work.extend(bytes(parity))
    for i in range(len(message)):
        coefficient=work[i]
        if coefficient:
            for offset,table in enumerate(tables,1):work[i+offset]^=table[coefficient]
    return message+bytes(work[-parity:])
def balanced_rs_blocks(channel_bytes:int,parity_bytes:int)->tuple[tuple[int,int],...]:
    blocks=(channel_bytes+254)//255
    if not blocks<=parity_bytes<=channel_bytes-blocks:raise V7ModemError("invalid RS parity budget")
    lb,le=divmod(channel_bytes,blocks);pb,pe=divmod(parity_bytes,blocks); result=tuple((lb+(1 if i<le else 0),pb+(1 if i<pe else 0)) for i in range(blocks))
    if any(p<1 or p>=n for n,p in result):raise V7ModemError("invalid balanced RS block")
    return result
def parity_bytes_for_ratio(channel_bytes:int,ratio:float)->int:
    if not 0<ratio<1:raise V7ModemError("parity ratio must be between 0 and 1")
    blocks=(channel_bytes+254)//255;return min(channel_bytes-blocks,max(blocks,math.ceil(channel_bytes*ratio)))
def interleave_stride(channel_bytes:int)->int:
    stride=channel_bytes//2+1
    while math.gcd(stride,channel_bytes)!=1:stride+=1
    return stride
@lru_cache(maxsize=64)
def inner_fec_plan(channel_bytes:int,ratio:float=DEFAULT_PARITY_RATIO)->InnerFecPlan:
    parity=parity_bytes_for_ratio(channel_bytes,ratio);return InnerFecPlan(channel_bytes,parity,channel_bytes-parity,balanced_rs_blocks(channel_bytes,parity),interleave_stride(channel_bytes))
@lru_cache(maxsize=64)
def _interleave_map(channel_bytes:int,stride:int)->tuple[int,...]:return tuple((i*stride)%channel_bytes for i in range(channel_bytes))
def symbol_payload_capacity(channel_bytes:int,ratio:float=DEFAULT_PARITY_RATIO)->int:
    value=inner_fec_plan(channel_bytes,ratio).data_bytes-PACKET_OVERHEAD
    if value<1:raise V7ModemError("channel frame cannot hold a modem symbol")
    return value
def inner_fec_encode(packet:bytes,channel_bytes:int,ratio:float=DEFAULT_PARITY_RATIO)->bytes:
    plan=inner_fec_plan(channel_bytes,ratio)
    if len(packet)>plan.data_bytes:raise V7ModemError("packet exceeds channel data capacity")
    padded=packet+bytes(plan.data_bytes-len(packet));offset=0;raw=bytearray(channel_bytes);code_offset=0
    for n,parity in plan.blocks:
        data_len=n-parity;encoded=rs_encode(padded[offset:offset+data_len],parity);raw[code_offset:code_offset+n]=encoded;offset+=data_len;code_offset+=n
    if offset!=plan.data_bytes or code_offset!=channel_bytes:raise AssertionError("RS accounting error")
    out=bytearray(channel_bytes)
    for logical,physical in enumerate(_interleave_map(channel_bytes,plan.interleave_stride)):out[physical]=raw[logical]
    return bytes(out)
def plan_generations(stream_size:int,symbol_bytes:int,target_generation_bytes:int=DEFAULT_GENERATION_TARGET_BYTES)->tuple[GenerationPlan,...]:
    if stream_size<1 or symbol_bytes<1 or target_generation_bytes<1:raise V7ModemError("invalid generation planning input")
    target_count=min(MAX_SOURCE_SYMBOLS,max(1,(target_generation_bytes+symbol_bytes-1)//symbol_bytes));capacity=target_count*symbol_bytes;plans=[];offset=0;gid=0
    while offset<stream_size:
        length=min(capacity,stream_size-offset);count=(length+symbol_bytes-1)//symbol_bytes;plans.append(GenerationPlan(gid,offset,length,count,symbol_bytes));offset+=length;gid+=1
    return tuple(plans)
