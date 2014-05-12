#copyright 2013 optical networks lab of ustc
#
#    I am the man who will be the king of the Pirates!
#=======================================================================
#
#                             OSPF header

#    0                   1                   2                   3
#    0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
#   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
#   |   Version#    |     Type      |         Packet Length         |
#   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
#   |                          Router ID                            |
#   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
#   |                           Area ID                             |
#   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
#   |          Checksum             |             AuType            |
#   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
#   |                       Authentication                          |
#   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
#   |                       Authentication                          |
#   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
#   |                                                               |
#   /                                                               /
#   /                                                               /
#   |                                                               |
#   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
#
#   Type   Description
#   ________________________________
#    1      Hello
#    2      Database Description
#    3      Link State Request
#    4      Link State Update
#    5      Link State Acknowledgment
#
#=======================================================================

import struct
from packet_utils import *
from packet_base import packet_base
from pox.lib.addresses import *

_type_to_name = {
    1   : "HELLO",
    2   : "DD",
    3   : "LSR",
    4   : "LSU",
    5   : "LSAck",
}



class ospf(packet_base):
    """
    OSFP packet struct
    """
    MIN_LEN = 20
    
    def __init__(self,raw=None, prev=None, **kw):
        packet_base.__init__(self)
        
        self.version = 2     #OSPF v2
        self.type = 0
        self.length = ospf.MIN_LEN
        self.router_id = None
        self.area_id = None
        self.csum = None
        self.au_type = None
        self.auth = None
        
        if raw is not None:
            self.parse(raw)
        
        self._init(kw)
    
    def __str__(self):
        s = "[OSPF version:%s type:%s length:%s router_id:%s area_id:%s checknum:%s Autype:%s Authentication:%s]" % \
        (self.version,self.type,self.length,self.router_id,self.area_id,self.csum,self.au_type,self.auth)
        
        return s 
    
        
    def checknum(self):
        pass
        
            
    def hdr (self, payload):
        self.csum = self.checknum()
        
        return struct.pack("!BBHLLHHQ",self.version,self.type,self.length,
                           self.router_id,self.area_id,self.csum,self.au_type,self.auth)
 
    def parse(self,raw):
        assert isinstance(raw, bytes)
        self.raw = raw
        dlen = len(raw)
        if dlen < self.MIN_LEN:
            self.msg('OSPF packet data too short to parse')
            return None
        
        (self.version,self.type,self.length,self.router_id,self.area_id,self.csum,
         self.au_type,self.auth) = struct.unpack("!BBHLLHHQ",raw[:ospf.MIN_LEN])
         
        self.parsed = True
        self.next = raw[ospf.MIN_LEN:]
    
        

        
 
#=======================================================================
#                       OSPF Hello message header
#
#    0                   1                   2                   3
#    0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
#   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
#   |                        Network Mask                           |
#   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
#   |         HelloInterval         |    Options    |    Rtr Pri    |
#   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
#   |                     RouterDeadInterval                        |
#   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
#   |                      Designated Router                        |
#   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
#   |                   Backup Designated Router                    |
#
#=======================================================================

class Hello(ospf):
    """
    OSPF HELLO message packet struct
    """
    
class DD(ospf):
    """
    OSPF Database Description message packet struct
    """
    
    
class LSR(ospf):
    """
    OSPF Link State Request message packet struct
    """
    
class LSU(ospf):
    """
    OSPF Link State Updates message packet struct
    """
    
class LSA(ospf):
    """
    OSPF Link State Ack message packet struct
    """
    

    
    
        
