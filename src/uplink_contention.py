#-*- coding: utf-8 -*-
# jtuki@foxmail.com

r"""针对上行竞争接入的FHSS策略做一些仿真。
"""

from random import randint
from simple_logger import get_logger

logger = get_logger()

def calc_ratio1():
    r"""随机选择时间槽，不按照 uFrameSlots 的倍数来选择起始时间槽位置。
    note: 问题在于虽然有时间槽，但并非单个时间槽里可以完成全部消息的发送，不够类似 slotted CSMA。
    """
    slotList = []
    
    for i in range(numNodes):
        slotList.append(randint(1, totalUplinkSlots-uFrameSlots+1))
    slotList.sort()
    
    slotOk = []
    i = 0
    while i < numNodes:
        slotOk.append(slotList[i])
        curSlot = slotList[i]
        i += 1
        while i < numNodes and (slotList[i] - curSlot) < uFrameSlots:
            i += 1
            
    return (len(slotList), len(slotOk), slotList, slotOk, len(slotOk)*uFrameSlots / totalUplinkSlots)
    
def calc_ratio2():
    r"""按照 uFrameSlots 的倍数来选择起始时间槽位置。
    note: 问题在于只有简单假设「所有落在同一个时间槽里的消息，有且仅有一个可以发送成功」，但忽略了「可能都发送失败」的情况。
    """
    slotList = []
    
    for i in range(numNodes):
        slotList.append(int(randint(1, totalUplinkSlots-uFrameSlots+1) / uFrameSlots) * uFrameSlots)
    slotList.sort()
    
    slotOk = []
    i = 0
    while i < numNodes:
        slotOk.append(slotList[i])
        curSlot = slotList[i]
        i += 1
        while i < numNodes and (slotList[i] - curSlot) < uFrameSlots:
            i += 1
            
    return (len(slotList), len(slotOk), slotList, slotOk, len(slotOk)*uFrameSlots / totalUplinkSlots)
    
def calc_ratio3():
    r"""按照 uFrameSlots 的倍数来选择起始时间槽位置。
    note: 按照先选择大的时间槽再选择 sub 时间槽的办法。在同一个时间槽里，如果最前面的 sub 时间槽出现了两个消息，则全部算作丢弃。
    """
    slotList = []   # ()
    
    for i in range(numNodes):
        slot1 = int(randint(1, totalUplinkSlots-uFrameSlots+1) / uFrameSlots) * uFrameSlots
        slot2 = randint(1, uSubFrameSlots)
        slotList.append((slot1, slot2))
    slotList.sort(key=lambda x:x[0])
    
    slotOk = []
    i = 0
    while i < numNodes:
        frames = []     # 所有落在同一个大slot里的数据帧
        frames.append(slotList[i])
        
        s = frames[-1][0]   # 获取slot编号
        i += 1
        while i < numNodes and slotList[i][0] == s:
            frames.append(slotList[i])
            i += 1
            
        if len(frames) > 1:
            frames.sort(key=lambda x:x[1])
            if frames[0][1] != frames[1][1]:
                # 每个slot里只有第一个占据了不和别人重复的sub时间槽的才可能发送成功
                slotOk.append(frames[0])
        else: # only one item
            slotOk.append(frames[0])
            
    return (len(slotList), len(slotOk), slotList, slotOk, len(slotOk)*uFrameSlots / totalUplinkSlots)
    
if __name__ == '__main__':
    runTimes = 5000
    
    numNodes = None
    numNodesList = [n for n in range(101, 200)]
    totalUplinkSlots = 100  # 所有竞争的时间槽数量
    uFrameSlots = 4         # 每个上行消息占据的时间槽数量
    uSubFrameSlots = 3      # 在 calc_ratio3 中，每个时间槽的前面部分再细分了 uSubFrameSlots 个子槽。

    logger.info("numNodesList: %s" % numNodesList)
    for num in numNodesList:
        numNodes = num
        k = 0
        for i in range(runTimes):
            r = calc_ratio3()
            k += r[1]
        k = k/runTimes
        logger.info("%f, " % k)
    