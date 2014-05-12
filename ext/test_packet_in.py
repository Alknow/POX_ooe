from pox.core import core
import pox.openflow.libopenflow_01 as of
from pox.lib.util import dpid_to_str
from pox.lib.packet.ipv4 import ipv4
from pox.lib.addresses import IPAddr, EthAddr
from pox.lib.packet.ooe import ooe
from pox.lib.packet.ethernet import ethernet

from pox.lib.revent import *

log = core.getLogger()

def _handle_PacketIn(event):
    packet=event.parsed
    match = of.ofp_match.from_packet(packet)
    print "%04x" % (match.dl_type)
    if match.dl_type == 0x0908:
        print match.ooe_dst
        print match.ooe_length
        print match.ooe_start
def launch ():
  core.openflow.addListenerByName("PacketIn", _handle_PacketIn)
  
