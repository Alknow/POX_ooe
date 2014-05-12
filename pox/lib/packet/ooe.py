import struct

from packet_base import packet_base
from ethernet import ethernet

from packet_utils import *



class ooe(packet_base):
    #ooe Header
    MIN_LEN = 20
    
    def __init__(self, raw=None, prev=None, **kw):
        packet_base.__init__(self)

        self.prev = prev

        self.next = b''
        self.ooe_dst = 0
        self.ooe_start = 0
        self.ooe_length = 0
        self.ooe_bit_rate = 0
        self.ooe_timeout = 0
        
        if raw is not None:
            self.parse(raw)
        
        self._init(kw)
        
    def __str__(self):
        s = "[OOE ooe_dst:%S ooe_start:%s ooe_length:%s ooe_bit_rate:%s idle_ooe_timeout:%s]" % (self.ooe_dst, self.ooe_start, self.ooe_length, self.ooe_bit_rate, self.ooe_timeout)
        return s
    
    
    def parse(self, raw):
        assert isinstance(raw, bytes)
        self.raw = raw
        dlen = len(raw)
        if dlen < ooe.MIN_LEN:
            self.msg('(ooe parse) warning ooe packet data too short to '
                     + 'parse header: data len %u' % (dlen,))
            return

        (self.ooe_dst,self.ooe_start,self.ooe_length,self.ooe_bit_rate,self.ooe_timeout) = struct.unpack("!LLLLL", raw[:ooe.MIN_LEN])
        self.parsed = True
        self.next = raw[ooe.MIN_LEN:]
        
    def hdr(self,payload):
        ooe_dst=self.ooe_dst
        ooe_start=self.ooe_start
        ooe_length=self.ooe_length
        ooe_bit_rate=self.ooe_bit_rate
        ooe_timeout=self.ooe_timeout
        buf = struct.pack('!LLLLL', ooe_dst, ooe_start, ooe_length, ooe_bit_rate,ooe_timeout)
        return buf
    
        
        
        
        