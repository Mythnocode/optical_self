from collections import OrderedDict
import sys
class ResultCache:
    def __init__(self,max_entries=20,max_bytes=500*1024*1024): self.max_entries=max_entries; self.max_bytes=max_bytes; self._data=OrderedDict(); self._size=0
    def put(self,key,value):
        size=len(value) if isinstance(value,(bytes,bytearray)) else sys.getsizeof(value)
        if key in self._data: self._size-=self._data.pop(key)[1]
        while self._data and (len(self._data)>=self.max_entries or self._size+size>self.max_bytes): _,(_,s)=self._data.popitem(last=False); self._size-=s
        self._data[key]=(value,size); self._size+=size
    def get(self,key,default=None):
        if key not in self._data: return default
        value,size=self._data.pop(key); self._data[key]=(value,size); return value
    def clear(self): self._data.clear(); self._size=0
