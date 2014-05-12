from pox.core import core
import pox.openflow.libopenflow_01 as of
from pox.lib.util import dpid_to_str
from pox.lib.packet.ipv4 import ipv4
from pox.lib.addresses import IPAddr, EthAddr
from pox.lib.packet.ooe import ooe
from pox.lib.packet.ethernet import ethernet
import pox.lib.packet as pkt
from pox.lib.revent import *

log = core.getLogger()

def _handle_ConnectionUp (event):
        msg=of.ofp_flow_mod()
        msg.command=of.OFPFC_ADD
        msg.idle_timeout= 10000
        msg.hard_timeout= of.OFP_FLOW_PERMANENT
        msg.priority = 42
        msg.flags = 1<<3
        msg.match.dl_type = 0x0908
        #msg.match.nw_src = IPAddr('172.16.0.8')
        #msg.match.in_port = 2
        msg.match.ooe_dst = 1
        #msg.match.ooe_start = 2
        #msg.match.ooe_length = 3
        msg.actions.append(of.ofp_action_nw_addr.set_dst(IPAddr('192.168.102.203')))
        #msg.actions.append(of.ofp_action_dl_addr.set_dst(EthAddr("01:02:03:04:05:06")))
        msg.actions.append(of.ofp_action_ooe.set_dst('5'))
        msg.actions.append(of.ofp_action_ooe.set_start('6'))
        msg.actions.append(of.ofp_action_ooe.set_length('7'))
        
        #msg.actions.append(of.ofp_action_nw_addr.set_src(IPAddr('192.168.102.202')))
        msg.actions.append(of.ofp_action_output(port=2))
        event.connection.send(msg)

def launch ():
  core.openflow.addListenerByName("ConnectionUp", _handle_ConnectionUp)
