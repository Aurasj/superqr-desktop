"""Bounded-memory next-generation V7 modem sender, independent of physical PHY."""
from __future__ import annotations
from dataclasses import dataclass
import secrets
from typing import Iterator
from .modem import DEFAULT_GENERATION_TARGET_BYTES,DEFAULT_PARITY_RATIO,GenerationPlan,build_modem_packet,encode_fountain_symbol,inner_fec_encode,plan_generations,symbol_payload_capacity
from .package_stream import PreparedPackageSource
@dataclass(frozen=True)
class ModemSenderSnapshot:
    session_id:int;channel_bytes:int;parity_ratio:float;symbol_bytes:int;total_generations:int;generation_id:int;symbol_id:int;source_count:int;systematic_frames:int;repair_frames:int;emitted_frames:int;package_bytes:int;generation_bytes_resident:int
class V7ModemSender:
    """Streams one prepared package through one bounded generation at a time.

    This object deliberately owns no display timing. The presentation backend asks
    for exact-size channel frames when it is ready to present them.
    """
    def __init__(self,source:PreparedPackageSource,*,channel_bytes:int,parity_ratio:float=DEFAULT_PARITY_RATIO,target_generation_bytes:int=DEFAULT_GENERATION_TARGET_BYTES,session_id:int|None=None,initial_repair_fraction:float=.20):
        if not 0<=initial_repair_fraction<=2:raise ValueError("initial_repair_fraction outside 0..2")
        self.source=source;self.channel_bytes=channel_bytes;self.parity_ratio=parity_ratio;self.symbol_bytes=symbol_payload_capacity(channel_bytes,parity_ratio);self.plans=plan_generations(source.size,self.symbol_bytes,target_generation_bytes);self.session_id=session_id or (secrets.randbits(32) or 1);self.initial_repair_fraction=initial_repair_fraction
        self._generation_index=0;self._symbols:tuple[bytes,...]=();self._symbol_id=0;self._systematic=0;self._repair=0;self._emitted=0;self._load_generation(0)
    @property
    def plan(self)->GenerationPlan:return self.plans[self._generation_index]
    def _load_generation(self,index:int)->None:
        p=self.plans[index];payload=self.source.read_at(p.offset,p.payload_len)
        if len(payload)!=p.payload_len:raise IOError("package generation read was short")
        symbols=[]
        for i in range(p.source_count):
            chunk=payload[i*p.symbol_bytes:(i+1)*p.symbol_bytes];symbols.append(chunk+bytes(p.symbol_bytes-len(chunk)))
        self._generation_index=index;self._symbols=tuple(symbols);self._symbol_id=0
    def physical_frame(self,generation_id:int,symbol_id:int)->bytes:
        if not 0<=generation_id<len(self.plans):raise IndexError("generation outside transfer")
        if generation_id!=self._generation_index:self._load_generation(generation_id)
        p=self.plan;payload=encode_fountain_symbol(self._symbols,self.session_id,p.generation_id,symbol_id);packet=build_modem_packet(session_id=self.session_id,generation_id=p.generation_id,total_generations=len(self.plans),symbol_id=symbol_id,source_count=p.source_count,generation_payload_len=p.payload_len,payload=payload);return inner_fec_encode(packet,self.channel_bytes,self.parity_ratio)
    def next_physical_frame(self)->bytes:
        p=self.plan;sid=self._symbol_id;frame=self.physical_frame(p.generation_id,sid);self._emitted+=1
        if sid<p.source_count:self._systematic+=1
        else:self._repair+=1
        self._symbol_id+=1;initial_count=p.source_count+max(8,int(p.source_count*self.initial_repair_fraction+.999))
        if self._symbol_id>=initial_count and self._generation_index+1<len(self.plans):self._load_generation(self._generation_index+1)
        return frame
    def repair_frame(self,generation_id:int,repair_ordinal:int)->bytes:
        p=self.plans[generation_id]
        if repair_ordinal<0:raise ValueError("repair ordinal must be non-negative")
        return self.physical_frame(generation_id,p.source_count+repair_ordinal)
    def initial_pass(self)->Iterator[bytes]:
        for gid,p in enumerate(self.plans):
            count=p.source_count+max(8,int(p.source_count*self.initial_repair_fraction+.999))
            for sid in range(count):yield self.physical_frame(gid,sid)
    def snapshot(self)->ModemSenderSnapshot:
        p=self.plan;return ModemSenderSnapshot(self.session_id,self.channel_bytes,self.parity_ratio,self.symbol_bytes,len(self.plans),p.generation_id,self._symbol_id,p.source_count,self._systematic,self._repair,self._emitted,self.source.size,sum(map(len,self._symbols)))
    def close(self)->None:self.source.close()
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
