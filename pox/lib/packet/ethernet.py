# Copyright 2011,2012,2013 James McCauley
# Copyright 2008 (C) Nicira, Inc.
#
# This file is part of POX.
#
# POX is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# POX is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with POX.  If not, see <http://www.gnu.org/licenses/>.

# This file is derived from the packet library in NOX, which was
# developed by Nicira, Inc.

#======================================================================
# Ethernet header
#
#======================================================================

import struct

from packet_base import packet_base
from packet_utils import ethtype_to_str

from pox.lib.addresses import *

ETHER_ANY            = EthAddr(b"\x00\x00\x00\x00\x00\x00")
ETHER_BROADCAST      = EthAddr(b"\xff\xff\xff\xff\xff\xff")
BRIDGE_GROUP_ADDRESS = EthAddr(b"\x01\x80\xC2\x00\x00\x00")
LLDP_MULTICAST       = EthAddr(b"\x01\x80\xc2\x00\x00\x0e")
PAE_MULTICAST        = EthAddr(b'\x01\x80\xc2\x00\x00\x03') # 802.1x Port
                                                            #  Access Entity
NDP_MULTICAST        = EthAddr(b'\x01\x23\x20\x00\x00\x01') # Nicira discovery
                                                            #  multicast

class ethernet(packet_base):
  "Ethernet packet struct"

  resolve_names = False

  MIN_LEN = 14

  IP_TYPE    = 0x0800
  ARP_TYPE   = 0x0806
  RARP_TYPE  = 0x8035
  VLAN_TYPE  = 0x8100
  LLDP_TYPE  = 0x88cc
  PAE_TYPE   = 0x888e           # 802.1x Port Access Entity
  MPLS_UNICAST_TYPE = 0x8847
  MPLS_MULTICAST_TYPE = 0x8848
  IPV6_TYPE  = 0x86dd
  PPP_TYPE   = 0x880b
  LWAPP_TYPE = 0x88bb
  GSMP_TYPE  = 0x880c
  IPX_TYPE   = 0x8137
  IPX_TYPE   = 0x8137
  WOL_TYPE   = 0x0842
  TRILL_TYPE = 0x22f3
  JUMBO_TYPE = 0x8870
  SCSI_TYPE  = 0x889a
  ATA_TYPE   = 0x88a2
  QINQ_TYPE  = 0x9100
  OOE_TYPE   = 0x0908    #shengrulee

  INVALID_TYPE = 0xffff

  type_parsers = {}

  def __init__(self, raw=None, prev=None, **kw):
    packet_base.__init__(self)

    if len(ethernet.type_parsers) == 0:
      from vlan import vlan
      ethernet.type_parsers[ethernet.VLAN_TYPE] = vlan
      from arp  import arp
      ethernet.type_parsers[ethernet.ARP_TYPE]  = arp
      ethernet.type_parsers[ethernet.RARP_TYPE] = arp
      from ipv4 import ipv4
      ethernet.type_parsers[ethernet.IP_TYPE]   = ipv4
      from lldp import lldp
      ethernet.type_parsers[ethernet.LLDP_TYPE] = lldp
      from eapol import eapol
      ethernet.type_parsers[ethernet.PAE_TYPE]  = eapol
      from mpls import mpls
      ethernet.type_parsers[ethernet.MPLS_UNICAST_TYPE] = mpls
      ethernet.type_parsers[ethernet.MPLS_MULTICAST_TYPE] = mpls
      from llc import llc
      ethernet._llc = llc
      
      from ooe import ooe    #shengrulee
      ethernet.type_parsers[ethernet.OOE_TYPE] = ooe
      
      #ethernet.type_parsers['ethernet.OOE_TYPE']

    self.prev = prev

    self.dst  = ETHER_ANY
    self.src  = ETHER_ANY

    self.type = 0
    self.next = b''

    if raw is not None:
      self.parse(raw)

    self._init(kw)

  def parse (self, raw):
    assert isinstance(raw, bytes)
    self.raw = raw
    alen = len(raw)
    if alen < ethernet.MIN_LEN:
      self.msg('warning eth packet data too short to parse header: data len %u'
               % (alen,))
      return

    self.dst = EthAddr(raw[:6])
    self.src = EthAddr(raw[6:12])
    self.type = struct.unpack('!H', raw[12:ethernet.MIN_LEN])[0]

    self.hdr_len = ethernet.MIN_LEN
    self.payload_len = alen - self.hdr_len

    self.next = ethernet.parse_next(self, self.type, raw, ethernet.MIN_LEN)
    self.parsed = True

  @staticmethod
  def parse_next (prev, typelen, raw, offset=0, allow_llc=True):
    parser = ethernet.type_parsers.get(typelen)
    if parser is not None:
      return parser(raw[offset:], prev)
    elif typelen < 1536 and allow_llc:
      return ethernet._llc(raw[offset:], prev)
    else:
      return raw[offset:]

  @staticmethod
  def getNameForType (ethertype):
    """ Returns a string name for a numeric ethertype """
    return ethtype_to_str(ethertype)

  @property
  def effective_ethertype (self):
    return self._get_effective_ethertype(self)

  @staticmethod
  def _get_effective_ethertype (self):
    """
    Get the "effective" ethertype of a packet.

    This means that if the payload is something like a VLAN or SNAP header,
    we want the type from that deeper header.  This is kind of ugly here in
    the packet library, but it should make user code somewhat simpler.
    """
    if not self.parsed:
      return ethernet.INVALID_TYPE
    if self.type == ethernet.VLAN_TYPE or type(self.payload) == ethernet._llc:
      try:
        return self.payload.effective_ethertype
      except:
        return ethernet.INVALID_TYPE
    return self.type

  def _to_str(self):
    s = ''.join(('[',str(EthAddr(self.src)),'>',str(EthAddr(self.dst)),' ',
                ethernet.getNameForType(self.type),']'))
    return s

  def hdr(self, payload):
    dst = self.dst
    src = self.src
    if type(dst) is EthAddr:
      dst = dst.toRaw()
    if type(src) is EthAddr:
      src = src.toRaw()
    return struct.pack('!6s6sH', dst, src, self.type)
