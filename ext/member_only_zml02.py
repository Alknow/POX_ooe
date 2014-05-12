'''
'member_only' algorithm in POX 
For totally work:  if a node of multicast blocked, then block all the nodes.

Edit by Melody
2014.4.26
'''

from pox.core import core
import pox.openflow.libopenflow_01 as of
from pox.lib.revent import *
from pox.lib.recoco import Timer
from collections import defaultdict
from pox.lib.util import dpid_to_str
from pox.lib.addresses import EthAddr
from pox.lib.packet.ooe import ooe
import math
import copy
import time
import random
import member_only

log = core.getLogger() #record the process

'''---------------------------Topology informations----------------------------'''
#the dict of id -> dpid
dict_id2dpid = {1:0x0000f80f41f42a1a,
                2:0x000090e2ba0abc70,
                3:0x000090e2ba0ab8e1,
                4:0x000090e2ba0ab392,
                5:0x000090e2ba0abc71,
                6:0x000090e2ba0ab390,
                }

#the dict of dpid -> id
dict_dpid2id = {v:k for k,v in dict_id2dpid.items()}     #reverse of dict_id2dpid

# Adjacency map.  [sw1][sw2] -> port, link, distance
adjacency = defaultdict(lambda:defaultdict(lambda:None))
adjacency[1][2] = (1, 0, 300) #port,link_No.,cost
adjacency[2][1] = (3, 8, 300)
adjacency[1][6] = (2, 1, 700)
adjacency[6][1] = (1, 9, 700)
adjacency[2][3] = (4, 3, 1000)
adjacency[3][2] = (1, 11, 1000)
adjacency[2][6] = (5, 2, 500)
adjacency[6][2] = (3, 10, 500)
adjacency[6][5] = (2, 4, 750)
adjacency[5][6] = (2, 12, 750)
adjacency[3][5] = (2, 5, 400)
adjacency[5][3] = (1, 13, 400)
adjacency[3][4] = (3, 6, 600)
adjacency[4][3] = (1, 14, 600)
adjacency[5][4] = (3, 15, 200)
adjacency[4][5] = (2, 7, 200)
for i in range(1,len(adjacency)+1):
        for j in range(1,len(adjacency)+1):
            if adjacency[i][j]==None:
                adjacency[i][j]=(float('inf'),float('inf'),float('inf'))

LINK_NUM =16 #total number of links
SW_NUM = 6 #nuber of switches 
SW = dict_id2dpid.keys()#SW=[1,2,3,4,5,6]

'''--------------------------Initialization-------------------------------------------'''
SLOT_TOTAL = 358
FLOOD_HOLDDOWN = 8 # Time to not flood in seconds
PATH_SETUP_TIME = 4# How long is allowable to set up a path?

packetin_num = 0
block_num = 0
block_bit = 0
request_delnum = 0
request_delnum_total = 0
total_bit = 0
MAX_SLOT_USED = 0
TOTAL_SLOT_USED = 0
request_list = {}

# xid -> request id
dict_xid2reqid = {}  

# Switches we know of.  [dpid] -> Switch
switches = {} 

# Waiting path.  (dpid,xid) -> WaitingPath
waiting_paths = {}
        
#store request when packet in, delete request when barrier in   
request_buffer = []  #[request_id, src, dst, event.ofp, packetin_time]

#-slots usage initialization-#
slot_map = [[1 for x in range(SLOT_TOTAL)] for y in range(LINK_NUM)] 
slot_map_copy = []
slot_map_id = [[0 for x in range(SLOT_TOTAL)] for y in range(LINK_NUM)]
slot_map_id_copy = []

del_req_num = 0 #lsr
'''-----------------------------Finding Path--------------------------------------'''
def write_map(slot_map):
    f = file('/home/zml/member_only/slot_map.txt','w+')
    f.write(str(slot_map))
    f.close


#whether the src and dst are in specific switches
def whether_in_SW (Switch,source,destinations):
    num = 0
    if source in Switch:
        for i in range(len(destinations)):
            if destinations[i] not in Switch:
                num +=1
        if num>0:
            return False
        else:
            return True
               
    else:
        return False


#-Mark request's slots occupy-#
def addslot(req_id,start,length,path_link):
    global slot_map,slot_map_id
    for j in path_link:
        for i in range(length):
            slot_map[j][start+i] = 0
            slot_map_id[j][start+i] = req_id

#-Delete request's slots occupy-#
def delslot(req_id,start,length,path_link):
    global slot_map,slot_map_id
    print 'It is delslot function!'
    print 'delete links:',path_link
    
    for j in path_link:
        #print "delete slot from %d to %d on %s print at delslot function" % (start, start + length, path_link) #lsr
        for i in range(length):
            slot_map[j][start+i] = 1
            slot_map_id[j][start+i] = 0

#-delete timeout request and its slots occupy-#
def del_timeout():
    '''
    request_list[req_id] = [p[],match,stoptime,links[],starts[],lengths[]] 
    '''
    print 'It is del_timeout function!!!!'
    
    global request_list
    global del_req_num
    delnum = 0
    for i in request_list.keys():   
        item = request_list[i]
        #path_old = item[0]
        #match_old = item[1]
        stoptime = item[2]
        links_old = item[3]
        starts_old= item[4]
        lengths_old = item[5]
        #print "links_old:", links_old
        #print 'request id:',i,
        #print 'time minus:',time.time()-stoptime
        
        # delete slot
        if time.time() > stoptime:
            for j in range(len(starts_old)): 
                delslot(i,starts_old[j],lengths_old[j],links_old[j])
                #print "delete slots from %d to %d on %s" % (starts_old[j], starts_old[j] + lengths_old[j], links_old[j])
            del request_list[i]    #delete this request
            #print 'request %d delete' % i
            delnum += 1
            del_req_num += 1
    return delnum

#-find the maximum slot ever used-#
def calc_maxslot():
    maxslot = 0;
    templist = range(SLOT_TOTAL)
    templist.reverse()
    for i in range(LINK_NUM):
        for j in templist:
            if slot_map[i][j] == 0:
                if j > maxslot:
                    maxslot = j
                break
    return maxslot

#-find slots location-#
def calcslot(bitrate,path,path_link,distance):
    
    maxdistance = 9600.0
    subcarrier = 1
    slotspace = 12.5 #granularity
    
    M = math.floor(math.log(maxdistance / distance, 2) + 1) 
    RB = bitrate * (subcarrier + 1) / (2 * M * subcarrier) 
    slot_num = int(math.ceil(RB / slotspace))     # length

    #pick up all the links and find their same free slots
    slot_temp = [1]*SLOT_TOTAL
    for j in path_link:
        for i in range(SLOT_TOTAL):
            slot_temp[i] = slot_map[j][i] & slot_temp[i]
  
    start = None
    for i in range(SLOT_TOTAL - slot_num +1):
        count = 0
        if slot_temp[i] == 1:
            for j in range(slot_num):
                if slot_temp[i+j] != 1:
                    break
                else:
                    count += 1
        if count == slot_num:
            start = i
            break
    return start,slot_num

def slot_location(bitrate,paths):
    '''
    paths=[(link_section, minpath[], minpath_port[], mincost, link_id[])]
    multiple starts & lengths  for multiple destinations:
    starts[]
    lenghts[]
    '''
    starts = [0] * len(paths)
    lengths = [0] * len(paths)
    
    for i in range(len(paths)):
        minpath = paths[i][1] 
        mincost = paths[i][3]
        if len(minpath) == 1:    # if src == dst,there is only one path and no need to allocate slot
            start = None
            length = None    
        else:
            links = paths[i][4] 
            start,length = calcslot(bitrate,minpath,links,mincost) # calculate slots location(start,length)
            if start is None:
                starts[i]=None
                lengths[i]=length
            else:
                starts[i]=start
                lengths[i]=length                 
    return starts,lengths

def _install_path (req_id, p, match, packet_in=None):
    print 'install path: ',p
    #global waiting_df_xid
    
    def _install (sw_dpid, in_port, out_port, match, buf = None):
        msg = of.ofp_flow_mod()
        msg.match.in_port = in_port
        msg.match.dl_type=0x0908
        msg.match.ooe_dst = match.ooe_dst
        msg.idle_timeout = match.ooe_timeout   
        
        length = match.ooe_length 
        start = match.ooe_start 
        
        if in_port == 65534:                                                    # the first node
            msg.actions.append(of.ofp_action_ooe.set_start(start))
            msg.actions.append(of.ofp_action_ooe.set_length(length))
        else:
            msg.match.ooe_start = start 
            msg.match.ooe_length = length
        msg.actions.append(of.ofp_action_output(port = out_port))
        
        
        #msg.buffer_id = buf
        switches[sw_dpid].connection.send(msg)
    
    wp = WaitingPath(p, packet_in) # a class
    for sw,in_port,out_port in p[::-1]:       #send flow table from the end to beginning, here sw means sw_id
        _install(dict_id2dpid[sw], in_port, out_port, match)
            
        msg = of.ofp_barrier_request()       # send barrier request
        switches[dict_id2dpid[sw]].connection.send(msg)        
        wp.add_xid(dict_id2dpid[sw], msg.xid)
        if packet_in:          #if packet is not None, it is RSA
            dict_xid2reqid[msg.xid] = req_id
        #else:                   #if packet is None, it is Re-RSA( or DF )
            #waiting_df_xid.append(msg.xid)      

'''--------------------------------POX-------------------------------------------'''

class WaitingPath (object):
    """
    A path which is waiting for its path to be established
    """
    def __init__ (self, path, packet):
        """
        xids = set( (dpid, xid), (x, x), (x, x) ):
        first_switch is the DPID where the packet came from
        packet is something that can be sent in a packet_out
        """
        self.expires_at = time.time() + PATH_SETUP_TIME
        self.path = path
        self.first_switch = dict_id2dpid[path[0][0]] #changed by cc ,add dict_id2dpid
        self.xids = set()
        self.packet = packet
    
        if len(waiting_paths) > 1000:
            print 'waiting_paths is too long!'
            print 'len(waiting_paths):',len(waiting_paths)
            WaitingPath.expire_waiting_paths() #delete expire packets

    def add_xid (self, dpid, xid):  
        self.xids.add((dpid,xid))
        waiting_paths[(dpid,xid)] = self
    
    @property
    def is_expired (self):
        return time.time() >= self.expires_at
    
    def notify (self,event):
        """
        Called when a barrier has been received
        """
        global request_buffer
      
        xid = event.xid
        
        #print 'xid:',xid
        #print 'request_buffer',request_buffer
        #print 'xids:',self.xids

        self.xids.discard((event.dpid,event.xid))  #delete (event.dpid, event.xid) from xids if it exists
        if (len(self.xids) == 0):     #the last barrier reply of a path is received
            if self.packet and (request_buffer!=[]):
                log.debug("Sending delayed packet out %s" % (dict_dpid2id[self.first_switch]))
                req_id = dict_xid2reqid[xid]   
                filter_buffer = filter(lambda item:item[0]==req_id,request_buffer) #the present request
                request_buffer = filter(lambda item:item[0] != req_id, request_buffer)     #delete requests from request_buffer  
                #print 'len(filter_buffer):',len(filter_buffer)
                #print 'filter_buffer:',filter_buffer
                #print 'request_buffer:',request_buffer
                if filter_buffer!=[]:
                    packetin_time = min([filter_buffer[i][4] for i in range(len(filter_buffer))]) #FIXME: min()
                else:
                    packetin_time = 0
                for item in filter_buffer:
                    msg = of.ofp_packet_out(data=item[3], action=of.ofp_action_output(port=of.OFPP_TABLE))
                    core.openflow.sendToDPID(self.first_switch, msg)
                barrierin_time = time.time()
                setup_lantency = barrierin_time - packetin_time
                print 'setup_lantency:',setup_lantency
                print 'OVER...'
                #print '-'*50
                print
                
            core.member_only_pox.raiseEvent(PathInstalled(self.path))

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
    

class Switch(EventMixin):
    def __init__ (self):
        self.connection = None
        self.ports = None
        self.dpid = None
        self._listeners = None
        self._connected_at = None
        
    def _handle_PacketIn (self,event):
        '''
        req: [req_id, src, dst[], bitrate, hold_time, PacketIn_time] 
        one request
    
        packetin_num: total packet_in requests numbers 
        delnum: currently deletion requests numbers
        request_delnum: total deletion 
        maxslot: maximum slots now
        MAX_SLOT_USED: maximum slits overall situation
        path_detail:(flag, treenode_detail, totalcost)
        path_map:[(link_section, minpath[], minpath_port[], mincost, link_id[])]
        request_list[req_id] = [path,match,stoptime,links]
        '''  
        global request_delnum
        global request_delnum_total
        global packetin_num
        global block_num
        global block_bit
        global total_bit
        global MAX_SLOT_USED
        global TOTAL_SLOT_USED
        global request_buffer
        global Total_df_req
        global Total_df_times
        global Total_df_batch
        global block_due_to_df
        global batch_num
        global DF_batch_lantency
        global SW
        global request_list
        global adjacency
        global del_req_num
        
        #-Kill the buffer-#
        def drop (): 
            #buffer_id: ID of the buffer in which the packet is stored at the datapath.     
            if event.ofp.buffer_id is not None:
                msg = of.ofp_packet_out()
                msg.buffer_id = event.ofp.buffer_id
                event.ofp.buffer_id = None # Mark is dead
                msg.in_port = event.port
                self.connection.send(msg)
        
        
        packet = event.parsed
        match = of.ofp_match.from_packet(packet)
        
        if packet.effective_ethertype == packet.LLDP_TYPE:  
            drop()
            return
        
        if match.dl_type == 0x0908:
            print '------------------------packet %d begin to parse-----------------------' % packetin_num
            
            packetin_time = time.time() 
            
            #-delete request which is out of time-#
            delnum = del_timeout()    # delete number at once
            request_delnum_total += delnum   # delete number totally
            #request_delnum_total += request_delnum
            print 'request_delnum:',delnum
            print 'request_delnum_total',request_delnum_total
            #print 'length of request_list',len(request_list)
            
            #-request information-#
            src = dict_dpid2id[event.dpid] #change dpid to id
            ooe_dst = match.ooe_dst
            dst1 = ooe_dst & 0xffff
            req_id = (ooe_dst & 0xffff0000) >> 16
            group_dst = (ooe_dst & 0xffff)
            bitrate = match.ooe_bit_rate
            timeout = match.ooe_timeout  
            dl_type = match.dl_type
            
            print "group dst:", group_dst
            #print "request list:", request_list
            
            if req_id in request_list.keys(): #lsr
                print "req_id %d dropped because req already exist!" % req_id
                print "--------------------------------------------"
                drop() 
                return
            
                
            print "timeout:",timeout
            #-generate multiple destinations-#
            dst = []
            dst_num = random.randint(1,SW_NUM-1) #changed by lsr
            while len(dst) == 0:
                for i in range(dst_num):
                    dst.append(random.randint(1,SW_NUM))
                while src in dst:
                    dst.remove(src)
            dst= list(set(dst))
            '''
            for i in range(0,dst1): #????
                if 1<src<len(SW):
                    dst_temp1 = random.randint(1,src-1)
                    dst_temp2 = random.randint(src+1,len(SW))
                    dst.append(dst_temp1)
                    dst.append(dst_temp2)
                elif src ==1:
                    dst_temp = random.randint(src+1,len(SW))
                    dst.append(dst_temp)
                elif src == len(SW):
                    dst_temp = random.randint(1,len(SW)-1)
                    dst.append(dst_temp)
            dst= list(set(dst)) #remove repeated num

            if src in dst: 
                dst.remove(src)  
            '''
            #--# 
            
            #src = 5 #FIXME: the value is just for testing
            #dst = [3,4,2] 
            print '< ----------------Request Information---------------- >'       
            print 'req_id:',req_id,
            print ', src:',src,
            #print 'dst1:',dst1,
            print ', dst:',dst,
            print ', bitrate:',bitrate
            #print ' timeout:',timeout
            
            print '< Request Processing >'
            flag = 0
            if req_id in [request_buffer[i][0] for i in range(len(request_buffer))]:
                #reuqest_buffer:store request when packet in
                flag = 1
                print 'the request %d is is processing, waiting to packetout!'%req_id
            
            request_buffer.append([req_id, src, dst1, event.ofp, packetin_time]) #add the request in to the buffer
            
            if flag == 0:
                packetin_num += 1
                if not whether_in_SW (SW,src,dst):
                    log.warning("Can't get a path from %s to %s", src, dst)
                    msg = of.ofp_flow_mod()    #can be replaced by drop()
                    msg.match.in_port = event.port
                    msg.match.dl_type = dl_type
                    msg.idle_timeout = 10
                    msg.match.ooe_dst = match.ooe_dst   
                    switches[dict_id2dpid[src]].connection.send(msg)
                else:
                    #-calculate path-#
                    path_detail = member_only.member_only(src, dst, 0,adjacency)
                    path_map = path_detail[1] 
                    path_cost = path_detail[2] #total cost
                    
    
                    #-slots locations-#
                    starts, lengths= slot_location(bitrate,path_map) 
                    total_bit += bitrate
                    
                    p_temp=[]
                    links_temp=[]
                    
                    #exist one way be blocked
                    if None in starts: 
                        for i in range(len(starts)): 
                            if starts[i] == None:
                                print 'No.%d link is blocked'.center(30,'*')%i
                                print 'Can not reach destination %s'%dst[i]
                                print 'slot_num:',lengths[i] 
                                print
                        block_num += 1
                        block_bit+=bitrate
                        #drop the packet
                        request_buffer = filter(lambda item:item[0] != req_id, request_buffer) 
                        msg = of.ofp_flow_mod()    #can be replaced by drop()
                        msg.match.in_port = event.port
                        msg.match.dl_type=0x0908
                        msg.idle_timeout = 10
                        msg.match.ooe_dst = match.ooe_dst   
                        switches[dict_id2dpid[src]].connection.send(msg) 
                    else:  
                        for i in range(len(starts)):       
                            p = path_map[i][2] #path+in_port+out_port
                            p_temp.append(p)
                            #p_cost = path_map[i][3]
                            links = path_map[i][4]
                            links_temp.append(links)
                            if links == []: #src == dst
                                print 'source == destination, no need to allocate slots!'
                            else:  
                                addslot(req_id,starts[i],lengths[i],links)                   
                                match.ooe_start = starts[i]
                                match.ooe_length = lengths[i]
                            
                                _install_path(req_id,p, match, event.ofp) #def
                                TOTAL_SLOT_USED += lengths[i] 
                                stoptime = time.time() + timeout #FIXME:
                            print 'No. ',i
                            print 'links:',links
                            print 'start:',starts[i],
                            print ', slot_num:',lengths[i]
                            #print ', cost:',p_cost 
                            #print 'path:',p                                
                            print
                        
                        request_list[req_id] = [p_temp,match,stoptime,links_temp,starts,lengths] #FIXME:
                        
                print '< ---------------Block Rate--------------- >'
                print 'packetin_num:',packetin_num,',',' block_num:',block_num
                print 'block_rate(num): ',float(block_num)/packetin_num
                print 'block_rate(bitrate): ',float(block_bit) / total_bit
                print 'total delete req number:', del_req_num
                #write_map(slot_map)
                    
            #-calculate maxslot occupation-#
            maxslot = calc_maxslot()
            if maxslot > MAX_SLOT_USED: 
                MAX_SLOT_USED = maxslot
            print 'maxslots used: ',MAX_SLOT_USED
            print 'total slots used: ',TOTAL_SLOT_USED
        
                    
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


class PathInstalled (Event):
    def __init__(self,path):
        Event.__init__(self)
        self.path = path


class member_only_pox(EventMixin):
    _eventMixin_events = set([PathInstalled,]) #raise the event: PathInstalled(a class)
    
    def __init__ (self):
        core.openflow.addListeners(self) #add listener
    
    def _handle_ConnectionUp (self,event):
        sw = switches.get(event.dpid) #switches{}: dpid -> switch
        if sw is None:
            sw = Switch() # a class
            switches[event.dpid] = sw
            sw.connect(event.connection)
        else:
            sw.connect(event.connection) 
    
    def _handle_BarrierIn (self,event):
        #waiting_paths{}:(dpid,xid)->WaitingPath
        wp = waiting_paths.pop((event.dpid,event.xid),None) 
        if not wp:
            return
        wp.notify(event)
        

def launch():
    core.registerNew(member_only_pox) #register a class named 'member_only_pox'































