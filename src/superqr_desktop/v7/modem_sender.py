"""Bounded-memory next-generation V7 modem sender, independent of physical PHY."""
from __future__ import annotations
from dataclasses import dataclass
import secrets
from typing import Iterator
from .modem import DEFAULT_GENERATION_TARGET_BYTES,DEFAULT_PARITY_RATIO,GenerationLayout,GenerationPlan,build_modem_packet,coefficient_words,generation_layout,inner_fec_encode,symbol_payload_capacity
from .package_stream import PreparedPackageSource
MAX_PRODUCT_GENERATIONS=16_000_000
@dataclass(frozen=True)
class ModemSenderSnapshot:
    session_id:int;channel_bytes:int;parity_ratio:float;symbol_bytes:int;total_generations:int;schedule_phase:str;next_generation_id:int;next_symbol_id:int;last_generation_id:int|None;last_symbol_id:int|None;systematic_frames:int;repair_frames:int;emitted_frames:int;package_bytes:int;generation_bytes_resident:int
class V7ModemSender:
    """Streams one prepared package through one bounded generation at a time.

    Transfer metadata is O(1) in file size: generation plans are derived on demand
    from DENSE_XOR_V1's deterministic layout, and repair ids are derived from a
    sweep epoch instead of storing one counter per generation.

    The first pass is systematic plus bounded repair overhead for every generation.
    If presentation continues without receiver feedback, repair symbols then sweep
    all generations round-robin forever with monotonically increasing per-generation
    ids. No exact optical frame is required and no old repair symbol is replayed.
    This object deliberately owns no display timing.
    """
    def __init__(self,source:PreparedPackageSource,*,channel_bytes:int,parity_ratio:float=DEFAULT_PARITY_RATIO,target_generation_bytes:int=DEFAULT_GENERATION_TARGET_BYTES,session_id:int|None=None,initial_repair_fraction:float=.20):
        if not 0<=initial_repair_fraction<=2:raise ValueError("initial_repair_fraction outside 0..2")
        if target_generation_bytes!=DEFAULT_GENERATION_TARGET_BYTES:raise ValueError("DENSE_XOR_V1 generation target is fixed at 128 KiB")
        self.source=source;self.channel_bytes=channel_bytes;self.parity_ratio=parity_ratio;self.symbol_bytes=symbol_payload_capacity(channel_bytes,parity_ratio);self.layout:GenerationLayout=generation_layout(source.size,self.symbol_bytes,target_generation_bytes)
        if self.layout.total_generations>MAX_PRODUCT_GENERATIONS:raise ValueError("package exceeds the shared Android/Desktop generation safety limit")
        self.session_id=session_id or (secrets.randbits(32) or 1);self.initial_repair_fraction=initial_repair_fraction
        self._loaded_generation=-1;self._symbols:tuple[bytes,...]=();self._symbol_ints:tuple[int,...]=();self._schedule_generation=0;self._schedule_symbol=0;self._initial_done=False;self._repair_cursor=0;self._repair_epoch=0;self._systematic=0;self._repair=0;self._emitted=0;self._last_address:tuple[int,int]|None=None;self._load_generation(0)
    @property
    def total_generations(self)->int:return self.layout.total_generations
    def plan(self,generation_id:int)->GenerationPlan:return self.layout.plan(generation_id)
    def _initial_symbol_count(self,plan:GenerationPlan)->int:return plan.source_count+max(8,int(plan.source_count*self.initial_repair_fraction+.999))
    def _load_generation(self,index:int)->None:
        if index==self._loaded_generation:return
        if self.source.stored_path==self.source.source_path:self.source.assert_source_unchanged()
        p=self.plan(index);payload=self.source.read_at(p.offset,p.payload_len)
        if len(payload)!=p.payload_len:raise IOError("package generation read was short")
        symbols=[]
        for i in range(p.source_count):
            chunk=payload[i*p.symbol_bytes:(i+1)*p.symbol_bytes];symbols.append(chunk+bytes(p.symbol_bytes-len(chunk)))
        self._loaded_generation=index;self._symbols=tuple(symbols);self._symbol_ints=tuple(int.from_bytes(symbol,"little") for symbol in self._symbols)
    def _encode_symbol(self,generation_id:int,symbol_id:int)->bytes:
        self._load_generation(generation_id);p=self.plan(generation_id)
        if symbol_id<p.source_count:return self._symbols[symbol_id]
        value=0
        for word_index,word in enumerate(coefficient_words(self.session_id,p.generation_id,symbol_id,p.source_count)):
            while word:
                low=word&-word;source_index=word_index*64+low.bit_length()-1;value^=self._symbol_ints[source_index];word^=low
        return value.to_bytes(p.symbol_bytes,"little")
    def physical_frame(self,generation_id:int,symbol_id:int)->bytes:
        p=self.plan(generation_id);payload=self._encode_symbol(generation_id,symbol_id);packet=build_modem_packet(session_id=self.session_id,generation_id=p.generation_id,total_generations=self.total_generations,symbol_id=symbol_id,source_count=p.source_count,generation_payload_len=p.payload_len,payload=payload);return inner_fec_encode(packet,self.channel_bytes,self.parity_ratio)
    def _take_next_address(self)->tuple[int,int]:
        if not self._initial_done:
            gid=self._schedule_generation;sid=self._schedule_symbol;p=self.plan(gid);self._schedule_symbol+=1
            if self._schedule_symbol>=self._initial_symbol_count(p):
                if gid+1<self.total_generations:self._schedule_generation+=1;self._schedule_symbol=0
                else:self._initial_done=True;self._repair_cursor=0;self._repair_epoch=0
            return gid,sid
        gid=self._repair_cursor;p=self.plan(gid);sid=self._initial_symbol_count(p)+self._repair_epoch;self._repair_cursor+=1
        if self._repair_cursor>=self.total_generations:self._repair_cursor=0;self._repair_epoch+=1
        return gid,sid
    def next_addressed_frame(self)->tuple[int,int,bytes]:
        gid,sid=self._take_next_address();frame=self.physical_frame(gid,sid);p=self.plan(gid);self._emitted+=1
        if sid<p.source_count:self._systematic+=1
        else:self._repair+=1
        self._last_address=(gid,sid);return gid,sid,frame
    def next_physical_frame(self)->bytes:return self.next_addressed_frame()[2]
    def repair_frame(self,generation_id:int,repair_ordinal:int)->bytes:
        p=self.plan(generation_id)
        if repair_ordinal<0:raise ValueError("repair ordinal must be non-negative")
        return self.physical_frame(generation_id,p.source_count+repair_ordinal)
    def initial_pass(self)->Iterator[bytes]:
        for gid in range(self.total_generations):
            p=self.plan(gid)
            for sid in range(self._initial_symbol_count(p)):yield self.physical_frame(gid,sid)
    def snapshot(self)->ModemSenderSnapshot:
        if self._initial_done:next_gid=self._repair_cursor;next_sid=self._initial_symbol_count(self.plan(next_gid))+self._repair_epoch;phase="REPAIR_SWEEP"
        else:next_gid=self._schedule_generation;next_sid=self._schedule_symbol;phase="INITIAL"
        last_gid,last_sid=self._last_address if self._last_address is not None else (None,None)
        return ModemSenderSnapshot(self.session_id,self.channel_bytes,self.parity_ratio,self.symbol_bytes,self.total_generations,phase,next_gid,next_sid,last_gid,last_sid,self._systematic,self._repair,self._emitted,self.source.size,sum(map(len,self._symbols)))
    def close(self)->None:self.source.close()
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
