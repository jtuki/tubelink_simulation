#-*- coding: utf-8 -*-
# jtuki@foxmail.com

r"""针对 TDMA+LPW 的方式做一些仿真验证。
note -
1. TDMA 仅有上行、LPW 仅有下行，前者是可以按照 TDMA 时间槽的长度来步进的，而后者是更离散的 1ms 步进。
2. 鉴于第1点，我们使用两次timeline遍历，分别针对上行和下行的场景，得到运行数据，然后再联合起来给出仿真结果。
"""

# 功耗开销参数
# 电流
AMP_TX = 120    # mA
AMP_RX = 10
AMP_SLEEP = 0.005
# 时长
DURATION_UPLINK = 200   # ms - 发送一帧数据的时间
DURATION_DOWNLINK = 200 # 假设接收一帧数据的持续时间
DURATION_ACK = 80       # 发出去一帧后，会收到网关ack；收到网关数据后，要发出一帧ack
DURATION_CAD_NO_PERAMBLE = 2   # 节点每个 gl_longPreambleDuration 时间段里的CAD开销
DURATION_CAD_HAS_PREAMBLE_SUFFIX = 20   # 虽然sx1278 lora模式不支持这么做，但考虑到比较的公平性问题，依然
                                        # 设定了这个参数，即，节点收到preamble之后的几个payload字节、发现并
                                        # 非发给自己时，额外接收的这几个payload字节持续的时长。
# 单次收发功耗开销
POWER_CONSUMPTION_TX_UPLINK         = AMP_TX * DURATION_UPLINK      # TDMA 发送一帧上行的power开销
POWER_CONSUMPTION_RX_DOWNLINK       = AMP_RX * DURATION_DOWNLINK    # LPW 接收一帧下行的power开销
POWER_CONSUMPTION_RX_ACK            = AMP_RX * DURATION_ACK
POWER_CONSUMPTION_TX_ACK            = AMP_TX * DURATION_ACK
POWER_CONSUMPTION_CAD_NO_PREAMBLE   = AMP_RX * DURATION_CAD_NO_PERAMBLE     # CAD preamble但没有数据的开销
POWER_CONSUMPTION_CAD_PREAMBLE_SUFFIX = AMP_RX * DURATION_CAD_HAS_PREAMBLE_SUFFIX

# 总共的运行时间(ms)
gl_totalRunTime = 3600*10*1000
gl_curRunTime = 0           # 当前的仿真运行时间 (ms)

gl_nodeID_node_mapping = {}     # nodeID => NodeUp或者NodeDown节点

# 对TDMA而言，每个节点都有分配一个固定的时间槽
gl_slotID_node_mapping = {}     # slotID => NodeUp

# 对于 LPW 而言，发送消息是等同于将一串排序好的数据帧，依次发送出去
gl_allDownlinkMsg = []
gl_channel_nodes_mapping = {}   # channel => nodes @gl_downChannelNum
    
from random import randint
import numpy as np

from simple_logger import get_logger

logger = get_logger()

def gen_possion_msg_sequence(avg, duration):
    r"""返回一个泊松分布的序列，表示各个消息的创建时间。
    @avg         泊松分布的期望值（消息间隔的期望值）
    @duration    整体消息序列所在的时间轴长度
    """
    s = list(np.random.poisson(avg, int(duration*1.5/avg)))
    for i in range(1, len(s)):
        s[i] += s[i-1]
        if s[i] >= duration:
            s = s[:i]
            break
    return s if len(s) > 0 else [int(randint(1, duration))] # 至少1个

def gen_saddr(reinit=False):
    r"""针对一个网关下的所有节点，分配不重复的短地址
    """
    if reinit:
        gen_saddr.saddrList = []
    
    ok = False
    saddr = None
    try:
        while not ok:
            saddr = randint(0x0001, 0xFFFA)
            if saddr not in gen_saddr.saddrList:
                ok = True
                gen_saddr.saddrList.append(saddr)
    except:
        gen_saddr.saddrList = []
        gen_saddr.saddrList.append(saddr)
    return saddr

def gen_slots_alloc(reinit=False):
    r"""针对一个网关下的所有上行节点，分配上行时间槽
    """
    if reinit:
        gen_slots_alloc.slotID = -1
        return
    
    gen_slots_alloc.slotID += 1
    assert gen_slots_alloc.slotID < gl_nodesUpNum   # valid range: [0, gl_nodesUpNum)
    
    return gen_slots_alloc.slotID

def time_prefix():
    r"""显示当前的仿真时间做为日志前缀
    """
    return "%12s:" % str(gl_curRunTime)

def init_simulation_state():
    global gl_nodeID_node_mapping
    global gl_slotID_node_mapping
    global gl_allDownlinkMsg
    global gl_channel_nodes_mapping
    
    gen_saddr(reinit=True)
    gen_slots_alloc(reinit=True)
    
    gl_nodeID_node_mapping = {}
    gl_slotID_node_mapping = {}
    gl_channel_nodes_mapping = {}
    gl_allDownlinkMsg = []

###############################################################################
# TDMA simulation
###############################################################################

class NodeMsg(object):
    r"""上行节点的消息。
    """
    def __init__(self, id, t):
        self.nodeID = id
        self.genTime = t    # 假设在这个网络里不存在重传的问题，由于TDMA的指定时间槽内不存在冲突
        self.txTime = None  # 一旦发送之后，txTime被置成发送的时间
        self.powerConsumption = 0    # 本仿真中，一个上行节点的功耗开销，等于其所有上行消息的功耗开销总和
        self.txDuration = 0
        self.rxDuration = 0
    
    def tx(self, t):
        assert self.txTime is None
        self.txTime = t
        self.powerConsumption += POWER_CONSUMPTION_TX_UPLINK + POWER_CONSUMPTION_RX_ACK
        self.txDuration += DURATION_UPLINK
        self.rxDuration += DURATION_ACK

class NodeUp(object):
    r"""上行消息节点。
    """
    def __init__(self, avgEvent):
        self.id = gen_saddr()
        gl_nodeID_node_mapping[self.id] = self
        
        self.slotID = gen_slots_alloc() # 模拟入网后被分配固定时间槽的情况
        gl_slotID_node_mapping[self.slotID] = self
        
        self.randStart = randint(0, gl_nodeInitSpan)
        
        self.avg = avgEvent     # 上行消息间的时间间隔（泊松分布期望值）
        
        self.eventMsgGenTime = gen_possion_msg_sequence(self.avg,
                                            gl_totalRunTime - self.randStart - gl_nodesUpNum*gl_slotDuration)
        
        self.msgList = []   # 所有的上行消息对象
        self.msgNoIterList = [] # 所有不再参与后续遍历搜索的消息对象
        
        for t in self.eventMsgGenTime:
            # 所有msg的genTime时间是严格递增的
            self.msgList.append(NodeMsg(self.id, self.randStart + t))
            
        logger.debug(time_prefix() + "NodeUp inited: 0x%X, eventNum %d" 
                     % (self.id, len(self.eventMsgGenTime)))
        self.simulationFinished = False
        
    def get_msg_can_tx(self, slotID, before):
        r"""获取节点中待发送的消息 (在@before时刻之前被创造出来)
        """
        assert slotID == self.slotID

        m = []  # (msg, idx)
        idx = 0
        for msg in self.msgList:
            assert isinstance(msg, NodeMsg)
            if msg.genTime < before:
                m.append((msg, idx))
                if len(m) >= gl_maxUpPerSlot:
                    break
            elif msg.genTime > before:
                # 所有msg的genTime时间是严格递增的，因此后续所有的genTime都比before大
                break
            idx += 1
        return m
        
    def try_tx_msg(self, slotID, before):
        # 尝试发送在@before时刻之前产生的消息，一次最多可以发送@gl_maxUpPerSlot个。
        assert slotID == self.slotID
        
        msg = self.get_msg_can_tx(slotID, before)
        if msg:
            msg.sort(key=lambda x:x[1], reverse=True) # 按照idx逆序排列，否则del会有问题
            for m, idx in msg:
                m.tx(gl_curRunTime)
                self.msgNoIterList.append(m)
                del self.msgList[idx]
                
    def finalize_simulation(self):
        self.msgList += self.msgNoIterList
        self.msgNoIterList == []
        
        self.msgNum = len(self.msgList)  # 总共的消息数
        self.msgTx = 0.0                # 发送出去的消息数
        self.avgDelay = 0.0
        self.txDuration = 0.0
        self.rxDuration = 0.0
        self.powerConsumption = 0.0
        
        for msg in self.msgList:
            if msg.txTime is not None:
                self.msgTx += 1
                self.avgDelay += msg.txTime - msg.genTime
                self.txDuration += msg.txDuration
                self.rxDuration += msg.rxDuration
                self.powerConsumption += msg.powerConsumption
            else:
                self.txDuration += msg.txDuration
                self.rxDuration += msg.rxDuration
                self.powerConsumption += msg.powerConsumption
        
        self.powerConsumption += (gl_totalRunTime - self.txDuration - self.rxDuration) * AMP_SLEEP 
        if self.msgTx > 0:
            self.avgDelay /= self.msgTx
        else:
            self.avgDelay = None
            
        self.simulationFinished = True
        
    def get_simulation_result(self):
        assert self.simulationFinished
        return (self.powerConsumption, self.avgDelay, self.msgTx, self.msgNum)


def GatewaySchedulerRunTDMA():
    r"""调度器，负责运行 TDMA。
    """
    init_simulation_state()
    
    global gl_curRunTime
    gl_curRunTime = 0
    
    nodesUp   = []
    for i in range(gl_nodesUpNum):
        nodesUp.append(NodeUp(gl_avgEvent))

    curSlotID = -1
    while gl_curRunTime < gl_totalRunTime:
        if gl_curRunTime % gl_slotDuration == 0:
            curSlotID += 1  # [0, gl_nodesUpNum)
            curSlotID %= gl_nodesUpNum
            
            nodeUp = gl_slotID_node_mapping[curSlotID]
            assert isinstance(nodeUp, NodeUp)
            
            nodeUp.try_tx_msg(curSlotID, gl_curRunTime)
            
        gl_curRunTime += 1
        
    # 仿真完成，搜集仿真结果
    powerList = []
    delayList = []
    msgNumList = []
    txNumList = []

    for nodeUp in nodesUp:
        nodeUp.finalize_simulation()
        power, delay, tx, num = nodeUp.get_simulation_result()
        
        if delay:
            delayList.append(delay)
        powerList.append(power)
        msgNumList.append(num)
        txNumList.append(tx)
    
    return (sum(powerList)/len(powerList)*1000/gl_totalRunTime, # power current -uA
            sum(delayList)/len(delayList),
            sum(msgNumList)/len(msgNumList),
            sum(txNumList)/len(txNumList)) 
        
###############################################################################
# LPW simulation
###############################################################################

class DownMsg(object):
    r"""下行节点的消息。
    """
    def __init__(self, id, t):
        self.nodeID = id
        self.genTime = t
        self.txTime = None  # 在网关认为的空闲时间槽里发送；本仿真里直接判定为发送成功
        self.ttl = gl_downMsgLiveTime

    def tx(self, t):
        assert self.txTime is None
        self.txTime = t

def finish_all_downlink_nodes_init_hook():
    global gl_allDownlinkMsg
    assert gl_allDownlinkMsg != []
    gl_allDownlinkMsg.sort(key=lambda x:x.genTime)  # 按照genTime排序

class NodeDown(object):
    r"""下行节点
    """
    def __init__(self, avgDown):
        self.id = gen_saddr()
        # 每个下行节点都工作在一个125khz的channel上，用于避免频繁被长前导码唤醒
        self.channel = self.id % gl_downChannelNum
        gl_nodeID_node_mapping[self.id] = self
        try:
            gl_channel_nodes_mapping[self.channel].append(self)
        except:
            gl_channel_nodes_mapping[self.channel] = []
            gl_channel_nodes_mapping[self.channel].append(self)
        
        self.randStart = randint(0, gl_nodeInitSpan)
        
        self.avg = avgDown     # 上行消息间的时间间隔（泊松分布期望值）
        self.eventMsgGenTime = gen_possion_msg_sequence(self.avg, 
                                            gl_totalRunTime - self.randStart - gl_nodesUpNum*gl_slotDuration)
        
        self.msgList = []
        for t in self.eventMsgGenTime:
            # 所有msg的genTime时间是严格递增的
            msg = DownMsg(self.id, self.randStart + t)
            gl_allDownlinkMsg.append(msg)
            self.msgList.append(msg)    # 用于后续的统计分析
            
        logger.debug(time_prefix() + "NodeDown inited: 0x%X")

        self.simulationFinished = False
        self.powerConsumption = 0.0
        self.rxDuration = 0.0
        self.txDuration = 0.0
        
        self.simulationFinished = False
        
    def wakeup_and_sleep(self):
        # 被唤醒但消息目的地不是本节点
        self.powerConsumption += (gl_longPreambleDuration/2)*AMP_RX # 收听前导码的平均时长等于前导码长度的一半
        self.powerConsumption += POWER_CONSUMPTION_CAD_PREAMBLE_SUFFIX
        self.rxDuration += (gl_longPreambleDuration/2) + DURATION_CAD_HAS_PREAMBLE_SUFFIX
    
    def wakeup_and_rx(self):
        # 被唤醒接收消息帧
        self.powerConsumption += (gl_longPreambleDuration/2)*AMP_RX
        self.powerConsumption += POWER_CONSUMPTION_RX_DOWNLINK + POWER_CONSUMPTION_TX_ACK
        self.rxDuration += (gl_longPreambleDuration/2) + DURATION_DOWNLINK
        self.txDuration += DURATION_ACK
        
    def finalize_simulation(self):
        self.msgNum = len(self.msgList)
        self.msgTx = 0.0
        self.avgDelay = 0.0
        
        for msg in self.msgList:
            assert isinstance(msg, DownMsg)
            if msg.txTime:
                self.msgTx += 1
                self.avgDelay += msg.txTime - msg.genTime + DURATION_DOWNLINK # 这里再加上空中传输时间
        
        if self.msgTx > 0:
            self.avgDelay /= self.msgTx
        else:
            self.avgDelay = None
            
        cad_time = (gl_totalRunTime - self.rxDuration - self.txDuration) / gl_longPreambleDuration
        sleep_time = (gl_totalRunTime - self.rxDuration - self.txDuration) - cad_time
        self.powerConsumption += (AMP_RX*DURATION_CAD_NO_PERAMBLE)*cad_time + AMP_SLEEP*sleep_time
        
        self.simulationFinished = True
    
    def get_simulation_result(self):
        assert self.simulationFinished
        return (self.powerConsumption, self.avgDelay, self.msgTx, self.msgNum)
    
def GatewaySchedulerRunLPW():
    r"""调度器，负责运行 LPW。
    """
    init_simulation_state()
    
    global gl_curRunTime
    gl_curRunTime = 0
    
    nodesDown = []
    for i in range(gl_nodesDownNum):
        nodesDown.append(NodeDown(gl_avgDown))
    finish_all_downlink_nodes_init_hook()
    
    while gl_curRunTime < gl_totalRunTime and len(gl_allDownlinkMsg) > 0:
        msg = gl_allDownlinkMsg[0]
        assert isinstance(msg, DownMsg)
        
        if gl_curRunTime <= msg.genTime + msg.ttl:
            gl_curRunTime = msg.genTime if gl_curRunTime < msg.genTime else gl_curRunTime
            # 处理这个下行消息
            nodeDown = gl_nodeID_node_mapping[msg.nodeID]
            assert isinstance(nodeDown, NodeDown)
            
            otherNodes = gl_channel_nodes_mapping[nodeDown.channel]
            for n in otherNodes:
                n.wakeup_and_sleep()
            
            msg.tx(gl_curRunTime)
            nodeDown.wakeup_and_rx()
            
        del gl_allDownlinkMsg[0]
        gl_curRunTime += gl_longPreambleDuration + DURATION_DOWNLINK + DURATION_ACK
    
    
    # 仿真完毕，开始搜集仿真结果
    powerList = []
    delayList = []
    msgNumList = []
    txNumList = []
    
    for nodeDown in nodesDown:
        nodeDown.finalize_simulation()
        power, delay, tx, num = nodeDown.get_simulation_result()
        
        if delay:
            delayList.append(delay)
        powerList.append(power)
        msgNumList.append(num)
        txNumList.append(tx)
    
    return (sum(powerList)/len(powerList)*1000/gl_totalRunTime, # power current -uA
            sum(delayList)/len(delayList),
            sum(msgNumList)/len(msgNumList),
            sum(txNumList)/len(txNumList))
    
def GatewaySchedulerRun():
    print(GatewaySchedulerRunTDMA())
    print(GatewaySchedulerRunLPW())
    
if __name__ == '__main__':
    #####################################
    # 仿真的基本配置参数
    gl_slotDuration = 500   # ms
    gl_maxUpPerSlot = 2     # 单个时间槽里可以捆绑发送的上行消息个数
    
    gl_longPreambleDuration = 500   # LPW长前导码的持续时间 (ms)
    
    gl_downMsgLiveTime = 3600*1000  # 每个下行消息的存活时间，如果在这个时间内没有推送下去，就删除掉
    gl_downChannelNum = 8           # 将所有LPW节点查收长前导码的频段，划分为8个子频段，避免被频繁唤醒

    gl_nodeInitSpan = 600*1000  # 节点在仿真时间的前面这段时间内完成初始化
    gl_avgEvent = 300*1000      # ms
    gl_avgDown  = 600*1000
    gl_batteryCapacity = 2500   # mAh
    
    gl_nodesUpNum   = 300   # 上行TDMA节点数量（被分配固定的时间槽用于数据交互）
    gl_nodesDownNum = 500   # 下行LPW节点数量（不分配固定的时间槽）
    #####################################
    
    GatewaySchedulerRun()
    
    
