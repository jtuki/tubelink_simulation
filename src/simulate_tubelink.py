#-*- coding: utf-8 -*-
# jtuki@foxmail.com

r"""针对TubeLink做一些仿真验证。
"""

gl_bcnDuration = 8000       # 信标周期的长度
gl_packedAckDelay = 2       # 延迟查收ack的信标周期间隔数量
gl_evtCollisionDelay = 3    # 冲突之后的上行事件消息在 [1, gl_evtCollisionDelay] 个信标周期后再次发送
gl_emergCollisionDelay = 2
gl_totalSlots = 128         # 一个信标周期里所有的时间槽数量
gl_slotDuration = gl_bcnDuration/gl_totalSlots 

gl_bcnSlots = 6        # 信标段所占据的时间槽数量    
gl_dFrameSlots = 6     # 每个下行消息占据的时间槽数量
gl_uFrameSlots = 4     # 每个上行消息占据的时间槽数量
gl_subFrameSlots = 3   # 每个gl_uFrameSlots前面的部分再次细分的时间槽

# 功耗开销参数
# 电流
AMP_TX = 120    # mA
AMP_RX = 10
AMP_SLEEP = 0.005
# 时长
DURATION_BCN = 500  # ms
DURATION_UPLINK = 200
DURATION_DOWNLINK = 300 # 留了一些给guard interval
DURATION_ACK    = 80
# 单次收发功耗开销
POWER_CONSUMPTION_TRACK_BCN     = AMP_RX * DURATION_BCN         # mA*ms
POWER_CONSUMPTION_RX_DOWNLINK   = AMP_RX * DURATION_DOWNLINK
POWER_CUNSUMPTION_ACK           = AMP_TX * DURATION_ACK
POWER_CONSUMPTION_TX_UPLINK     = AMP_TX * DURATION_UPLINK

# 总共的运行时间(ms)
gl_totalRunTime = 3600*10*1000
gl_curRunTime = 0           # 当前的仿真运行时间 (ms)
gl_virtualBcnSeqID = -1     # 不断持续递增的、专门用于仿真的信标序列号

from random import randint
import numpy as np

from simple_logger import get_logger

logger = get_logger()

gl_nodeID_node_mapping = {}     # nodeID => NodeUp或者NodeDown节点

gl_vbcn_node_mapping = {}       # gl_virtualBcnSeqID => [nodeID ...]
                                # 这个信标周期里可能有上行的节点，加速仿真速度

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
    
def gen_saddr():
    r"""针对一个网关下的所有节点，分配不重复的短地址
    """
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
    return saddr

def time_prefix():
    r"""显示当前的仿真时间做为日志前缀
    """
    return "%12s:" % str(gl_curRunTime)

class NodeMsg(object):
    r"""传感上报类型节点的消息。
    """
    def __init__(self, id, type, gen):
        assert type in ['event', 'emerg']
        self.nodeID = id        # 节点的ID编号
        self.type = type        # 'event' | 'emerg'
        self.genTime = [gen]    # 消息产生的时间，每次tx_fail时会认为是再次生成一个msg
        self.updateGenTimeHook()
        self.txTime = []        # 尝试发送的时间
        

        self.tryTx = True       # 是否尝试发送
        self.discard = False    # @gl_maxTxTimes次发送依然失败后，丢失消息，并将discard置True 
        
        # @powerConsumtion - 这里的基本假设是节点内的所有上行消息的能耗开销，等于节点本身的能耗开销。
        self.powerConsumption = 0   # 在此消息上的功耗开销
        self.rxDuration = 0     # 用于统计节点rx的时长
        self.txDuration = 0     # 用于统计节点tx的时长
        
    def updateGenTimeHook(self):
        # 更新了消息的genTime之后，更新 gl_vbcn_node_mapping 映射里的内容
        vbcn = int(self.genTime[-1] / gl_bcnDuration) + 1
        if vbcn not in gl_vbcn_node_mapping:
            gl_vbcn_node_mapping[vbcn] = []
        if self.nodeID not in gl_vbcn_node_mapping[vbcn]:
            gl_vbcn_node_mapping[vbcn].append(self.nodeID)
    
    def can_tx(self, bcnClassID):
        r"""检查是否可以在当前的信标周期下发送。
        """
        # 当前信标周期的起始时间
        periodStart = gl_virtualBcnSeqID*gl_bcnDuration
        
        if (self.tryTx and not self.discard
            and self.genTime[-1] <= periodStart 
            and periodStart - self.genTime[-1] < gl_bcnDuration):
            # 检查信标周期分组的约束
            if self.nodeID % gl_bcnClassesNum == bcnClassID or self.type == 'emerg':
                return True
            else:
                self.genTime.append(self.genTime[-1] + gl_bcnDuration)
                self.updateGenTimeHook()
                return False
        elif self.tryTx == False:
            return None
        else:
            return False
        
    def tx_fail(self, t):
        assert self.tryTx == True and self.discard == False
        self.txDuration += DURATION_UPLINK
        self.rxDuration += 2*DURATION_BCN

        # 两次跟踪bcn的功耗开销(tx & ack) + 发送上行数据的开销
        self.powerConsumption += 2*POWER_CONSUMPTION_TRACK_BCN + POWER_CONSUMPTION_TX_UPLINK
        
        self.txTime.append(t)
        if len(self.txTime) >= gl_maxTxTimes:
            self.tryTx = False
            self.discard = True
        else:
            # 模拟在delayed信标周期里查看packedACK没有找到的场景
            if self.type == 'event':
                self.genTime.append(t + gl_bcnDuration*(gl_packedAckDelay 
                                                        + randint(1, gl_evtCollisionDelay)
                                                        + pow(2, len(self.txTime))))
                self.updateGenTimeHook()
            else:
                self.genTime.append(t + gl_bcnDuration*(gl_packedAckDelay 
                                                        + randint(1, gl_emergCollisionDelay)
                                                        + pow(2, len(self.txTime))))
                self.updateGenTimeHook()
        
    def tx_ok(self, t):
        assert self.tryTx == True and self.discard == False
        self.txDuration += DURATION_UPLINK
        self.rxDuration += 2*DURATION_BCN
        self.powerConsumption += 2*POWER_CONSUMPTION_TRACK_BCN + POWER_CONSUMPTION_TX_UPLINK
        
        self.txTime.append(t)
        self.tryTx = False
        
    def delay_gentime(self):
        r"""仅仅是往后延迟一个周期，比如当前的周期里节点有两个消息要发送时，就要选择一个往后延迟。
        """
        self.genTime.append(self.genTime[-1] + gl_bcnDuration)
        self.updateGenTimeHook()
        
class NodeUp(object):
    r"""传感上报类型的节点。
    """
    def __init__(self, avgEvent, avgEmerg):
        self.id = gen_saddr()
        self.randStart = randint(0, gl_nodeInitSpan)
        
        gl_nodeID_node_mapping[self.id] = self
        self.avg = (avgEvent, avgEmerg)     # 上行消息间的时间间隔（泊松分布期望值）
        
        self.eventMsgGenTime = gen_possion_msg_sequence(self.avg[0], 
                                            gl_totalRunTime - self.randStart
                                            - gl_bcnDuration*(gl_packedAckDelay+gl_evtCollisionDelay))
        self.emergMsgGenTime = gen_possion_msg_sequence(self.avg[1],
                                            gl_totalRunTime - self.randStart
                                            - gl_bcnDuration*(gl_packedAckDelay+gl_evtCollisionDelay))
        
        self.msgList = []   # 所有的上行消息对象
        self.msgNoIterList = [] # 所有不再参与后续遍历搜索的消息对象
        
        for t in self.eventMsgGenTime:
            self.msgList.append(NodeMsg(self.id, 'event', self.randStart + t))
        for t in self.emergMsgGenTime:
            self.msgList.append(NodeMsg(self.id, 'emerg', self.randStart + t))
            
        logger.debug(time_prefix() + "NodeUp inited: 0x%X, eventNum %d, emergNum %d" 
                     % (self.id, len(self.eventMsgGenTime), len(self.emergMsgGenTime)))
        
    def get_msg_can_tx(self, bcnClassID):
        r"""获取可以在当前信标周期下发送的消息。如果有多个就选择一个，其余的往后排。
        """
        tx_msg = []
        i = 0
        del_idx = []
        for msg in self.msgList:
            can = msg.can_tx(bcnClassID)
            if can == True:
                tx_msg.append(msg)
            elif can == None:
                del_idx.append(i)
                self.msgNoIterList.append(msg)
            i += 1
        
        # 删除所有已经不再需要遍历的消息对象
        del_idx.sort(reverse=True)
        for i in del_idx:
            del self.msgList[i]
        
        if len(tx_msg) > 1:
            for i in range(1, len(tx_msg)):
                tx_msg[i].delay_gentime()
        
        if len(tx_msg) > 0:
            return tx_msg[0]
        else:
            return None

class DownMsg(object):
    def __init__(self, id, genTime, bcnDown):
        self.nodeID = id
        self.bcnDown = bcnDown
        self.genTime = [genTime]    # 每次tx_buf_full()情况下，推迟下行消息的发送
        self.txTime = None          # 当发送成功时，将此时间设置成发送时间
        
    def can_tx(self):
        periodStart = gl_virtualBcnSeqID*gl_bcnDuration
        if (self.txTime is None 
            and len(self.genTime) < gl_maxDownTimes  # 最多延后 gl_maxDownTimes 次数
            and self.genTime[-1] <= periodStart
            and periodStart - self.genTime[-1] < self.bcnDown*gl_bcnDuration):
            return True
        else:
            return False
        
    def tx_ok(self, t):
        assert t > self.genTime[-1]
        self.txTime = t
    
    def tx_buf_full(self):
        r"""由于网关下行buffer已满，因此需要往后推延
        """
        self.genTime.append(self.genTime[-1] + self.bcnDown*gl_bcnDuration
                            + (pow(2, len(self.genTime)) + randint(1, gl_evtCollisionDelay))*gl_bcnDuration)
        
class NodeDown(object):
    r"""消息下发类型的节点。
    """
    def __init__(self, bcnDown, avgDown):
        self.id = gen_saddr()
        self.randStart = randint(0, gl_nodeInitSpan)
        
        gl_nodeID_node_mapping[self.id] = self
        
        self.bcnDown = bcnDown      # 节点每隔多少个信标周期查看一次是否有下行消息
        assert 128 % bcnDown == 0   # beacon序列号按照[0~127]为循环，@bcnDown 需要可以被128整除
        self.avgDown = avgDown      # 网关给本节点发送下行消息的消息间间隔的泊松分布的期望值
        
        self.rxDuration = 0         # 节点rx的时长，跟踪信标+接收下行消息
        self.txDuration = 0         # 节点tx的时长，收到下行消息后反馈ack
        self.powerConsumption = 0   # 本节点的功耗开销
        
        self.downMsgGenTime = gen_possion_msg_sequence(avgDown, gl_totalRunTime-self.randStart)
        
        self.downMsgList = []       # 所有的下行消息对象
        for t in self.downMsgGenTime:
            self.downMsgList.append(DownMsg(self.id, self.randStart + t, self.bcnDown))
        
        # 注册入网时和TubeLink服务器侧约定的查收下行的信标周期序列号起始值（[0, gl_bcnDown] 取随机值）
        self.registerBcnSeqID = randint(0, self.bcnDown-1)
        self.checkBcnSeqID = []     # 检查下行消息的信标周期序列号
        
        k = self.registerBcnSeqID
        while k < 128:
            self.checkBcnSeqID.append(k)
            k += self.bcnDown
        assert len(self.checkBcnSeqID) == int(128 / self.bcnDown) 
        
        logger.debug(time_prefix() + "NodeDown inited: 0x%X, downMsgNum %d" %
                     (self.id, len(self.downMsgList)))
        
    def is_check_downlink(self, bcnSeqID):
        if bcnSeqID in self.checkBcnSeqID:
            return True
        else:
            return False
        
    def get_downlink_msg(self, bcnSeqID):
        rx_msg = []
        for msg in self.downMsgList:
            if msg.can_tx():
                rx_msg.append(msg)
                
        if len(rx_msg) > 1:
            for i in range(1, len(rx_msg)):
                rx_msg[i].tx_buf_full()     # 本仿真约定：每个节点在单个信标周期里只接收一个下行消息
        
        if len(rx_msg) > 0:
            return rx_msg[0]
        else:
            return None
        
    def check_downlink_no_msg(self):
        self.rxDuration += DURATION_BCN
        self.powerConsumption += POWER_CONSUMPTION_TRACK_BCN
    
    def check_downlink_has_msg(self, msg, t):
        assert isinstance(msg, DownMsg)
        assert msg.txTime is None
        
        msg.tx_ok(t)
        
        self.rxDuration += DURATION_BCN + DURATION_DOWNLINK
        self.txDuration += DURATION_UPLINK
        # 接收下行消息+ack的开销
        self.powerConsumption += (POWER_CONSUMPTION_TRACK_BCN + 
                                  POWER_CONSUMPTION_RX_DOWNLINK + 
                                  POWER_CUNSUMPTION_ACK)

def GatewaySchedulerRun(check_variables):
    r"""调度器。负责定时发出信标；将可以发出去的下行消息，发出去；接收上行消息。
    """
    global gl_curRunTime
    global gl_virtualBcnSeqID
    
    gl_curRunTime = 0
    
    bcnSeqID = -1   # 初始化根据lollipop序列方式，从负数-127开始，这里假设初始就已经是-1
    gl_virtualBcnSeqID = -1
    bcnClassID = 0  # 信标周期分组，使用0做为起始值，参见 @gl_bcnClassesNum
    
    nodesUp   = []
    nodesDown = []
    
    for i in range(gl_nodesUpNum):
        nodesUp.append(NodeUp(gl_avgEvent, gl_avgEmerg))
    for i in range(gl_nodesDownNum):
        nodesDown.append(NodeDown(gl_bcnDown, gl_avgDown))
    
    # 开始仿真
    while gl_curRunTime <= gl_totalRunTime:
        if gl_curRunTime % gl_bcnDuration == 0:
            # 处理当前的信标周期
            bcnSeqID = (bcnSeqID+1) % 128
            gl_virtualBcnSeqID += 1
            bcnClassID = (bcnClassID+1) % gl_bcnClassesNum
            
            logger.debug(time_prefix() + "START bcnPeriod %d bcnClassID %d" % (bcnSeqID, bcnClassID))
            
            # 检查所有的下行节点
            down_msg = []
            
            for downNode in nodesDown:
                assert isinstance(downNode, NodeDown)
                if downNode.is_check_downlink(bcnSeqID):
                    msg = downNode.get_downlink_msg(bcnSeqID)
                    if msg:
                        down_msg.append(msg)
                    else:
                        downNode.check_downlink_no_msg()
            
            if len(down_msg) > gl_maxDownlinkMsg:
                # 网关本信标周期的下行缓冲超过限值
                for i in range(gl_maxDownlinkMsg, len(down_msg)):
                    down_msg[i].tx_buf_full()
                    downNode = gl_nodeID_node_mapping[down_msg[i].nodeID]
                    downNode.check_downlink_no_msg()
                down_msg = down_msg[:gl_maxDownlinkMsg]
            
            t = gl_curRunTime + gl_slotDuration*gl_bcnSlots
            for msg in down_msg:
                assert isinstance(msg, DownMsg)
                downNode = gl_nodeID_node_mapping[msg.nodeID]
                t += gl_slotDuration*gl_dFrameSlots
                downNode.check_downlink_has_msg(msg, t)
            
            gl_curRunTime = t
            
            logger.debug(time_prefix() + "bcnPeriod %7d: len(down_msg): %d" 
                         % (bcnSeqID, len(down_msg)))
            
            # 剩余的供上行消息段使用的时间槽数量
            remainSlots = gl_totalSlots - gl_bcnSlots - gl_dFrameSlots*len(down_msg)
            
            # 检查所有的上行节点
            uplink_msg = []
            
            if gl_virtualBcnSeqID in gl_vbcn_node_mapping: # 否则当前没有节点有消息发送
                for id in gl_vbcn_node_mapping[gl_virtualBcnSeqID]:
                    upNode = gl_nodeID_node_mapping[id]
                    assert isinstance(upNode, NodeUp)
                    msg = upNode.get_msg_can_tx(bcnClassID)
                    if msg:
                        uplink_msg.append(msg)
            
            logger.debug(time_prefix() + "bcnPeriod %7d: len(uplink_msg): %d" 
                         % (bcnSeqID, len(uplink_msg)))
                    
            if len(uplink_msg) > 0:
                # 在上行消息段里，节点随机选择时间槽，然后发送数据，使用FHSS，没有CAD过程
                # 参见 @gl_uFrameSlots
                slotList = []   # (slotID, msg)元组构成的列表
                
                for msg in uplink_msg:
                    assert isinstance(msg, NodeMsg)
                    # remainSlots减去gl_uFrameSlots的原因是给最后一段保留一个上行时间，避免和下个信标冲突
                    slot1 = int(randint(1, remainSlots-gl_uFrameSlots+1) / gl_uFrameSlots) * gl_uFrameSlots
                    slot2 = randint(1, gl_subFrameSlots)
                    slotList.append((slot1, msg, slot2))
                slotList.sort(key=lambda x:x[0])
                
                slotOk = []     # 成功发送的slot
                slotFailed = [] # 没有被收到的slot
                
                i = 0
                while i < len(slotList):
                    frames = []
                    frames.append(slotList[i])
                    s = frames[-1][0]
                    i += 1
                    while i < len(slotList) and slotList[i][0] == s:
                        frames.append(slotList[i])
                        i += 1
                    if len(frames) > 1:
                        frames.sort(key=lambda x:x[2])
                        if frames[0][2] != frames[1][2]:
                            slotOk.append(frames[0])
                        else:
                            slotFailed.append(frames[0])
                        slotFailed += frames[1:]    # 每个slot里只有第一个占据了不和别人重复的sub时间槽的才可能发送成功
                    else:
                        slotOk.append(frames[0])
                        
                assert len(slotOk) + len(slotFailed) == len(slotList)
                
                for slot, msg, _ in slotOk:
                    t = gl_curRunTime + slot*gl_slotDuration
                    msg.tx_ok(t)
                for slot, msg, _ in slotFailed:
                    t = gl_curRunTime + slot*gl_slotDuration
                    msg.tx_fail(t)
                    
                logger.debug(time_prefix() +
                             "bcnPeriod %7d: len(uplink_msg): %d, "
                             "len(slotOk): %d, len(slotFailed): %d" 
                             % (bcnSeqID, len(uplink_msg), len(slotOk), len(slotFailed)))
            
        gl_curRunTime = int(gl_curRunTime)
        gl_curRunTime += 1  # 使用1ms做为仿真步进
    
    logger.debug(time_prefix() + "simulate FINISH!")
        
    # 仿真结果搜集预处理
    for upNode in nodesUp:
        upNode.msgList += upNode.msgNoIterList    
        
    # 仿真完成
    # 搜集传感上报类型节点的仿真结果
    upPowerList = []    # 节点的能量开销列表
    upDelayList = []    # 节点的上行事件消息平均延迟、以及紧急消息平均延迟列表 (可能有None存在)
    upTxNumList = []    # 节点的上行事件消息平均发送次数、以及紧急消息平均发送次数 (可能有None存在)
    upMsgNumList = []   # 节点的上行事件消息个数、以及紧急消息个数
    upMsgFailList = []  # 节点的上行事件消息发送失败个数、以及紧急消息的发送失败个数
    
    for upNode in nodesUp:
        # 功耗开销
        sleepDuration = 0
        rxDuration = 0
        txDuration = 0
        powerConsumption = 0    # mA*ms
        
        for msg in upNode.msgList:
            rxDuration += msg.rxDuration
            txDuration += msg.txDuration
            powerConsumption += msg.powerConsumption
        
        sleepDuration = gl_totalRunTime - (rxDuration + txDuration)
        powerConsumption += sleepDuration*AMP_SLEEP
        
        upPowerList.append((upNode, powerConsumption))
        
        # 延迟，发送次数，总体个数，失败个数
        eventDelay = []
        emergDelay = []
        
        eventTxNum = []
        emergTxNum = []
        
        eventMsgNum = 0
        emergMsgNum = 0 
        
        eventFailNum = 0
        emergFailNum = 0
        
        for msg in upNode.msgList:
            if msg.type == 'event':
                eventMsgNum += 1
                if msg.discard == False and msg.tryTx == False: # 发送成功
                    eventDelay.append(msg.txTime[-1] - msg.genTime[0])
                    eventTxNum.append(len(msg.txTime))
                else:
                    eventFailNum += 1
            else:
                assert msg.type == 'emerg'
                emergMsgNum += 1
                if msg.discard == False and msg.tryTx == False: # 发送成功
                    emergDelay.append(msg.txTime[-1] - msg.genTime[0])
                    emergTxNum.append(len(msg.txTime))
                else:
                    emergFailNum += 1
        
        upDelayList.append((upNode, 
                            sum(eventDelay) / len(eventDelay) if eventDelay else None, 
                            sum(emergDelay) / len(emergDelay) if emergDelay else None))
        upTxNumList.append((upNode, 
                            sum(eventTxNum) / len(eventTxNum) if eventTxNum else None, 
                            sum(emergTxNum) / len(emergTxNum) if emergTxNum else None))
        upMsgNumList.append((upNode, eventMsgNum, emergMsgNum))
        upMsgFailList.append((upNode, eventFailNum, emergFailNum))
        
    # 搜集消息下发类型节点的仿真结果
    downPowerList = []      # 节点的能量开销列表
    downDelayList = []      # 节点的下行消息平均延迟 (可能有None存在)
    downTxNumList = []      # 节点的下行消息平均推后次数 (可能有None存在)
    downMsgNumList = []     # 节点的下行消息个数
    downMsgFailList = []    # 节点的下行消息失败个数（推后多次被丢弃的）
    
    for downNode in nodesDown:
        # 功耗开销
        sleepDuration = gl_totalRunTime - (downNode.rxDuration + downNode.txDuration)
        powerConsumption = sleepDuration*AMP_SLEEP + downNode.powerConsumption    # mA*ms
        
        downPowerList.append((downNode, powerConsumption))
        
        # 延迟，推后次数，消息个数，失败个数
        downDelay = []
        downTxNum = []
        downMsgNum = 0
        downMsgFailNum = 0  
        
        for dmsg in downNode.downMsgList:
            assert isinstance(dmsg, DownMsg)
            downMsgNum += 1
            if dmsg.txTime is None: # 发送失败
                downMsgFailNum += 1
            else:
                downDelay.append(dmsg.txTime - dmsg.genTime[0])
                downTxNum.append(len(dmsg.genTime))
                
        downDelayList.append((downNode,
                              sum(downDelay) / len(downDelay) if downDelay else None))
        downTxNumList.append((downNode,
                              sum(downTxNum) / len(downTxNum) if downTxNum else None))
        downMsgNumList.append((downNode, downMsgNum))
        downMsgFailList.append((downNode, downMsgFailNum))
                
    # 汇总结果
    avgPowerNodeUp = 0.0        # 传感上报节点的平均功耗开销
    avgPowerNodeDown = 0.0      # 消息下发节点的平均功耗开销
    avgLifeNodeUp = 0.0
    avgLifeNodeDown = 0.0
    
    avgEventDelay = 0.0         # 平均上行事件消息的延迟（每节点）
    avgEmergDelay = 0.0         # 平均上行紧急消息的延迟
    avgEventTxNum = 0.0         # 平均每个发送成功的上行事件消息的发送次数
    avgEmergTxNum = 0.0         # 平均每个发送成功的上行紧急消息的发送次数
    avgEventMsgNum = 0.0        # 平均上行事件消息的数量
    avgEmergMsgNum = 0.0        # 平均上行紧急消息的数量
    avgEventMsgFailed = 0.0     # 平均发送失败的上行事件消息的数量
    avgEmergMsgFailed = 0.0     # 平均发送失败的上行紧急消息的数量

    avgDownDelay = 0.0          # 平均下行消息的延迟
    avgDownTxNum = 0.0          # 平均的下行消息推后次数
    avgDownMsgNum = 0.0         # 平均的下行消息总数
    avgDownMsgFailNum = 0.0     # 平均的下行消息发送失败总数
    
    
    # avgPowerNodeUp, avgPowerNodeDown
    for n, power in upPowerList:
        avgPowerNodeUp += power
    avgPowerNodeUp /= len(upPowerList)      # mA*ms
    
    for n, power in downPowerList:
        avgPowerNodeDown += power
    avgPowerNodeDown /= len(downPowerList)  # mA*ms
    
    avgLifeNodeUp   = gl_batteryCapacity*3600*1000 / avgPowerNodeUp * gl_totalRunTime / (3600*1000*24*365)  # year
    avgLifeNodeDown = gl_batteryCapacity*3600*1000 / avgPowerNodeDown * gl_totalRunTime / (3600*1000*24*365)
    
    # avgEventDelay, avgEmergDelay
    ev = 0; em =0
    for n, event, emerg in upDelayList:
        if event:   # 可能是None
            avgEventDelay += event
        else:
            ev += 1
        if emerg:
            avgEmergDelay += emerg
        else:
            em += 1
    
    if avgEventDelay > 0:
        avgEventDelay /= len(upDelayList) - ev
    if avgEmergDelay > 0:
        avgEmergDelay /= len(upDelayList) - em
    
    # avgEventTxNum, avgEmergTxNum
    for n, event, emerg in upTxNumList:
        if event:   # 可能是None
            avgEventTxNum += event
        else:
            ev += 1
        if emerg:
            avgEmergTxNum += emerg
        else:
            em += 1
    
    if avgEventTxNum > 0:
        avgEventTxNum /= len(upTxNumList) - ev
    if avgEmergTxNum > 0:
        avgEmergTxNum /= len(upTxNumList) - em
    
    # avgEventMsgNum, avgEmergMsgNum, avgEventMsgFailed, avgEmergMsgFailed
    for n, ev, em in upMsgNumList:
        avgEventMsgNum += ev
        avgEmergMsgNum += em
        
    for n, ev, em in upMsgFailList:
        avgEventMsgFailed += ev
        avgEmergMsgFailed += em
    
    avgEventMsgNum /= len(upMsgNumList)
    avgEmergMsgNum /= len(upMsgNumList)

    avgEventMsgFailed /= len(upMsgFailList)
    avgEmergMsgFailed /= len(upMsgFailList)
    
    # avgDownDelay
    d = 0
    for n, delay in downDelayList:
        if delay: # 可能是None
            avgDownDelay += delay
        else:
            d += 1
    
    if avgDownDelay > 0:
        avgDownDelay /= len(downDelayList) - d
        
    # avgDownTxNum
    t = 0
    for n, num in downTxNumList:
        if num:
            avgDownTxNum += num
        else:
            t += 1
            
    if avgDownTxNum > 0:
        avgDownTxNum /= len(downTxNumList) - t
    
    # avgDownMsgNum, avgDownMsgFailNum
    for n, num in downMsgNumList:
        avgDownMsgNum += num
    avgDownMsgNum /= len(downMsgNumList)
    
    for n, num in downMsgFailList:
        avgDownMsgFailNum += num
    avgDownMsgFailNum /= len(downMsgFailList)
    
    logger.info("%10.2f, %10.2f, %10.2f, %10.4f, %10.2f, %10.4f" %
                ((avgPowerNodeUp / gl_totalRunTime)*1000, (avgPowerNodeDown / gl_totalRunTime)*1000, # power (uA)
                 avgEventDelay / 1000, 1-(avgEventMsgFailed / avgEventMsgNum),      # upDelay and upOk
                 avgDownDelay / 1000, 1-(avgDownMsgFailNum / avgDownMsgNum)))       # downDelay and downOk
    
    # power                                   
    # logger.info("avgAmpNodeUp,      %f" % (avgPowerNodeUp / gl_totalRunTime))
    # logger.info("avgAmpNodeDown,    %f" % (avgPowerNodeDown / gl_totalRunTime))
    
    # logger.info("avgLifeNodeUp,   %f" % avgLifeNodeUp)
    # logger.info("avgLifeNodeDown, %f" % avgLifeNodeDown)
    
    # upDelay
    # logger.info("avgEventDelay,     %f" % avgEventDelay)
    # logger.info("avgEmergDelay,     %f" % avgEmergDelay)
                                      
    # logger.info("avgEventTxNum,       %f" % avgEventTxNum)
    # logger.info("avgEmergTxNum,       %f" % avgEmergTxNum)
                                      
    # logger.info("avgEventMsgNum,      %f" % avgEventMsgNum)
    # logger.info("avgEventMsgFailed,   %f" % avgEventMsgFailed)
                                      
    # logger.info("avgEmergMsgNum,      %f" % avgEmergMsgNum)
    # logger.info("avgEmergMsgFailed,   %f" % avgEmergMsgFailed)

    # upOk
    # logger.info("avgEventOkRatio,   %f" % (1-(avgEventMsgFailed / avgEventMsgNum)))
    # logger.info("avgEmergOkRatio,   %f" % (1-(avgEmergMsgFailed / avgEmergMsgNum)))
    
    # downDelay
    # logger.info("avgDownDelay,      %f" % avgDownDelay)
        
    # logger.info("avgDownTxNum,        %f" % avgDownTxNum)
    # logger.info("avgDownMsgNum,       %f" % avgDownMsgNum)
    # logger.info("avgDownMsgFailNum,   %f" % avgDownMsgFailNum)
    
    # downOk
    # logger.info("avgDownOkRatio,    %f" % (1-(avgDownMsgFailNum / avgDownMsgNum)))
    
if __name__ == '__main__':
    r"""['power', 'upDelay', 'upOk', 'downDelay', 'downOk']
    """
    #####################################
    # 仿真的基本配置参数
    gl_avgEvent = 300*1000      # ms
    gl_avgEmerg = 3600*99*1000  # 不再分析event和emerg的差别，这里尽量降低emerg的数量，避免对evt的影响
    gl_avgDown  = 600*1000
    gl_nodeInitSpan = 600*1000  # 节点在仿真时间的前面这段时间内完成初始化
    gl_batteryCapacity = 2500   # mAh
    gl_maxTxTimes = 3           # 每个上行消息的最大传输次数（最多重传次数+1）
    gl_maxDownTimes = 10        # 每个下行消息的最大推延次数
    gl_maxDownlinkMsg = 10      # 每个信标周期里最多传输的下行消息数量
    gl_bcnClassesNum = 2        # 信标周期分组的数量
    
    # variables
    gl_bcnDown  = 32            # 消息下发类型的节点每隔多少信标周期检查一次下行消息
    gl_nodesUpNum   = 300
    gl_nodesDownNum = 300
    #####################################
    
    #####################################
    S1 = False
    if S1:
        # 仿真场景1的配置参数 - 更改上行节点数量，验证对上行重传功耗开销、上行丢包率、上行延迟的影响
        gl_nodesUpNum   = None      # [50, 100, 150, 200, 250, 300, 350, 400, 450, 500]
    
        logger.info("=== S1 === gl_nodesUpNum")
        logger.info("%10s, %10s, %10s, %10s, %10s, %10s," %
                    ("ampUp", "ampDown", "upDelay", "upOk", "downDelay", "downOk"))
        for n in [50, 100, 150, 200, 250, 300, 350, 400, 450, 500]:
            gl_nodesUpNum = n
            GatewaySchedulerRun(['power', 'upDelay', 'upOk', 'downDelay', 'downOk'])
            
        gl_nodesUpNum = 300     # 还原默认配置
    #####################################
        
    #####################################
    S2 = False
    if S2:
        # 仿真场景2的配置参数  - 更改下行节点数量，验证对上行段（变短）的丢包率的影响
        gl_bcnDown  = 8
        gl_nodesDownNum = None      # [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
        
        logger.info("=== S2 === gl_nodesDownNum")
        logger.info("%10s, %10s, %10s, %10s, %10s, %10s," %
                    ("ampUp", "ampDown", "upDelay", "upOk", "downDelay", "downOk"))
        for n in [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]:
            gl_nodesDownNum = n
            GatewaySchedulerRun(['power', 'upDelay', 'upOk', 'downDelay', 'downOk'])
            
        # 还原默认值
        gl_nodesDownNum = 300
        gl_bcnDown  = 32
    #####################################
    
    #####################################
    S3 = True
    if S3:
        # 仿真场景3的配置参数 - 更改bcnDown参数，验证对下行节点功耗开销、以及下行延迟的影响
        gl_nodesDownNum = 500
        gl_bcnDown = None   # [4, 8, 16, 32, 64]
        
        logger.info("=== S3 === gl_bcnDown")
        logger.info("%10s, %10s, %10s, %10s, %10s, %10s," %
                    ("ampUp", "ampDown", "upDelay", "upOk", "downDelay", "downOk"))
        for n in [4, 8, 16, 32, 64]:
            gl_bcnDown = n
            GatewaySchedulerRun(['power', 'upDelay', 'upOk', 'downDelay', 'downOk'])
            
        # 还原默认值
        gl_bcnDown = 32
        gl_nodesDownNum = 300
    #####################################
    
    #####################################
    S4 = True
    if S4:
        # 仿真场景4的配置参数 - 压缩初始化的随机性，查看信标周期分组机制（削峰填谷）对上行丢包率的影响
        gl_nodeInitSpan = 10*1000
        gl_bcnClassesNum = None  # [1, 3, 5, 7, 9, 11, 13, 15]
        
        logger.info("=== S4 === gl_bcnClassesNum")
        logger.info("%10s, %10s, %10s, %10s, %10s, %10s," %
                    ("ampUp", "ampDown", "upDelay", "upOk", "downDelay", "downOk"))
        for n in [1, 3, 5, 7, 9, 11, 13, 15]:
            gl_bcnClassesNum = n
            GatewaySchedulerRun(['power', 'upDelay', 'upOk', 'downDelay', 'downOk'])
            
        # 还原默认值
        gl_nodeInitSpan = 600*1000  # 节点在仿真时间的前面这段时间内完成初始化
        gl_bcnClassesNum = 2        # 信标周期分组的数量
    #####################################
    
