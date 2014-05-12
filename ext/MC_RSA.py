
from pox.core import core
import pox.openflow.libopenflow_01 as of
from pox.lib.revent import *
from pox.lib.recoco import Timer
#from pox.openflow.discovery import Discovery
from pox.lib.util import dpid_to_str
from pox.lib.addresses import EthAddr
from pox.lib.packet.ooe import ooe

import time
import math
from collections import defaultdict
import random


log = core.getLogger()

#the dict of id -> dpid
dict_id2dpid = {1:0x0000f80f41f42a1a,
                2:0x000090e2ba0abc70,
                3:0x000090e2ba0ab8e1,
                4:0x000090e2ba0ab392,
                5:0x000090e2ba0abc71,
                6:0x000090e2ba0ab390,
                }
#the dict of dpid -> id
dict_dpid2id = {v:k for k,v in dict_id2dpid.items()} #reverse

SW_SUM = 6
SW = [x+1 for x in range(SW_SUM)]

# Adjacency map.  [sw1][sw2] -> port from sw1 to sw2
adjacency = defaultdict(lambda:defaultdict(lambda:None))

adjacency[1][2] = (1,0,300)
adjacency[2][1] = (3,8,300)
adjacency[1][6] = (2,1,700)
adjacency[6][1] = (1,9,700)
adjacency[2][3] = (4,3,1000)
adjacency[3][2] = (1,11,1000)
adjacency[2][6] = (5,2,500)
adjacency[6][2] = (3,10,500)
adjacency[6][5] = (2,4,750)
adjacency[5][6] = (2,12,750)
adjacency[3][5] = (2,5,400)
adjacency[5][3] = (1,13,400)
adjacency[3][4] = (3,6,600)
adjacency[4][3] = (1,14,600)
adjacency[5][4] = (3,15,200)
adjacency[4][5] = (2,7,200)

LINK_SUM = sum([len(adjacency[x]) for x in SW]) #the total number of list

SLOT_SUM = 358
slotspace = 12.5  # granularity (i.e., the bandwidth of a subcarrier , in terms of GHz)


slot_map = [[1 for x in range(SLOT_SUM)] for y in range(LINK_SUM)]

# Switches we know of.  [dpid] -> Switch
switches = {}

# [sw1][sw2] -> (distance, intermediate)
path_map = defaultdict(lambda:defaultdict(lambda:(None,None)))

# Waiting path.  (dpid,xid)->WaitingPath
waiting_paths = {}

dict_xid2reqid = {}       # xid -> request id

# Time to not flood in seconds
FLOOD_HOLDDOWN = 8

# Flow timeouts
FLOW_IDLE_TIMEOUT = 1000
FLOW_HARD_TIMEOUT = 300

# How long is allowable to set up a path?
PATH_SETUP_TIME = 4

#Group information
group = defaultdict(lambda:[None,[]]) # {group id:[dst id], }

request_list = {}
#store request when packet in, delete request when barrier in   
request_buffer = []  #[request_id, src, dst, event.ofp, packetin_time]



#--------Statistics----------
link_usage = [0 for x in range(LINK_SUM)]

count_packetin = 0
request_delnum = 0

def link2node(link_num):    
    for node1, value in adjacency.items():
        for node2, info_tuple in value.items():
            if info_tuple[1] == link_num:
                return node1, node2
            else:
                continue
            
def node2link(topo,src,dst):
    try:
        link_num = topo[src][dst][1]
        return link_num
    except:
        print "Error in node2link: There is no link between %d and %d." % (src,dst)     
    

def check_connect(topo_adj, src, Dst):  
    connected = 1
    nodes = []
    nodes.append(src)   # from the source node
    num = []
    
    for i in nodes:
        num = topo_adj[i].keys()
        for n in num:
            if n not in nodes:
                nodes.append(n)        
        if set(Dst) < set(nodes):   #  if nodes includes Dst
            connected = 1
        else:
            connected = 0

    return connected


def addslot(start,length,path_link):    # from cc
    global slot_map
    for j in path_link:
        for i in range(length):
            slot_map[j][start+i] = 0
            

def delslot(start,length,path_link):    # from cc
    global slot_map
    for j in path_link:
        for i in range(length):
            slot_map[j][start+i] = 1
            
def _calc_paths (topo_adj):
    
    """
    Essentially Floyd-Warshall algorithm
    """

    #sws = switches.values()
    sws = dict_id2dpid.keys()
    path_map.clear()
    for k in sws:
        for j,port in topo_adj[k].iteritems():
            if port is None: 
                continue
            path_map[k][j] = (topo_adj[k][j][2], None) # adjacency[k][j][2] = distance of the link, edit by lsr
        path_map[k][k] = (0,None) # distance, intermediate

    for k in sws:
        for i in sws:
            for j in sws:
                if path_map[i][k][0] is not None:
                    if path_map[k][j][0] is not None:
                        # i -> k -> j exists
                        ikj_dist = path_map[i][k][0]+path_map[k][j][0]
                        if path_map[i][j][0] is None or ikj_dist < path_map[i][j][0]:
                            # i -> k -> j is better than existing
                            path_map[i][j] = (ikj_dist, k)

  
def _get_raw_path (topo_adj,src, dst):
    """
    Get a raw path (just a list of nodes to traverse)
    """
    #if len(path_map) == 0:
    _calc_paths(topo_adj)
    if src is dst:
        # We're here!
        return []
    if path_map[src][dst][0] is None:
        return None
    intermediate = path_map[src][dst][1]
    if intermediate is None:
    # Directly connected
        return []
    raw_path = _get_raw_path(topo_adj, src, intermediate) + [intermediate] + _get_raw_path(topo_adj, intermediate, dst)
    return raw_path


def _check_path (p):
    """
    Make sure that a path is actually a string of nodes with connected ports
    
    returns True if path is valid
    """
    for a,b in zip(p[:-1],p[1:]):
        if adjacency[a[0]][b[0]] != a[2]:
            return False
        if adjacency[b[0]][a[0]] != b[2]:
            return False
    return True

def _get_path (topo_adj, src, dst):
    """
    Gets a cooked path -- a list of (node,in_port,out_port)
    src and dst mean their id
    """
    # Start with a raw path...
    if src == dst:
        path = [src]
    else:
        path = _get_raw_path(topo_adj, src, dst)
        if path is None: return None
        path = [src] + path + [dst]
  
    first_port = 65534
    final_port = 65534
  
    # Now add the ports
    r = []
    in_port = first_port
    for s1,s2 in zip(path[:-1],path[1:]):
        out_port = adjacency[s1][s2][0]
        r.append((s1,in_port,out_port))
        in_port = adjacency[s2][s1][0]
    r.append((dst,in_port,final_port))

    assert _check_path(r), "Illegal path!"
    return r


def _get_tree(topo,path_tree):
    """
    Gets a cooked multicast tree path -- a list of ()   
    """
    """
    Gets a cooked path -- a list of (node,in_port,[out_port])
    src and dst mean their id
    out_port is a list
    """
    first_port = 65534
    final_port = 65534
  
    # Now add the ports
    r = []

    for path in path_tree:
        in_port = first_port
        
        for s1,s2 in zip(path[:-1],path[1:]):
            out_port = adjacency[s1][s2][0]
            r.append((s1,in_port,out_port))
            in_port = adjacency[s2][s1][0]
        r.append((path[len(path)-1],in_port,final_port))
    
    #assert _check_path(r), "Illegal path!"
    r = list(set(r))
    print "r:",r
    return r
    
def MSTree(topo,src,Dst):
    return None


def SPTree(topo,src,Dst):
    dst_num = len(Dst)
    mst_paths = []
    mst_paths_len = []
    
    for i in range(dst_num):
        shortest_path = _get_raw_path(topo,src,Dst[i])
        shortest_path.insert(0,src)
        shortest_path.append(Dst[i])
        path_length = path_map[src][Dst[i]][0]
        if shortest_path is not None:
            mst_paths.append(shortest_path)
            mst_paths_len.append(path_length)
    return mst_paths, mst_paths_len


def layer_search(src, Dst, slot_map, slotneeded):
    global link_usage
    layer_flag = 0

    if slotneeded < SLOT_SUM:
        for i in range(SLOT_SUM - slotneeded + 1):
            
            if layer_flag == 1:  
                #i = SLOT_SUM
                print "layer search successfully!"
                #continue
                break
            assist_adjacency = defaultdict(lambda: defaultdict(lambda: None))
            layer_num = i

            for j in range(LINK_SUM):
                if sum(slot_map[j][i:(slotneeded + i)]) == slotneeded:
                    s1, d1 = link2node(j)
                    assist_adjacency[s1][d1] = adjacency[s1][d1]
            #print "The assist_adjacency is layer[%d]"%i
                            
            flagd = check_connect(assist_adjacency,src,Dst)
    
            #print "connection flag:",flagd
            if flagd == 1:
                '''
                for node1,value in assist_adjacency.items():
                    for nodes2,info_tuple in value.items():
                        info_tuple[2] = 1 # tuple does not support value changed
                '''
                #print "**************assist_topology*************"
                for aa_src in assist_adjacency.keys():
                    for aa_dst in assist_adjacency[aa_src].keys():
                        print "%d-->%d:%r"%(aa_src,aa_dst,assist_adjacency[aa_src][aa_dst])
                        
                path_tree, distance = SPTree(assist_adjacency, src, Dst)# path_tree is a list stored the nodes on the path but src and dst
                #print "path_tree:", path_tree
                
                if len(path_tree) != 0:
                    layer_flag = 1  # MSTree established successfully
                    path_num = len(path_tree)   # how many path in a path_tree
                    link_num = []   # store the link number in the calculated path
                    for p in range(path_num):
                        for k in range(len(path_tree[p])-1): # ergodic the each path in path_tree
                            ln = node2link(assist_adjacency, path_tree[p][k],path_tree[p][k+1])
                            if ln not in link_num:
                                link_num.append(ln) # add the link number to the path
                                link_usage[ln] = link_usage[ln] + slotneeded    # change the link usage
                                if assist_adjacency[path_tree[p][k]][path_tree[p][k+1]] is None:
                                    print "Error in layer search: There is no link between %d and %d"\
                                          % (path_tree[p][k],path_tree[p][k+1])
                
                    addslot(layer_num, slotneeded, link_num)    # change the slot map
                    link_use = link_num
                    
            if layer_flag == 0 and layer_num >= SLOT_SUM - slotneeded:
                layer_num = 0
                link_use = -1
                path_tree = []
                print "The slot is blocked, all layer cannot find!"
                
    else:
        layer_num = 0
        link_use = -1
        path_tree = []
        print "slotneeded is larger than slot_sum!"
    
    print link_usage                       
    return layer_flag, layer_num, assist_adjacency, path_tree

def del_timeout():
    """
    delete expired requests in request_list
    requests:   req_id: [p,links,start,length,stoptime]
    """
    global request_list
    delnum = 0
    for i in request_list.keys():
        item = request_list[i]
        links = item[1]
        start = item[2]
        length = item[3]
        stoptime = item[4]
        # delete slot
        if time.time() > stoptime:
            delslot(i,start,length,links)
            del request_list[i]    #delete this request
            delnum += 1
    return delnum


class WaitingPath (object):
  """
  A path which is waiting for its path to be established
  """
  def __init__ (self, path, packet):
    """
    xids is a sequence of (dpid,xid)
    first_switch is the DPID where the packet came from
    packet is something that can be sent in a packet_out
    """
    self.expires_at = time.time() + PATH_SETUP_TIME
    self.path = path
    print "path:", path
    self.first_switch = dict_id2dpid[path[0][0]] #changed 
    self.xids = set()
    self.packet = packet

    if len(waiting_paths) > 1000:
      WaitingPath.expire_waiting_paths()

  def add_xid (self, dpid, xid):
    self.xids.add((dpid,xid))
    waiting_paths[(dpid,xid)] = self

  @property
  def is_expired (self):
    return time.time() >= self.expires_at

  def notify (self, event):
    """
    Called when a barrier has been received
    """
    global request_buffer
    xid = event.xid
    self.xids.discard((event.dpid,event.xid))
    if len(self.xids) == 0:
      # Done!
      if self.packet:
        log.debug("Sending delayed packet out %s"
                  % (dpid_to_str(self.first_switch),))
        req_id = dict_xid2reqid[xid]
        filter_buffer = filter(lambda item:item[0] == req_id,request_buffer)
        request_buffer = filter(lambda item:item[0] != req_id,request_buffer)
        packetin_time = min([filter_buffer[i][4] for i in range(len(filter_buffer))])
        for item in filter_buffer:       
            msg = of.ofp_packet_out(data=self.packet,
                action=of.ofp_action_output(port=of.OFPP_TABLE))
            core.openflow.sendToDPID(self.first_switch, msg)

      core.Multicast.raiseEvent(PathInstalled(self.path))


  @staticmethod
  def expire_waiting_paths ():
    packets = set(waiting_paths.values())
    killed = 0
    for p in packets:
      if p.is_expired:
        killed += 1
        for entry in p.xids:
          waiting_paths.pop(entry, None)
    if killed:
      log.error("%i paths failed to install" % (killed,))


class PathInstalled (Event):
    """
    Fired when a path is installed
    """
    def __init__ (self, path):
        Event.__init__(self)
        self.path = path

class Switch(EventMixin):
    def __init__(self):
        self.connection = None
        self.ports = None
        self.dpid = None
        self._listeners = None
        self._connected_at = None
        #core.openflow.addListeners(self)
        
    def _install (self, sw_dpid, in_port, out_port_list, match, buf = None, is_multicast = True):
        
        msg = of.ofp_flow_mod()
        #msg.match = match
        msg.match.in_port = in_port
        msg.match.dl_type=0x0908
        msg.idle_timeout = match.ooe_timeout
        #print 'ooe_timeout:',match.ooe_timeout
         
        #msg.hard_timeout = FLOW_HARD_TIMEOUT
        if is_multicast:

            if in_port == 65534:
                #msg.actions.append(of.ofp_action_ooe.set_dst(match.ooe_dst))
                msg.actions.append(of.ofp_action_ooe.set_start(match.ooe_start))
                msg.actions.append(of.ofp_action_ooe.set_length(match.ooe_length))
                msg.match.ooe_dst = match.ooe_dst
            else:
                msg.match.ooe_dst = match.ooe_dst
                msg.match.ooe_start = match.ooe_start
                msg.match.ooe_length = match.ooe_length
            
            for out_port in out_port_list: #change by lsr for multiple out port
                msg.actions.append(of.ofp_action_output(port = out_port))
            msg.buffer_id = buf
            
            switches[sw_dpid].connection.send(msg)
        
        
    def _uninstall(self,p,match):
        #print 'uninstall path: ',p
        for sw,in_port,out_port in p[1:]:   #from the second sw to the last sw
            msg = of.ofp_flow_mod()
            #msg.match = match
            msg.match.in_port = in_port
            msg.match.dl_type=0x0908
            msg.idle_timeout = 1
            #print 'ooe_timeout:',match.ooe_timeout 
            #msg.hard_timeout = FLOW_HARD_TIMEOUT
            msg.match.ooe_dst = match.ooe_dst
            msg.match.ooe_start = match.ooe_start
            msg.match.ooe_length = match.ooe_length     
            msg.actions.append(of.ofp_action_output(port = out_port))
             
            switches[dict_id2dpid[sw]].connection.send(msg)
            
    
    def _install_path (self, req_id, p, match, packet_in=None):
        wp = WaitingPath(p, packet_in)
        for sw,in_port,out_port in p[::-1]:       #send flow table from the end to beginning, # here sw means id
            self._install(dict_id2dpid[sw], in_port, out_port, match)
            msg = of.ofp_barrier_request()
            switches[dict_id2dpid[sw]].connection.send(msg)
            wp.add_xid(dict_id2dpid[sw], msg.xid)        
            dict_xid2reqid[msg.xid] = req_id

          
    def _install_tree(self,req_id, p, match, packet_in = None):    #TODO: use it
        wp = WaitingPath(p, packet_in)
        new_p = []
        raw_path = []
        for i in range(len(p)):
            if p[i][0] in raw_path:
                j = raw_path.index(p[i][0])
                new_p[j][2].append(p[i][2])
            else:
                new_p.append((p[i][0],p[i][1],[p[i][2]]))
            raw_path.append(p[i][0])
            
        print new_p
            
        for sw,in_port,out_port_list in new_p[::-1]:       #send flow table from the end to beginning, # here sw means id
            
            self._install(dict_id2dpid[sw], in_port, out_port_list, match)
            msg = of.ofp_barrier_request()
            switches[dict_id2dpid[sw]].connection.send(msg)
            wp.add_xid(dict_id2dpid[sw], msg.xid)        
            dict_xid2reqid[msg.xid] = req_id
    
   
    def _handle_PacketIn(self, event):  
        global request_buffer
        global request_delnum
        global slot_map
        global link_usage
        
        def drop ():
            # Kill the buffer
            if event.ofp.buffer_id is not None:
                msg = of.ofp_packet_out()
                msg.buffer_id = event.ofp.buffer_id
                event.ofp.buffer_id = None # Mark is dead
                msg.in_port = event.port
                self.connection.send(msg)
                
        packet = event.parsed
        match = of.ofp_match.from_packet(packet)
        
        if packet.effective_ethertype == packet.LLDP_TYPE:  #FIXME: must be modified
            drop()
            return
        
        if match.dl_type == 0x0908:
            global count_packetin
            count_packetin = count_packetin +1
            packetin_time = time.time()
            
            #delete request if it is out of time
            delnum = del_timeout()
            request_delnum += delnum
            print "request_delnum:",request_delnum
            
            dst = match.ooe_dst & 0xffff
            req_id = (match.ooe_dst & 0xffff0000) >> 16
            bit_rate = match.ooe_bit_rate
            
            src = dict_dpid2id[event.dpid]
        
            print "packet in count:",count_packetin
            print "src node: %d" % src
            print "dl_type: %04x" % (match.dl_type)
            print "req_id:",req_id
            print "destination gourp id:", dst
            print "start_slot:%x" % match.ooe_start
            print "bitrate:", match.ooe_bit_rate
            
            #Generate a list of destination nodes randomly.
            dst_num = random.randint(1,SW_SUM-1)
            Dst = []
            while len(Dst) == 0:
                for i in range(dst_num):
                    Dst.append(random.randint(1,SW_SUM))
                while src in Dst:
                    Dst.remove(src)
            
            Dst = list(set(Dst))
            
            delnum = del_timeout()
            request_delnum += delnum
            print 'request num:',request_delnum
            
            #Dst = [3, 4]
            print "%d --> %r" % (src,Dst)
            
            flag = 0
            if req_id in [request_buffer[i][0] for i in range(len(request_buffer))]:
                flag = 1
                print "the request is processing!"
            request_buffer.append([req_id,src,Dst,event.ofp,packetin_time])
            
            
            if flag == 0:
                for dst in Dst:
                    if (src,dst) not in path_map:
                        drop()
                        
                        
            slotneeded = int(math.ceil(bit_rate / slotspace))
            
            layer_flag, layer_number, assist_topo, path_tree \
            = layer_search(src, Dst, slot_map, slotneeded)
            
            print "path tree:",path_tree
            p = _get_tree(assist_topo, path_tree)
            print "p:",p
            self._install_tree(req_id, p, match, event.ofp)
            '''
            for i in range(len(Dst)):
                p = _get_path(assist_topo, src, Dst[i])
                print "p:", p
                self._install_path(req_id, p, match, event.ofp)
            '''
            
            '''
            print "layer flag:", layer_flag
            print "layer number:",layer_number 
            print "assist topo:",assist_topo
            print "link usage:", link_usage1
            '''
            
            '''
            msg = of.ofp_flow_mod()
            msg.match.in_port = event.port
            msg.match.dl_type = 0x0908
            msg.idle_timeout = 100
            msg.match.ooe_dst = match.ooe_dst
            print dpid_to_str(dict_id2dpid[src])
            msg.actions.append(of.ofp_action_output(port=2))
            #core.openflow.sendToDPID(dict_id2dpid[src],msg)
            switches[dict_id2dpid[src]].connection.send(msg)
            '''
            
            
            
    def disconnect (self):
        if self.connection is not None:
            log.debug("Disconnect %s" % (self.connection,))
            self.connection.removeListeners(self._listeners)
            self.connection = None
            self._listeners = None
            
    
    def connect (self, connection):
        if self.dpid is None:
            self.dpid = connection.dpid
        assert self.dpid == connection.dpid
        if self.ports is None:
            self.ports = connection.features.ports
        self.disconnect()
        log.debug("Connect %s" % (connection,))
        self.connection = connection
        self._listeners = self.listenTo(connection)
        self._connected_at = time.time()
        
    
    @property
    def is_holding_down (self):
        if self._connected_at is None: return True
        if time.time() - self._connected_at > FLOOD_HOLDDOWN:
            return False
        return True
    
    
    def _handle_ConnectionDown (self, event):
        self.disconnect()
            
    
class Multicast(EventMixin):
    
    _eventMixin_events = set([PathInstalled,])
    
    def __init__(self):
        # Listen to dependencies
        core.openflow.addListeners(self)
        
    def _handle_ConnectionUp(self,event):
        sw = switches.get(event.dpid)
        if sw is None:              # New switch
            sw = Switch()
            switches[event.dpid] = sw
            #print switches
            sw.connect(event.connection)
        else:
            sw.connect(event.connection)
    
    def _handle_BarrierIn (self, event):
        wp = waiting_paths.pop((event.dpid,event.xid), None)
        #print "(%s, %s) receive barrier reply from %d" % (event.dpid, event.xid, dict_dpid2id[event.dpid])
        if not wp:
            #log.info("No waiting packet %s,%s", event.dpid, event.xid)
            return
        #log.debug("Notify waiting packet %s,%s", event.dpid, event.xid)
        wp.notify(event)     
    
            
def launch ():
    core.registerNew(Multicast)

"""
if __name__ == "__main__":
    
    
    import random
    request_list = []
    req_num = 10
    for i in range(1, req_num + 1):
        dst_num = random.randint(2,SW_SUM-1)
        request = [0,0,[],0]
        request[0] = i
        request[1] = random.randint(1,SW_SUM)
        while len(request[2]) == 0:
            for j in range(dst_num): 
                request[2].append(random.randint(1,SW_SUM))
            while request[1] in request[2]:
                #print "remove %d from %r"%(request[1],request[2])
                request[2].remove(request[1])    
        request[2] = list(set(request[2]))
        request[3] = random.randint(1,5)
        request_list.append(request)

    for request in request_list:
        print request
    
    print "-----------------Test for _get_raw_path---------------------"

    _calc_paths()
    for i in path_map.keys():
        for j in path_map[i].keys():
            print "%d-->%d"%(i,j), path_map[i][j]
    
    
    
    print "----------------------Test for SPTree-----------------------"
    src = 4
    Dst = [3, 5, 6]

    adjacency1 = defaultdict(lambda:defaultdict(lambda:None))

    adjacency1[1][2] = (1,0,300)
    adjacency1[2][1] = (3,8,300)
    adjacency1[1][6] = (2,1,700)
    adjacency1[6][1] = (1,9,700)
    #adjacency1[2][3] = (4,3,1000)
    adjacency1[3][2] = (1,11,1000)
    adjacency1[2][6] = (5,2,500)
    #adjacency1[6][2] = (3,10,500)
    #adjacency1[6][5] = (2,4,750)
    #adjacency1[5][6] = (2,12,750)
    adjacency1[3][5] = (2,5,400)
    adjacency1[5][3] = (1,13,400)
    adjacency1[3][4] = (3,6,600)
    adjacency1[4][3] = (1,14,600)
    #adjacency1[5][4] = (3,15,200)
    adjacency1[4][5] = (2,7,200)
            
    mst_paths, mst_paths_len = SPTree(adjacency1, src, Dst)
    
    print "%d --> %r"%(src,Dst)
    for i in range(len(Dst)):
        print "%d --> %d : %r, cost:%d"%(src,Dst[i],mst_paths[i],mst_paths_len[i])
    
    
    #print "--------Test for layer search---------"
    for req in request_list:
        print "--------------------------------------------------------------"
        src = req[1]
        Dst = req[2]
        slotneeded = req[3]
        print "req number:", req[0]
        print "source:",src
        print "destination:",Dst
        print "slotneeded:", slotneeded
        
        layer_flag, layer_number, assist_topo,link_usage1 = layer_search(src, Dst, slot_map, slotneeded, link_usage)
        '''
        print "**************assist_topology*************"
        for aa_src in assist_topo.keys():
            for aa_dst in assist_topo[aa_src].keys():
                print "%d-->%d:%r"%(aa_src,aa_dst,assist_topo[aa_src][aa_dst])
        '''
        print "*****************slot_map*****************"
        for i in range(len(slot_map)):
            print slot_map[i], "link %d"%i
        print "******************************************"
        print "link usage:", link_usage
"""
    
    

