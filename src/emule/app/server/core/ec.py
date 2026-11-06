# -*- coding: utf-8 -*-
"""aMule 外部连接协议（EC）客户端 —— 纯标准库实现。

协议依据 aMule 2.3.3 源码（research/amule-ec-src 与上游 src/libs/ec/cpp）：
  * 帧头   ECSocket.cpp : 4 字节 flags + 4 字节长度，均为网络字节序（big-endian）；
                          长度只算 opcode+tag 流，不含 8 字节帧头，上限 16MB
  * tag    ECTag.cpp    : 2 字节 (tagname<<1|hasChildren) + 1 字节 type
                          + 4 字节 taglen + [2 字节子 tag 数 + 子 tag...] + 数据
  * 数值   ECTag.cpp    : tag 内部整数一律 big-endian；字符串带结尾 NUL
  * IP     ECTag.h      : 4 字节分四段 + 2 字节端口（big-endian）
  * 鉴权   ExternalConn.cpp / RemoteConnect.cpp : 两段式（盐 + 口令 MD5 哈希）
  * 回包   ExternalConn.cpp / ECSpecial*Tags.cpp : 各 opcode 的字段与顺序
  * 分块   RLE.cpp      : PART/GAP/REQ 状态是 RLE（可差分）编码的字节流

连接语义：aMule 按顺序处理同一条连接上的请求，所以一个 ECClient 实例 = 一条 socket
+ 一把锁串行化“发一个包、收一个回包”；读超时 10s；socket 出错自动断开，下次请求
自动重连并重新鉴权。后台 reader 线程负责收包，未匹配到请求的推送包按 opcode 分发给
搜索会话（服务端只有在客户端声明 EC_TAG_CAN_NOTIFY 时才推送，我们默认不声明）。
"""

import hashlib
import queue
import socket
import struct
import threading
import time

# 帧头 flags：0x20 是协议版本位（服务端校验 (flags & 0x60) == 0x20）。
# 我们不声明 EC_FLAG_ZLIB / EC_FLAG_UTF8_NUMBERS，因此线上数据是未压缩 + 二进制整数。
EC_HEADER_FLAGS = 0x20
EC_HEADER_SIZE = 8
EC_MAX_PACKET = 16 * 1024 * 1024
EC_PROTOCOL_VERSION = 0x0204

#: 分块（part）大小：aMule/eMule 固定 9.28MB
PARTSIZE = 9728000
#: 小于该值的 eD2k ID 视为 LowID
HIGHEST_LOWID = 16777216

DEFAULT_TIMEOUT = 10.0
#: 统计树/日志/偏好这类大回包的单次等待上限（要小于面板侧 15s 的 HTTP 预算）
LONG_TIMEOUT = 12.0
DEFAULT_CLIENT_NAME = "fn-emule-panel"

#: 增量更新缓存里一条客户端/服务器多久没被任何一次回包提到就丢弃（秒）。
#: aMule 只在「这一轮有变化」时才把条目放进回包，所以没出现不等于消失。
#: 取 900 秒：排队中的来源可能十几分钟都没有状态变化（一直等位），
#: 存活期太短会把它误判成断开、来源数来回跳；确实断开的来源最终也会被清掉，
#: 只是晚一些——列表多留一条陈旧来源，远比显示不全要好。
_UPDATE_CACHE_TTL = 900.0


class EmuleError(Exception):
    """EC 层错误，消息一律是可直接展示给用户的中文原因。"""


class EmuleOffline(EmuleError):
    """引擎不可用：amuled 未运行、EC 端口不可达或握手失败。"""


class EmuleTimeout(EmuleOffline):
    """EC 请求超时（消息里一定带“超时”，面板据此回 504 而不是 503）。"""


#: aMule 服务端错误原文 → 面板展示的中文（CONTRACT：错误一律中文）
_ERROR_TRANSLATIONS = (
    ("FileHash not found", "下载列表里没有该文件"),
    ("Invalid link or already on list", "链接无效或该文件已在下载列表中"),
    ("eD2k is disabled in preferences", "设置里已禁用 eD2k 网络"),
    ("Kad is disabled in preferences", "设置里已禁用 Kad 网络"),
    ("eD2k search can't be done if eD2k is not connected",
     "未连接 eD2k 网络，暂时无法搜索（请先连接服务器）"),
    ("Kad search can't be done if Kad is not connected",
     "Kad 尚未连接，暂时无法搜索（请先引导 Kad）"),
    ("Kad search can't be done", "Kad 尚不可用，暂时无法搜索"),
    ("Server not added", "服务器未加入列表"),
    ("server not found", "服务器列表中没有该服务器"),
    ("need to define server to be removed", "必须先指定要删除的服务器"),
    ("Already shutting down", "引擎正在关闭中"),
    ("Invalid opcode", "EC 指令不被支持（协议版本可能不匹配）"),
    ("Search in progress", "搜索已开始，请稍候刷新结果"),
    ("Invalid file name", "文件名不合法"),
    ("File not found", "文件不存在"),
    ("Unable to rename file", "重命名失败"),
    ("No points for graph", "暂无统计数据"),
    ("Invalid protocol version", "EC 协议版本不匹配"),
    ("Missing protocol version tag", "EC 握手缺少协议版本"),
    ("Authentication failed", "EC 鉴权失败"),
)


def translate_message(message):
    """只翻译已知文案，未命中时原样返回（用于 aMule 的提示性字符串）。"""
    text = (message or "").strip()
    if not text:
        return text
    lowered = text.lower()
    for needle, chinese in _ERROR_TRANSLATIONS:
        if needle.lower() in lowered:
            return chinese
    return text


def translate_error(message):
    """把 aMule 的英文错误原文翻成中文；未命中时保留原文并加中文前缀。"""
    text = (message or "").strip()
    if not text:
        return "aMule 拒绝了该操作"
    lowered = text.lower()
    for needle, chinese in _ERROR_TRANSLATIONS:
        if needle.lower() in lowered:
            tail = ""
            # 形如 "FileHash not found: ABCD..." 时把后缀带出来
            if ":" in text:
                tail = "：" + text.split(":", 1)[1].strip()
            return chinese + tail
    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return text
    return "aMule 返回错误：%s" % text


class Op(object):
    """EC opcode（ECCodes.h ECOpCodes）。"""
    NOOP = 0x01
    AUTH_REQ = 0x02
    AUTH_FAIL = 0x03
    AUTH_OK = 0x04
    FAILED = 0x05
    STRINGS = 0x06
    MISC_DATA = 0x07
    SHUTDOWN = 0x08
    ADD_LINK = 0x09
    STAT_REQ = 0x0A
    GET_CONNSTATE = 0x0B
    STATS = 0x0C
    GET_DLOAD_QUEUE = 0x0D
    GET_ULOAD_QUEUE = 0x0E
    GET_SHARED_FILES = 0x10
    SHARED_SET_PRIO = 0x11
    PARTFILE_SWAP_A4AF_THIS = 0x16
    PARTFILE_SWAP_A4AF_THIS_AUTO = 0x17
    PARTFILE_SWAP_A4AF_OTHERS = 0x18
    PARTFILE_PAUSE = 0x19
    PARTFILE_RESUME = 0x1A
    PARTFILE_STOP = 0x1B
    PARTFILE_PRIO_SET = 0x1C
    PARTFILE_DELETE = 0x1D
    PARTFILE_SET_CAT = 0x1E
    DLOAD_QUEUE = 0x1F
    ULOAD_QUEUE = 0x20
    SHARED_FILES = 0x22
    SHAREDFILES_RELOAD = 0x23
    RENAME_FILE = 0x25
    SEARCH_START = 0x26
    SEARCH_STOP = 0x27
    SEARCH_RESULTS = 0x28
    SEARCH_PROGRESS = 0x29
    DOWNLOAD_SEARCH_RESULT = 0x2A
    IPFILTER_RELOAD = 0x2B
    GET_SERVER_LIST = 0x2C
    SERVER_LIST = 0x2D
    SERVER_DISCONNECT = 0x2E
    SERVER_CONNECT = 0x2F
    SERVER_REMOVE = 0x30
    SERVER_ADD = 0x31
    SERVER_UPDATE_FROM_URL = 0x32
    ADDLOGLINE = 0x33
    ADDDEBUGLOGLINE = 0x34
    GET_LOG = 0x35
    GET_DEBUGLOG = 0x36
    GET_SERVERINFO = 0x37
    LOG = 0x38
    DEBUGLOG = 0x39
    SERVERINFO = 0x3A
    RESET_LOG = 0x3B
    RESET_DEBUGLOG = 0x3C
    CLEAR_SERVERINFO = 0x3D
    GET_LAST_LOG_ENTRY = 0x3E
    GET_PREFERENCES = 0x3F
    SET_PREFERENCES = 0x40
    CREATE_CATEGORY = 0x41
    UPDATE_CATEGORY = 0x42
    DELETE_CATEGORY = 0x43
    GET_STATSGRAPHS = 0x44
    STATSGRAPHS = 0x45
    GET_STATSTREE = 0x46
    STATSTREE = 0x47
    KAD_START = 0x48
    KAD_STOP = 0x49
    CONNECT = 0x4A
    DISCONNECT = 0x4B
    KAD_UPDATE_FROM_URL = 0x4D
    KAD_BOOTSTRAP_FROM_IP = 0x4E
    AUTH_SALT = 0x4F
    AUTH_PASSWD = 0x50
    IPFILTER_UPDATE = 0x51
    GET_UPDATE = 0x52
    CLEAR_COMPLETED = 0x53
    CLIENT_SWAP_TO_ANOTHER_FILE = 0x54
    SHARED_FILE_SET_COMMENT = 0x55
    SERVER_SET_STATIC_PRIO = 0x56
    FRIEND = 0x57


OP_NAMES = dict((v, k) for k, v in vars(Op).items() if not k.startswith("_"))

#: 可能是“异步推送”的 opcode（服务端在通知模式下会主动发这些）
PUSH_OPCODES = frozenset([Op.SEARCH_RESULTS, Op.SEARCH_PROGRESS, Op.LOG,
                          Op.STATS, Op.MISC_DATA, Op.SHARED_FILES, Op.ULOAD_QUEUE])


class Tag(object):
    """EC tag 名称（ECCodes.h ECTagNames）。"""
    STRING = 0x0000
    PASSWD_HASH = 0x0001
    PROTOCOL_VERSION = 0x0002
    VERSION_ID = 0x0003
    DETAIL_LEVEL = 0x0004
    CONNSTATE = 0x0005
    ED2K_ID = 0x0006
    LOG_TO_STATUS = 0x0007
    BOOTSTRAP_IP = 0x0008
    BOOTSTRAP_PORT = 0x0009
    CLIENT_ID = 0x000A
    PASSWD_SALT = 0x000B
    CAN_ZLIB = 0x000C
    CAN_UTF8_NUMBERS = 0x000D
    CAN_NOTIFY = 0x000E
    ECID = 0x000F
    KAD_ID = 0x0010

    CLIENT_NAME = 0x0100
    CLIENT_VERSION = 0x0101
    CLIENT_MOD = 0x0102

    STATS_UL_SPEED = 0x0200
    STATS_DL_SPEED = 0x0201
    STATS_UL_SPEED_LIMIT = 0x0202
    STATS_DL_SPEED_LIMIT = 0x0203
    STATS_UP_OVERHEAD = 0x0204
    STATS_DOWN_OVERHEAD = 0x0205
    STATS_TOTAL_SRC_COUNT = 0x0206
    STATS_BANNED_COUNT = 0x0207
    STATS_UL_QUEUE_LEN = 0x0208
    STATS_ED2K_USERS = 0x0209
    STATS_KAD_USERS = 0x020A
    STATS_ED2K_FILES = 0x020B
    STATS_KAD_FILES = 0x020C
    STATS_LOGGER_MESSAGE = 0x020D
    STATS_KAD_FIREWALLED_UDP = 0x020E
    STATS_KAD_INDEXED_SOURCES = 0x020F
    STATS_KAD_INDEXED_KEYWORDS = 0x0210
    STATS_KAD_INDEXED_NOTES = 0x0211
    STATS_KAD_INDEXED_LOAD = 0x0212
    STATS_KAD_IP_ADRESS = 0x0213
    STATS_BUDDY_STATUS = 0x0214
    STATS_BUDDY_IP = 0x0215
    STATS_BUDDY_PORT = 0x0216
    STATS_KAD_IN_LAN_MODE = 0x0217
    STATS_TOTAL_SENT_BYTES = 0x0218
    STATS_TOTAL_RECEIVED_BYTES = 0x0219
    STATS_SHARED_FILE_COUNT = 0x021A
    STATS_KAD_NODES = 0x021B

    PARTFILE = 0x0300
    PARTFILE_NAME = 0x0301
    PARTFILE_PARTMETID = 0x0302
    PARTFILE_SIZE_FULL = 0x0303
    PARTFILE_SIZE_XFER = 0x0304
    PARTFILE_SIZE_XFER_UP = 0x0305
    PARTFILE_SIZE_DONE = 0x0306
    PARTFILE_SPEED = 0x0307
    PARTFILE_STATUS = 0x0308
    PARTFILE_PRIO = 0x0309
    PARTFILE_SOURCE_COUNT = 0x030A
    PARTFILE_SOURCE_COUNT_A4AF = 0x030B
    PARTFILE_SOURCE_COUNT_NOT_CURRENT = 0x030C
    PARTFILE_SOURCE_COUNT_XFER = 0x030D
    PARTFILE_ED2K_LINK = 0x030E
    PARTFILE_CAT = 0x030F
    PARTFILE_LAST_RECV = 0x0310
    PARTFILE_LAST_SEEN_COMP = 0x0311
    PARTFILE_PART_STATUS = 0x0312
    PARTFILE_GAP_STATUS = 0x0313
    PARTFILE_REQ_STATUS = 0x0314
    PARTFILE_SOURCE_NAMES = 0x0315
    PARTFILE_COMMENTS = 0x0316
    PARTFILE_STOPPED = 0x0317
    PARTFILE_DOWNLOAD_ACTIVE = 0x0318
    PARTFILE_LOST_CORRUPTION = 0x0319
    PARTFILE_GAINED_COMPRESSION = 0x031A
    PARTFILE_SAVED_ICH = 0x031B
    PARTFILE_SOURCE_NAMES_COUNTS = 0x031C
    PARTFILE_AVAILABLE_PARTS = 0x031D
    PARTFILE_HASH = 0x031E
    PARTFILE_SHARED = 0x031F
    PARTFILE_HASHED_PART_COUNT = 0x0320
    PARTFILE_A4AFAUTO = 0x0321
    PARTFILE_A4AF_SOURCES = 0x0322

    KNOWNFILE = 0x0400
    KNOWNFILE_XFERRED = 0x0401
    KNOWNFILE_XFERRED_ALL = 0x0402
    KNOWNFILE_REQ_COUNT = 0x0403
    KNOWNFILE_REQ_COUNT_ALL = 0x0404
    KNOWNFILE_ACCEPT_COUNT = 0x0405
    KNOWNFILE_ACCEPT_COUNT_ALL = 0x0406
    KNOWNFILE_AICH_MASTERHASH = 0x0407
    KNOWNFILE_FILENAME = 0x0408
    KNOWNFILE_COMPLETE_SOURCES_LOW = 0x0409
    KNOWNFILE_COMPLETE_SOURCES_HIGH = 0x040A
    KNOWNFILE_PRIO = 0x040B
    KNOWNFILE_ON_QUEUE = 0x040C
    KNOWNFILE_COMPLETE_SOURCES = 0x040D
    KNOWNFILE_COMMENT = 0x040E
    KNOWNFILE_RATING = 0x040F

    SERVER = 0x0500
    SERVER_NAME = 0x0501
    SERVER_DESC = 0x0502
    SERVER_ADDRESS = 0x0503
    SERVER_PING = 0x0504
    SERVER_USERS = 0x0505
    SERVER_USERS_MAX = 0x0506
    SERVER_FILES = 0x0507
    SERVER_PRIO = 0x0508
    SERVER_FAILED = 0x0509
    SERVER_STATIC = 0x050A
    SERVER_VERSION = 0x050B
    SERVER_IP = 0x050C
    SERVER_PORT = 0x050D

    CLIENT = 0x0600
    CLIENT_SOFTWARE = 0x0601
    CLIENT_SCORE = 0x0602
    CLIENT_HASH = 0x0603
    CLIENT_FRIEND_SLOT = 0x0604
    CLIENT_WAIT_TIME = 0x0605
    CLIENT_XFER_TIME = 0x0606
    CLIENT_QUEUE_TIME = 0x0607
    CLIENT_LAST_TIME = 0x0608
    CLIENT_UPLOAD_SESSION = 0x0609
    CLIENT_UPLOAD_TOTAL = 0x060A
    CLIENT_DOWNLOAD_TOTAL = 0x060B
    CLIENT_DOWNLOAD_STATE = 0x060C
    CLIENT_UP_SPEED = 0x060D
    CLIENT_DOWN_SPEED = 0x060E
    CLIENT_FROM = 0x060F
    CLIENT_USER_IP = 0x0610
    CLIENT_USER_PORT = 0x0611
    CLIENT_SERVER_IP = 0x0612
    CLIENT_SERVER_PORT = 0x0613
    CLIENT_SERVER_NAME = 0x0614
    CLIENT_SOFT_VER_STR = 0x0615
    CLIENT_WAITING_POSITION = 0x0616
    CLIENT_IDENT_STATE = 0x0617
    CLIENT_OBFUSCATION_STATUS = 0x0618
    CLIENT_CURRENTLYUNUSED1 = 0x0619
    CLIENT_REMOTE_QUEUE_RANK = 0x061A
    CLIENT_DISABLE_VIEW_SHARED = 0x061B
    CLIENT_UPLOAD_STATE = 0x061C
    CLIENT_EXT_PROTOCOL = 0x061D
    CLIENT_USER_ID = 0x061E
    CLIENT_UPLOAD_FILE = 0x061F
    CLIENT_REQUEST_FILE = 0x0620
    CLIENT_A4AF_FILES = 0x0621
    CLIENT_OLD_REMOTE_QUEUE_RANK = 0x0622
    CLIENT_KAD_PORT = 0x0623
    CLIENT_PART_STATUS = 0x0624
    CLIENT_NEXT_REQUESTED_PART = 0x0625
    CLIENT_LAST_DOWNLOADING_PART = 0x0626
    CLIENT_REMOTE_FILENAME = 0x0627
    CLIENT_MOD_VERSION = 0x0628
    CLIENT_OS_INFO = 0x0629
    CLIENT_AVAILABLE_PARTS = 0x062A
    CLIENT_UPLOAD_PART_STATUS = 0x062B

    SEARCHFILE = 0x0700
    SEARCH_TYPE = 0x0701
    SEARCH_NAME = 0x0702
    SEARCH_MIN_SIZE = 0x0703
    SEARCH_MAX_SIZE = 0x0704
    SEARCH_FILE_TYPE = 0x0705
    SEARCH_EXTENSION = 0x0706
    SEARCH_AVAILABILITY = 0x0707
    SEARCH_STATUS = 0x0708
    SEARCH_PARENT = 0x0709

    FRIEND = 0x0800
    FRIEND_NAME = 0x0801
    FRIEND_HASH = 0x0802
    FRIEND_IP = 0x0803
    FRIEND_PORT = 0x0804
    FRIEND_CLIENT = 0x0805
    FRIEND_ADD = 0x0806
    FRIEND_REMOVE = 0x0807
    FRIEND_FRIENDSLOT = 0x0808
    FRIEND_SHARED = 0x0809

    SELECT_PREFS = 0x1000
    PREFS_CATEGORIES = 0x1100
    CATEGORY = 0x1101
    CATEGORY_TITLE = 0x1102
    CATEGORY_PATH = 0x1103
    CATEGORY_COMMENT = 0x1104
    CATEGORY_COLOR = 0x1105
    CATEGORY_PRIO = 0x1106
    PREFS_GENERAL = 0x1200
    USER_NICK = 0x1201
    USER_HASH = 0x1202
    USER_HOST = 0x1203
    GENERAL_CHECK_NEW_VERSION = 0x1204
    PREFS_CONNECTIONS = 0x1300
    CONN_DL_CAP = 0x1301
    CONN_UL_CAP = 0x1302
    CONN_MAX_DL = 0x1303
    CONN_MAX_UL = 0x1304
    CONN_SLOT_ALLOCATION = 0x1305
    CONN_TCP_PORT = 0x1306
    CONN_UDP_PORT = 0x1307
    CONN_UDP_DISABLE = 0x1308
    CONN_MAX_FILE_SOURCES = 0x1309
    CONN_MAX_CONN = 0x130A
    CONN_AUTOCONNECT = 0x130B
    CONN_RECONNECT = 0x130C
    NETWORK_ED2K = 0x130D
    NETWORK_KADEMLIA = 0x130E
    PREFS_MESSAGEFILTER = 0x1400
    MSGFILTER_ENABLED = 0x1401
    MSGFILTER_ALL = 0x1402
    MSGFILTER_FRIENDS = 0x1403
    MSGFILTER_SECURE = 0x1404
    MSGFILTER_BY_KEYWORD = 0x1405
    MSGFILTER_KEYWORDS = 0x1406
    PREFS_REMOTECTRL = 0x1500
    WEBSERVER_AUTORUN = 0x1501
    WEBSERVER_PORT = 0x1502
    WEBSERVER_GUEST = 0x1503
    WEBSERVER_USEGZIP = 0x1504
    WEBSERVER_REFRESH = 0x1505
    WEBSERVER_TEMPLATE = 0x1506
    PREFS_ONLINESIG = 0x1600
    ONLINESIG_ENABLED = 0x1601
    PREFS_SERVERS = 0x1700
    SERVERS_REMOVE_DEAD = 0x1701
    SERVERS_DEAD_SERVER_RETRIES = 0x1702
    SERVERS_AUTO_UPDATE = 0x1703
    SERVERS_URL_LIST = 0x1704
    SERVERS_ADD_FROM_SERVER = 0x1705
    SERVERS_ADD_FROM_CLIENT = 0x1706
    SERVERS_USE_SCORE_SYSTEM = 0x1707
    SERVERS_SMART_ID_CHECK = 0x1708
    SERVERS_SAFE_SERVER_CONNECT = 0x1709
    SERVERS_AUTOCONN_STATIC_ONLY = 0x170A
    SERVERS_MANUAL_HIGH_PRIO = 0x170B
    SERVERS_UPDATE_URL = 0x170C
    PREFS_FILES = 0x1800
    FILES_ICH_ENABLED = 0x1801
    FILES_AICH_TRUST = 0x1802
    FILES_NEW_PAUSED = 0x1803
    FILES_NEW_AUTO_DL_PRIO = 0x1804
    FILES_PREVIEW_PRIO = 0x1805
    FILES_NEW_AUTO_UL_PRIO = 0x1806
    FILES_UL_FULL_CHUNKS = 0x1807
    FILES_START_NEXT_PAUSED = 0x1808
    FILES_RESUME_SAME_CAT = 0x1809
    FILES_SAVE_SOURCES = 0x180A
    FILES_EXTRACT_METADATA = 0x180B
    FILES_ALLOC_FULL_SIZE = 0x180C
    FILES_CHECK_FREE_SPACE = 0x180D
    FILES_MIN_FREE_SPACE = 0x180E
    FILES_CREATE_NORMAL = 0x180F
    PREFS_DIRECTORIES = 0x1A00
    DIRECTORIES_INCOMING = 0x1A01
    DIRECTORIES_TEMP = 0x1A02
    DIRECTORIES_SHARED = 0x1A03
    DIRECTORIES_SHARE_HIDDEN = 0x1A04
    PREFS_STATISTICS = 0x1B00
    STATSGRAPH_WIDTH = 0x1B01
    STATSGRAPH_SCALE = 0x1B02
    STATSGRAPH_LAST = 0x1B03
    STATSGRAPH_DATA = 0x1B04
    STATTREE_CAPPING = 0x1B05
    STATTREE_NODE = 0x1B06
    STAT_NODE_VALUE = 0x1B07
    STAT_VALUE_TYPE = 0x1B08
    STATTREE_NODEID = 0x1B09
    PREFS_SECURITY = 0x1C00
    SECURITY_CAN_SEE_SHARES = 0x1C01
    IPFILTER_CLIENTS = 0x1C02
    IPFILTER_SERVERS = 0x1C03
    IPFILTER_AUTO_UPDATE = 0x1C04
    IPFILTER_UPDATE_URL = 0x1C05
    IPFILTER_LEVEL = 0x1C06
    IPFILTER_FILTER_LAN = 0x1C07
    SECURITY_USE_SECIDENT = 0x1C08
    SECURITY_OBFUSCATION_SUPPORTED = 0x1C09
    SECURITY_OBFUSCATION_REQUESTED = 0x1C0A
    SECURITY_OBFUSCATION_REQUIRED = 0x1C0B
    PREFS_CORETWEAKS = 0x1D00
    CORETW_MAX_CONN_PER_FIVE = 0x1D01
    CORETW_VERBOSE = 0x1D02
    CORETW_FILEBUFFER = 0x1D03
    CORETW_UL_QUEUE = 0x1D04
    CORETW_SRV_KEEPALIVE_TIMEOUT = 0x1D05
    PREFS_KADEMLIA = 0x1E00
    KADEMLIA_UPDATE_URL = 0x1E01


TAG_NAMES = dict((v, k) for k, v in vars(Tag).items() if not k.startswith("_"))


class TagType(object):
    """EC tag 数据类型（ECTagTypes.h）。"""
    UNKNOWN = 0
    CUSTOM = 1
    UINT8 = 2
    UINT16 = 3
    UINT32 = 4
    UINT64 = 5
    STRING = 6
    DOUBLE = 7
    IPV4 = 8
    HASH16 = 9
    UINT128 = 10


class Detail(object):
    """EC_DETAIL_LEVEL；默认 FULL 时不上线 EC_TAG_DETAIL_LEVEL。"""
    CMD = 0
    WEB = 1
    FULL = 2
    UPDATE = 3
    INC_UPDATE = 4


class SearchType(object):
    LOCAL = 0
    GLOBAL = 1
    KAD = 2
    WEB = 3


class Prefs(object):
    """EC_PREFS_* 位掩码。"""
    CATEGORIES = 0x000001
    GENERAL = 0x000002
    CONNECTIONS = 0x000004
    MESSAGEFILTER = 0x000008
    REMOTECONTROLS = 0x000010
    ONLINESIG = 0x000020
    SERVERS = 0x000040
    FILES = 0x000080
    DIRECTORIES = 0x000200
    STATISTICS = 0x000400
    SECURITY = 0x000800
    CORETWEAKS = 0x001000
    KADEMLIA = 0x002000

    #: 面板关心的全部页签
    ALL_USED = (GENERAL | CONNECTIONS | ONLINESIG | SERVERS | FILES |
                DIRECTORIES | SECURITY | CORETWEAKS | KADEMLIA)


class ValueType(object):
    """EC_STATTREE_NODE_VALUE_TYPE。"""
    INTEGER = 0
    ISTRING = 1
    BYTES = 2
    ISHORT = 3
    TIME = 4
    SPEED = 5
    STRING = 6
    DOUBLE = 7


# ---------------------------------------------------------------- 数据模型

class ECTag(object):
    """一个解码后的 EC tag（含子 tag）。"""

    __slots__ = ("name", "type", "data", "children")

    def __init__(self, name=0, ttype=TagType.UNKNOWN, data=b"", children=None):
        self.name = name
        self.type = ttype
        self.data = data
        self.children = children if children is not None else []

    # -- 查找 ---------------------------------------------------------
    def get(self, name, default=None):
        for child in self.children:
            if child.name == name:
                return child
        return default

    def all(self, name):
        return [c for c in self.children if c.name == name]

    def has(self, name):
        return self.get(name) is not None

    def child_value(self, name, default=0):
        tag = self.get(name)
        return tag.int() if tag is not None else default

    def child_text(self, name, default=""):
        tag = self.get(name)
        return tag.text() if tag is not None else default

    # -- 取值 ---------------------------------------------------------
    def int(self, default=0):
        if self.type in (TagType.UINT8, TagType.UINT16, TagType.UINT32, TagType.UINT64):
            if not self.data:
                return default
            return int.from_bytes(self.data, "big")
        if self.type == TagType.STRING:
            try:
                return int(self.text().strip())
            except (TypeError, ValueError):
                return default
        return default

    def float(self, default=0.0):
        if self.type == TagType.DOUBLE:
            try:
                return float(self.text().strip())
            except (TypeError, ValueError):
                return default
        return float(self.int(default))

    def text(self):
        if self.type not in (TagType.STRING, TagType.DOUBLE):
            return ""
        raw = self.data
        if raw[-1:] == b"\x00":
            raw = raw[:-1]
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("utf-8", "replace")

    def hexhash(self):
        """HASH16 → 大写 32 位十六进制字符串。"""
        if self.type == TagType.HASH16 and len(self.data) == 16:
            return self.data.hex().upper()
        return ""

    def ip(self, default=("", 0)):
        """EC_TAGTYPE_IPV4 → ("1.2.3.4", port)。"""
        if self.type == TagType.IPV4 and len(self.data) >= 6:
            text = "%d.%d.%d.%d" % (self.data[0], self.data[1], self.data[2], self.data[3])
            return text, struct.unpack(">H", self.data[4:6])[0]
        if self.type == TagType.UINT32 and len(self.data) == 4:
            return uint32_to_ip(int.from_bytes(self.data, "big")), 0
        return default

    def __repr__(self):
        return "<ECTag %s type=%d len=%d kids=%d>" % (
            TAG_NAMES.get(self.name, hex(self.name)), self.type, len(self.data), len(self.children))


class ECPacket(ECTag):
    """一个回包：opcode + 顶层 tag 列表。"""

    __slots__ = ("opcode",)

    def __init__(self, opcode=0):
        ECTag.__init__(self, 0, TagType.UNKNOWN, b"", [])
        self.opcode = opcode

    def __repr__(self):
        return "<ECPacket %s kids=%d>" % (OP_NAMES.get(self.opcode, hex(self.opcode)), len(self.children))


def uint32_to_ip(value):
    """aMule 的 uint32 IP 是“反主机序”：低字节是第一段（NetworkFunctions.h Uint32toStringIP）。"""
    value = int(value) & 0xFFFFFFFF
    return "%d.%d.%d.%d" % (value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF, (value >> 24) & 0xFF)


def ip_to_uint32(text):
    parts = [int(p) for p in str(text).strip().split(".")]
    if len(parts) != 4 or any(p < 0 or p > 255 for p in parts):
        raise EmuleError("IP 地址不合法：%s" % text)
    return parts[0] | (parts[1] << 8) | (parts[2] << 16) | (parts[3] << 24)


# ---------------------------------------------------------------- 编码

class _Node(object):
    """待发送的 tag 节点。"""

    __slots__ = ("name", "ttype", "data", "children")

    def __init__(self, name, ttype=TagType.CUSTOM, data=b"", children=None):
        self.name = name
        self.ttype = ttype
        self.data = data
        self.children = children or []


def tag_string(name, value):
    """字符串 tag：UTF-8 + 结尾 NUL（aMule 用 strlen+1 作为长度）。"""
    return _Node(name, TagType.STRING, str(value).encode("utf-8") + b"\x00")


def tag_uint(name, value):
    """整数 tag：aMule 按数值大小自动选 uint8/16/32/64。"""
    value = int(value)
    if value < 0:
        value = 0
    if value <= 0xFF:
        return _Node(name, TagType.UINT8, value.to_bytes(1, "big"))
    if value <= 0xFFFF:
        return _Node(name, TagType.UINT16, value.to_bytes(2, "big"))
    if value <= 0xFFFFFFFF:
        return _Node(name, TagType.UINT32, value.to_bytes(4, "big"))
    return _Node(name, TagType.UINT64, value.to_bytes(8, "big"))


def tag_hash(name, file_hash):
    """16 字节 hash tag；file_hash 为 32 位十六进制。"""
    raw = bytes.fromhex(str(file_hash).strip().lower())
    if len(raw) != 16:
        raise EmuleError("文件哈希必须是 32 位十六进制：%s" % file_hash)
    return _Node(name, TagType.HASH16, raw)


def tag_ip(name, ip, port):
    """IPv4 tag：4 字节分四段 + 2 字节 big-endian 端口。"""
    parts = [int(p) for p in str(ip).split(".")]
    if len(parts) != 4:
        raise EmuleError("IP 地址不合法：%s" % ip)
    raw = bytes(parts) + struct.pack(">H", int(port))
    return _Node(name, TagType.IPV4, raw)


def tag_empty(name):
    """空 tag（布尔开关只靠“有没有这个 tag”表达）。"""
    return _Node(name, TagType.CUSTOM, b"")


def tag_node(name, children, ttype=TagType.CUSTOM, data=b""):
    return _Node(name, ttype, data, list(children))


def _serialize(node):
    """返回 (上线字节, 该 tag 上线后的总字节数)。"""
    child_parts = []
    inner = len(node.data)
    for child in node.children:
        blob, total = _serialize(child)
        child_parts.append(blob)
        inner += total
    has_children = bool(node.children)
    head = struct.pack(">HBI", (node.name << 1) | (1 if has_children else 0), node.ttype, inner)
    if has_children:
        head += struct.pack(">H", len(node.children)) + b"".join(child_parts)
    wire = head + node.data
    return wire, len(wire)


def build_packet(opcode, nodes=(), detail=None):
    """拼一个完整 EC 帧。

    帧体 = opcode(1B) + 顶层 tag 数(2B) + 各 tag（CECPacket::WritePacket +
    CECTag::WriteChildren）。漏掉那个 2 字节计数服务端会直接报 packet read error。
    """
    nodes = list(nodes)
    if detail is not None and detail != Detail.FULL:
        nodes = [tag_uint(Tag.DETAIL_LEVEL, detail)] + nodes
    body = [bytes([opcode & 0xFF]), struct.pack(">H", len(nodes))]
    for node in nodes:
        body.append(_serialize(node)[0])
    payload = b"".join(body)
    if len(payload) > EC_MAX_PACKET:
        raise EmuleError("EC 请求过大（%d 字节）" % len(payload))
    return struct.pack(">II", EC_HEADER_FLAGS, len(payload)) + payload


# ---------------------------------------------------------------- 解码

class _Cursor(object):
    __slots__ = ("buf", "pos")

    def __init__(self, buf):
        self.buf = buf
        self.pos = 0

    def take(self, count):
        end = self.pos + count
        if end > len(self.buf):
            raise EmuleError("EC 数据包被截断（需要 %d 字节，只剩 %d）"
                             % (count, len(self.buf) - self.pos))
        chunk = self.buf[self.pos:end]
        self.pos = end
        return chunk

    def u8(self):
        return self.take(1)[0]

    def u16(self):
        return int.from_bytes(self.take(2), "big")

    def u32(self):
        return int.from_bytes(self.take(4), "big")


def _wire_size(tag):
    """已解码 tag 再上线时的总字节数（7 字节头 + 子计数 + 数据）。"""
    size = 7 + len(tag.data)
    if tag.children:
        size += 2
        for child in tag.children:
            size += _wire_size(child)
    return size


def _decode_tag(cur):
    raw_name = cur.u16()
    name = raw_name >> 1
    has_children = bool(raw_name & 1)
    ttype = cur.u8()
    total = cur.u32()
    children = []
    if has_children:
        count = cur.u16()
        for _ in range(count):
            children.append(_decode_tag(cur))
    consumed = 0
    for child in children:
        consumed += _wire_size(child)
    data_len = total - consumed
    if data_len < 0:
        raise EmuleError("EC tag 长度字段不合法（声明 %d，子 tag 占 %d）" % (total, consumed))
    data = cur.take(data_len) if data_len else b""
    return ECTag(name, ttype, data, children)


def decode_packet(flags, payload):
    """解一个 EC 帧体（不含 8 字节头）。"""
    if (flags & 0x60) != 0x20:
        raise EmuleError("EC 协议版本不匹配（flags=0x%08X）" % flags)
    if flags & 0x01:
        raise EmuleError("EC 数据被压缩，当前客户端不支持")
    if flags & 0x02:
        raise EmuleError("EC 整数以 UTF-8 编码，当前客户端不支持")
    if not payload:
        raise EmuleError("EC 空数据包")
    cur = _Cursor(payload)
    packet = ECPacket(cur.u8())
    count = cur.u16()
    for _ in range(count):
        packet.children.append(_decode_tag(cur))
    return packet


# ---------------------------------------------------------------- RLE 解码
# aMule RLE_Data::Encode：连续 >=2 个相同字节编码成 [v, v, 长度]（长度 <= 255），
# 单字节原样输出。我们永远用 EC_DETAIL_FULL 请求，服务端会 ResetEncoder，
# 因此拿到的是不含差分的完整数据。

def rle_decode(buf):
    """RLE 解码为原始字节串。"""
    out = bytearray()
    i = 0
    total = len(buf)
    while i < total:
        if i < total - 2 and buf[i + 1] == buf[i]:
            out.extend([buf[i]] * buf[i + 2])
            i += 3
        else:
            out.append(buf[i])
            i += 1
    return bytes(out)


def rle_decode_uint8_list(buf):
    """每块一个字节（例如 part 的可用源数量）。"""
    return list(rle_decode(buf))


def rle_decode_uint64_list(buf):
    """uint64 数组：先按 8 个字节面分列打包（RLE_Data::Decode 的重排）。"""
    data = rle_decode(buf)
    count = len(data) // 8
    values = []
    for index in range(count):
        value = 0
        for plane in range(8):
            value |= data[index + plane * count] << (8 * plane)
        values.append(value)
    return values


def decode_gaps(tag):
    """EC_TAG_PARTFILE_GAP_STATUS → [(start, end), ...]，**左闭右开**（字节偏移）。

    aMule 的 gap list 存的是 [起点, 终点]，两端都包含，终点=最后一个未下载字节；
    这里统一 +1 转成左闭右开，后面按块计算覆盖率才不会差一字节
    （实测 3000000 字节的新任务回包是 [(0, 2999999)]）。
    """
    if tag is None or not tag.data:
        return []
    values = rle_decode_uint64_list(tag.data)
    return [(values[i], values[i + 1] + 1) for i in range(0, len(values) - 1, 2)]


def decode_parts(tag):
    """EC_TAG_PARTFILE_PART_STATUS → 每块的可用源数量列表。"""
    if tag is None or not tag.data:
        return []
    return rle_decode_uint8_list(tag.data)


# ---------------------------------------------------------------- 回包解析

def partfile_record(tag):
    """CEC_PartFile_Tag（ExternalConn.cpp / ECSpecialCoreTags.cpp 的字段顺序）。"""
    record = {
        "ecid": tag.int(),
        "hash": "",
        "name": tag.child_text(Tag.PARTFILE_NAME),
        "size": tag.child_value(Tag.PARTFILE_SIZE_FULL),
        "done": tag.child_value(Tag.PARTFILE_SIZE_DONE),
        "xfer": tag.child_value(Tag.PARTFILE_SIZE_XFER),
        "speed": tag.child_value(Tag.PARTFILE_SPEED),
        "status": tag.child_value(Tag.PARTFILE_STATUS),
        "prio_raw": tag.child_value(Tag.PARTFILE_PRIO),
        "category": tag.child_value(Tag.PARTFILE_CAT),
        "source_total": tag.child_value(Tag.PARTFILE_SOURCE_COUNT),
        "source_a4af": tag.child_value(Tag.PARTFILE_SOURCE_COUNT_A4AF),
        "source_not_current": tag.child_value(Tag.PARTFILE_SOURCE_COUNT_NOT_CURRENT),
        "source_xfer": tag.child_value(Tag.PARTFILE_SOURCE_COUNT_XFER),
        "last_recv": tag.child_value(Tag.PARTFILE_LAST_RECV),
        "last_seen_complete": tag.child_value(Tag.PARTFILE_LAST_SEEN_COMP),
        "download_active": tag.child_value(Tag.PARTFILE_DOWNLOAD_ACTIVE),
        "available_parts": tag.child_value(Tag.PARTFILE_AVAILABLE_PARTS),
        "hashed_parts": tag.child_value(Tag.PARTFILE_HASHED_PART_COUNT),
        "partmet_id": tag.child_value(Tag.PARTFILE_PARTMETID),
        "stopped": bool(tag.child_value(Tag.PARTFILE_STOPPED)),
        "shared": bool(tag.child_value(Tag.PARTFILE_SHARED)),
        "ed2k_link": tag.child_text(Tag.PARTFILE_ED2K_LINK),
        "lost_corruption": tag.child_value(Tag.PARTFILE_LOST_CORRUPTION),
        "gained_compression": tag.child_value(Tag.PARTFILE_GAINED_COMPRESSION),
        "saved_ich": tag.child_value(Tag.PARTFILE_SAVED_ICH),
        "gaps": decode_gaps(tag.get(Tag.PARTFILE_GAP_STATUS)),
        "part_availability": decode_parts(tag.get(Tag.PARTFILE_PART_STATUS)),
    }
    # 文件哈希：name 可能不是 HASH16（老细节级别下缺失），保底再取一次
    hash_tag = tag.get(Tag.PARTFILE_HASH)
    if hash_tag is not None:
        record["hash"] = hash_tag.hexhash()
    return record


def client_record(tag):
    """CEC_UpDownClient_Tag。"""
    ip_value = tag.child_value(Tag.CLIENT_USER_IP)
    return {
        "ecid": tag.int(),
        "name": tag.child_text(Tag.CLIENT_NAME),
        "hash": (tag.get(Tag.CLIENT_HASH).hexhash() if tag.get(Tag.CLIENT_HASH) else ""),
        "user_id": tag.child_value(Tag.CLIENT_USER_ID),
        "ip": ip_value,
        "ip_str": uint32_to_ip(ip_value) if ip_value else "",
        "port": tag.child_value(Tag.CLIENT_USER_PORT),
        "server_ip": uint32_to_ip(tag.child_value(Tag.CLIENT_SERVER_IP)),
        "server_port": tag.child_value(Tag.CLIENT_SERVER_PORT),
        "server_name": tag.child_text(Tag.CLIENT_SERVER_NAME),
        "software": tag.child_value(Tag.CLIENT_SOFTWARE),
        "soft_ver": tag.child_text(Tag.CLIENT_SOFT_VER_STR),
        "soft_ver_num": tag.child_value(Tag.CLIENT_VERSION),
        "mod_version": tag.child_text(Tag.CLIENT_MOD_VERSION),
        "os_info": tag.child_text(Tag.CLIENT_OS_INFO),
        "up_speed": tag.child_value(Tag.CLIENT_UP_SPEED),
        "down_speed": tag.get(Tag.CLIENT_DOWN_SPEED).float(0.0) if tag.get(Tag.CLIENT_DOWN_SPEED) else 0.0,
        "uploaded_total": tag.child_value(Tag.CLIENT_UPLOAD_TOTAL),
        "downloaded_total": tag.child_value(Tag.CLIENT_DOWNLOAD_TOTAL),
        "upload_session": tag.child_value(Tag.CLIENT_UPLOAD_SESSION),
        "xfer_down_session": tag.child_value(Tag.PARTFILE_SIZE_XFER),
        "upload_state": tag.child_value(Tag.CLIENT_UPLOAD_STATE),
        "download_state": tag.child_value(Tag.CLIENT_DOWNLOAD_STATE),
        "ident_state": tag.child_value(Tag.CLIENT_IDENT_STATE),
        "waiting_position": tag.child_value(Tag.CLIENT_WAITING_POSITION),
        "queue_rank": tag.child_value(Tag.CLIENT_REMOTE_QUEUE_RANK),
        "old_queue_rank": tag.child_value(Tag.CLIENT_OLD_REMOTE_QUEUE_RANK),
        "score": tag.child_value(Tag.CLIENT_SCORE),
        "obfuscation": tag.child_value(Tag.CLIENT_OBFUSCATION_STATUS),
        "friend_slot": bool(tag.child_value(Tag.CLIENT_FRIEND_SLOT)),
        "kad_port": tag.child_value(Tag.CLIENT_KAD_PORT),
        "request_file_ecid": tag.child_value(Tag.CLIENT_REQUEST_FILE),
        "upload_file_ecid": tag.child_value(Tag.CLIENT_UPLOAD_FILE),
        "upload_file_name": tag.child_text(Tag.PARTFILE_NAME),
        "remote_filename": tag.child_text(Tag.CLIENT_REMOTE_FILENAME),
        "available_parts": tag.child_value(Tag.CLIENT_AVAILABLE_PARTS),
        "source_from": tag.child_value(Tag.CLIENT_FROM),
        "ext_protocol": bool(tag.child_value(Tag.CLIENT_EXT_PROTOCOL)),
    }


def server_record(tag):
    """CEC_Server_Tag。两种形态：

    * FULL/WEB 细节级别：IP/端口编码在 tag 自身的 IPv4 数据里；
    * 增量更新包（CEC_Server_Tag + valuemap）：tag 自身数据是 ECID，IP/端口是
      EC_TAG_SERVER_IP / EC_TAG_SERVER_PORT 两个整数子 tag。

    所以先看有没有 SERVER_IP 子 tag —— 否则会把这个 uint32 的 ECID 当成 IPv4 解出来。
    """
    ip_tag = tag.get(Tag.SERVER_IP)
    if ip_tag is not None:
        ip = uint32_to_ip(ip_tag.int())
        port = tag.child_value(Tag.SERVER_PORT)
    else:
        ip, port = tag.ip()
    return {
        "ecid": tag.int(),
        "ip": ip,
        "port": port,
        "name": tag.child_text(Tag.SERVER_NAME),
        "desc": tag.child_text(Tag.SERVER_DESC),
        "version": tag.child_text(Tag.SERVER_VERSION),
        "ping": tag.child_value(Tag.SERVER_PING),
        "priority": tag.child_value(Tag.SERVER_PRIO),
        "failed": tag.child_value(Tag.SERVER_FAILED),
        "static": bool(tag.child_value(Tag.SERVER_STATIC)),
        "users": tag.child_value(Tag.SERVER_USERS),
        "maxusers": tag.child_value(Tag.SERVER_USERS_MAX),
        "files": tag.child_value(Tag.SERVER_FILES),
    }


def _filled_fields(record):
    """从一条记录里挑出「这次真的带了值」的字段。

    aMule 的增量回包里，同一个客户端有时只带几个变化的字段
    （实测常见的是 CLIENT_DOWN_SPEED / CLIENT_DOWNLOAD_TOTAL / CLIENT_QT_RANGES）。
    这种 tag 直接覆盖完整记录会把名字、IP 抹成空 —— 表现为来源列表里出现
    「一行没有 IP」的条目。所以只把非空字段合并进缓存里那份完整记录。

    注意 0 与空串都当「没带」：这些字段（速度、队列名次、状态）真实值本来
    就可能是 0，宁可保留旧值，也不要让一次部分更新把有效信息清空。
    """
    filled = {}
    for key, value in (record or {}).items():
        if value is None or value == "" or value == [] or value == 0:
            continue
        filled[key] = value
    return filled


def _update_client_child_tags(container):
    """增量更新包里的 CLIENT 容器 → 客户端 tag 列表（原始 tag，交给缓存层解析）。

    顶层 CLIENT 是 CECEmptyTag 容器（只带名字，任何字段都没有），每个真实的
    CEC_UpDownClient_Tag 是它的子节点。这里保持"原样返回子节点"，因为调用方还需要
    区分「带字段的全量 tag」和「只有 ECID 的增量存根」，这是缓存层才能判断的。
    老形态（顶层 CLIENT 自己就带字段、没有容器这一层）照样收下。
    """
    children = [child for child in container.children if child.name == Tag.CLIENT]
    if children:
        return children
    if container.get(Tag.CLIENT_NAME) is not None or not container.children:
        return [container] if container.get(Tag.CLIENT_NAME) is not None else []
    return []


def _update_server_child_tags(container):
    """增量更新包里的 SERVER 容器 → 服务器 tag 列表（理由同 _update_client_child_tags）。"""
    children = [child for child in container.children if child.name == Tag.SERVER]
    if children:
        return children
    if container.get(Tag.SERVER_NAME) is not None or container.get(Tag.SERVER_IP) is not None:
        return [container]
    return []


def search_record(tag):
    """CEC_SearchFile_Tag。"""
    return {
        "ecid": tag.int(),
        "hash": (tag.get(Tag.PARTFILE_HASH).hexhash() if tag.get(Tag.PARTFILE_HASH) else ""),
        "name": tag.child_text(Tag.PARTFILE_NAME),
        "size": tag.child_value(Tag.PARTFILE_SIZE_FULL),
        "sources": tag.child_value(Tag.PARTFILE_SOURCE_COUNT),
        "complete_sources": tag.child_value(Tag.PARTFILE_SOURCE_COUNT_XFER),
        "status": tag.child_value(Tag.PARTFILE_STATUS),
        "parent_ecid": tag.child_value(Tag.SEARCH_PARENT),
    }


def sharedfile_record(tag):
    """CEC_SharedFile_Tag（EC_TAG_KNOWNFILE）。"""
    return {
        "ecid": tag.int(),
        "hash": (tag.get(Tag.PARTFILE_HASH).hexhash() if tag.get(Tag.PARTFILE_HASH) else ""),
        "name": tag.child_text(Tag.PARTFILE_NAME),
        "path": tag.child_text(Tag.KNOWNFILE_FILENAME),
        "size": tag.child_value(Tag.PARTFILE_SIZE_FULL),
        "priority": tag.child_value(Tag.KNOWNFILE_PRIO),
        "requests": tag.child_value(Tag.KNOWNFILE_REQ_COUNT),
        "requests_all": tag.child_value(Tag.KNOWNFILE_REQ_COUNT_ALL),
        "accepts": tag.child_value(Tag.KNOWNFILE_ACCEPT_COUNT),
        "accepts_all": tag.child_value(Tag.KNOWNFILE_ACCEPT_COUNT_ALL),
        "xferred": tag.child_value(Tag.KNOWNFILE_XFERRED),
        "xferred_all": tag.child_value(Tag.KNOWNFILE_XFERRED_ALL),
        "complete_sources": tag.child_value(Tag.KNOWNFILE_COMPLETE_SOURCES),
        "on_queue": tag.child_value(Tag.KNOWNFILE_ON_QUEUE),
        "comment": tag.child_text(Tag.KNOWNFILE_COMMENT),
        "rating": tag.child_value(Tag.KNOWNFILE_RATING),
        "ed2k_link": tag.child_text(Tag.PARTFILE_ED2K_LINK),
        "aich_hash": tag.child_text(Tag.KNOWNFILE_AICH_MASTERHASH),
    }


def connstate_record(tag):
    """CEC_ConnState_Tag → 连接状态字典。"""
    flags = tag.int()
    ed2k_id = tag.child_value(Tag.ED2K_ID)
    server_tag = tag.get(Tag.SERVER)
    server = None
    if server_tag is not None:
        ip, port = server_tag.ip()
        if ip:
            server = {"name": server_tag.child_text(Tag.SERVER_NAME), "ip": ip, "port": port}
    kad_id = ""
    kad_tag = tag.get(Tag.KAD_ID)
    if kad_tag is not None and len(kad_tag.data) == 16:
        kad_id = kad_tag.data.hex().upper()
    return {
        "flags": flags,
        "ed2k_connected": bool(flags & 0x01),
        "ed2k_connecting": bool(flags & 0x02),
        "kad_connected": bool(flags & 0x04),
        "kad_firewalled": bool(flags & 0x08),
        "kad_running": bool(flags & 0x10),
        "ed2k_id": ed2k_id,
        "low_id": bool(ed2k_id) and ed2k_id < HIGHEST_LOWID,
        "client_id": tag.child_value(Tag.CLIENT_ID),
        "server": server,
        "kad_id": kad_id,
    }


#: EC_OP_STAT_REQ / EC_OP_STATS 里我们关心的字段
_STAT_FIELDS = {
    Tag.STATS_UL_SPEED: "up_speed",
    Tag.STATS_DL_SPEED: "down_speed",
    Tag.STATS_UL_SPEED_LIMIT: "up_limit",
    Tag.STATS_DL_SPEED_LIMIT: "down_limit",
    Tag.STATS_UP_OVERHEAD: "up_overhead",
    Tag.STATS_DOWN_OVERHEAD: "down_overhead",
    Tag.STATS_TOTAL_SRC_COUNT: "sources",
    Tag.STATS_BANNED_COUNT: "banned",
    Tag.STATS_UL_QUEUE_LEN: "ul_queue_len",
    Tag.STATS_ED2K_USERS: "ed2k_users",
    Tag.STATS_KAD_USERS: "kad_users",
    Tag.STATS_ED2K_FILES: "ed2k_files",
    Tag.STATS_KAD_FILES: "kad_files",
    Tag.STATS_KAD_FIREWALLED_UDP: "kad_firewalled_udp",
    Tag.STATS_KAD_INDEXED_SOURCES: "kad_indexed_sources",
    Tag.STATS_KAD_INDEXED_KEYWORDS: "kad_indexed_keywords",
    Tag.STATS_KAD_INDEXED_NOTES: "kad_indexed_notes",
    Tag.STATS_KAD_INDEXED_LOAD: "kad_indexed_load",
    Tag.STATS_KAD_IP_ADRESS: "kad_ip_raw",
    Tag.STATS_BUDDY_STATUS: "kad_buddy_status",
    Tag.STATS_BUDDY_IP: "kad_buddy_ip",
    Tag.STATS_BUDDY_PORT: "kad_buddy_port",
    Tag.STATS_KAD_IN_LAN_MODE: "kad_in_lan_mode",
    Tag.STATS_TOTAL_SENT_BYTES: "total_sent",
    Tag.STATS_TOTAL_RECEIVED_BYTES: "total_received",
    Tag.STATS_SHARED_FILE_COUNT: "shared_files",
    Tag.STATS_KAD_NODES: "kad_nodes",
}


def stats_record(packet):
    """EC_OP_STAT_REQ 回包 → {统计字段..., 'connstate': {...}, 'log': [...]}。"""
    result = {"connstate": None, "log": []}
    for tag in packet.children:
        key = _STAT_FIELDS.get(tag.name)
        if key is not None:
            result[key] = tag.int()
        elif tag.name == Tag.CONNSTATE:
            result["connstate"] = connstate_record(tag)
        elif tag.name == Tag.STATS_LOGGER_MESSAGE:
            result["log"] = [child.text() for child in tag.children if child.name == Tag.STRING]
    return result


# ---------------------------------------------------------------- 客户端

class _Broken(object):
    """reader 线程的断线哨兵。"""

    __slots__ = ("reason",)

    def __init__(self, reason):
        self.reason = reason


#: opcode → 合法回包 opcode 集合（None 表示“任何包都当回包”）
_EXPECTED = {
    Op.STAT_REQ: (Op.STATS,),
    Op.GET_CONNSTATE: (Op.MISC_DATA,),
    Op.GET_DLOAD_QUEUE: (Op.DLOAD_QUEUE,),
    Op.GET_ULOAD_QUEUE: (Op.ULOAD_QUEUE,),
    Op.GET_SHARED_FILES: (Op.SHARED_FILES,),
    Op.GET_UPDATE: (Op.SHARED_FILES,),
    Op.GET_SERVER_LIST: (Op.SERVER_LIST,),
    Op.GET_LOG: (Op.LOG,),
    Op.GET_DEBUGLOG: (Op.DEBUGLOG,),
    Op.GET_SERVERINFO: (Op.SERVERINFO,),
    Op.GET_LAST_LOG_ENTRY: (Op.LOG,),
    Op.GET_STATSTREE: (Op.STATSTREE,),
    Op.GET_PREFERENCES: (Op.SET_PREFERENCES, Op.NOOP),
    Op.SEARCH_START: (Op.STRINGS,),
    Op.SEARCH_RESULTS: (Op.SEARCH_RESULTS,),
    Op.SEARCH_PROGRESS: (Op.SEARCH_PROGRESS,),
    Op.DOWNLOAD_SEARCH_RESULT: (Op.STRINGS,),
    Op.SEARCH_STOP: (Op.MISC_DATA,),
    Op.CONNECT: (Op.STRINGS,),
    Op.DISCONNECT: (Op.STRINGS, Op.NOOP),
    Op.GET_STATSGRAPHS: (Op.STATSGRAPHS,),
}


class ECClient(object):
    """一条 EC 连接。线程安全：所有请求经内部锁串行执行。"""

    def __init__(self, host="127.0.0.1", port=4712, password="", timeout=DEFAULT_TIMEOUT,
                 client_name=DEFAULT_CLIENT_NAME, client_version="26.11.0"):
        self.host = host
        self.port = int(port)
        self.password = password or ""
        self.timeout = float(timeout)
        self.client_name = client_name
        self.client_version = client_version
        self.server_version = ""
        self.protocol_version = 0
        #: 收到“异步推送包”时的回调（例如搜索会话累积结果）
        self.on_push = None
        self._sock = None
        self._reader = None
        self._inbox = queue.Queue()
        self._lock = threading.RLock()
        self._closed = False
        #: 发出去但不等回包的请求（目前只有 SHAREDFILES_RELOAD），它回来的是
        #: EC_OP_NOOP，必须丢掉，不能当成下一个请求的响应。
        self._pending_noop = 0
        # EC_OP_GET_UPDATE 是「按连接」增量的：同一条连接上第一次回全量，
        # 之后只回 ECID 存根（tag 没有子节点）。所以这里按 ECID 累积上一次的全量结果，
        # 每次请求用当次响应里出现过的 ECID 做一次收敛，连接重建时整体清空。
        self._update_cache = {"files": {}, "clients": {}, "servers": {}}

    # -- 连接管理 -----------------------------------------------------
    @property
    def connected(self):
        return self._sock is not None

    def configure(self, host=None, port=None, password=None, timeout=None):
        """改连接参数；变了就断开，下次请求用新参数重连。"""
        changed = False
        if host is not None and host != self.host:
            self.host = host
            changed = True
        if port is not None and int(port) != self.port:
            self.port = int(port)
            changed = True
        if password is not None and password != self.password:
            self.password = password
            changed = True
        if timeout is not None:
            self.timeout = float(timeout)
        if changed:
            self.close()
        return changed

    def connect(self):
        """建立连接并完成鉴权；返回 {"version", "protocol"}。"""
        with self._lock:
            if self._sock is None:
                self._open()
            return {"version": self.server_version, "protocol": self.protocol_version}

    def close(self):
        """断开（不会等待 reader 线程退出）。"""
        self._closed = True
        self._pending_noop = 0          # 连接一断，之前那些不等回包的请求全部作废
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def probe(self, timeout=2.0):
        """轻量探活：能拿到连接状态就算在线。"""
        try:
            state = self.get_connstate(timeout=timeout)
            return True, state
        except EmuleError:
            return False, None

    def _open(self):
        self._closed = False
        # 新连接意味着 aMule 那边的增量 tagmap 从头开始，本地累积必须一起清掉，
        # 否则会把上一条连接见过、这次根本没出现的客户端当成本次结果。
        self._update_cache = {"files": {}, "clients": {}, "servers": {}}
        self._pending_noop = 0                  # 新连接上没有任何待收的 NOOP
        while not self._inbox.empty():          # 丢掉上次会话的残留包
            try:
                self._inbox.get_nowait()
            except queue.Empty:
                break
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise EmuleOffline("无法连接 aMule EC 端口 %s:%d（引擎未运行？）：%s"
                               % (self.host, self.port, exc))
        sock.settimeout(self.timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock
        self._reader = threading.Thread(target=self._reader_loop, args=(sock,),
                                        name="ec-reader", daemon=True)
        self._reader.start()
        try:
            self._authenticate()
        except Exception:
            self.close()
            raise

    def _reader_loop(self, sock):
        try:
            while True:
                header = self._recv_exact(sock, EC_HEADER_SIZE)
                flags, length = struct.unpack(">II", header)
                if length > EC_MAX_PACKET:
                    raise EmuleError("EC 回包声明长度异常（%d 字节）" % length)
                payload = self._recv_exact(sock, length) if length else b""
                self._inbox.put(decode_packet(flags, payload))
        except Exception as exc:                       # noqa: BLE001 - 统一转成断线哨兵
            self._inbox.put(_Broken("EC 连接中断：%s" % (exc,)))

    @staticmethod
    def _recv_exact(sock, count):
        """从 socket 读满 count 字节。

        **读线程不能用 socket 超时判断断线**：这条连接是长连接，两次请求之间
        空闲几十秒很正常，而 sock 的 timeout 是给「等请求回包」设的（默认 10 秒）。
        早先这里把 socket.timeout 当成断线，空闲 10 秒读线程就退出，下一次请求
        先撞上一个「连接已断」的哨兵再重连 —— 表现为面板每 10 秒重连一次引擎，
        按连接累积的增量缓存也跟着每 10 秒清空一次。
        所以超时只是「现在还没数据」，继续等；只有 recv 返回空才是真断开。
        """
        chunks = []
        remaining = count
        while remaining > 0:
            try:
                chunk = sock.recv(remaining)
            except socket.timeout:
                continue
            except OSError as exc:
                raise EmuleOffline("EC 连接中断：%s" % exc)
            if not chunk:
                raise EmuleOffline("EC 连接已被 aMule 关闭")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _send(self, opcode, nodes=(), detail=None):
        frame = build_packet(opcode, nodes, detail)
        sock = self._sock
        if sock is None:
            raise EmuleOffline("EC 尚未连接")
        try:
            sock.sendall(frame)
        except OSError as exc:
            self.close()
            raise EmuleOffline("EC 发送失败：%s" % exc)

    def _recv_one(self, deadline):
        remaining = deadline - time.time()
        if remaining <= 0:
            self.close()
            raise EmuleTimeout("EC 等待回包超时（%.0f 秒）" % self.timeout)
        try:
            item = self._inbox.get(timeout=remaining)
        except queue.Empty:
            self.close()
            raise EmuleTimeout("EC 等待回包超时（%.0f 秒）" % self.timeout)
        if isinstance(item, _Broken):
            self.close()
            raise EmuleOffline(item.reason)
        return item

    def _await_reply(self, expected, deadline):
        while True:
            packet = self._recv_one(deadline)
            # 之前发过不等回包的请求（SHAREDFILES_RELOAD），它回来的是 NOOP：
            # 那是给上一个请求的收尾，不能当成本次请求的响应。
            if packet.opcode == Op.NOOP and self._pending_noop > 0:
                self._pending_noop -= 1
                continue
            if expected is None or packet.opcode in expected:
                return packet
            if packet.opcode not in PUSH_OPCODES:
                return packet
            self._dispatch_push(packet)

    def _dispatch_push(self, packet):
        handler = self.on_push
        if handler is None:
            return
        try:
            handler(packet)
        except Exception:                              # noqa: BLE001 - 推送处理不能影响主流程
            pass

    def _authenticate(self):
        login = [
            tag_string(Tag.CLIENT_NAME, self.client_name),
            tag_string(Tag.CLIENT_VERSION, self.client_version),
            tag_uint(Tag.PROTOCOL_VERSION, EC_PROTOCOL_VERSION),
        ]
        self._send(Op.AUTH_REQ, login)
        deadline = time.time() + self.timeout
        reply = self._await_reply((Op.AUTH_SALT, Op.AUTH_FAIL), deadline)
        password_hash = hashlib.md5(self.password.encode("utf-8")).hexdigest()
        if reply.opcode == Op.AUTH_SALT:
            salt_tag = reply.get(Tag.PASSWD_SALT)
            if salt_tag is None:
                raise EmuleOffline("EC 握手失败：aMule 未返回密码盐")
            salt_text = format(salt_tag.int(), "X")     # 服务端用 CFormat("%lX")
            salt_hash = hashlib.md5(salt_text.encode("utf-8")).hexdigest()
            password_hash = hashlib.md5((password_hash.lower() + salt_hash)
                                        .encode("utf-8")).hexdigest()
        elif reply.opcode == Op.AUTH_FAIL:
            raise EmuleOffline("EC 鉴权被拒绝：%s" % (reply.child_text(Tag.STRING) or "密码错误"))
        self._send(Op.AUTH_PASSWD, [tag_hash(Tag.PASSWD_HASH, password_hash)])
        deadline = time.time() + self.timeout
        reply = self._await_reply((Op.AUTH_OK, Op.AUTH_FAIL), deadline)
        if reply.opcode != Op.AUTH_OK:
            raise EmuleOffline("EC 鉴权失败：%s" % (reply.child_text(Tag.STRING) or "密码错误"))
        self.server_version = reply.child_text(Tag.SERVER_VERSION)
        protocol = reply.get(Tag.PROTOCOL_VERSION)
        self.protocol_version = protocol.int() if protocol is not None else EC_PROTOCOL_VERSION

    # -- 通用请求 -----------------------------------------------------
    def request(self, opcode, nodes=(), detail=None, timeout=None, retry=True):
        """发一个请求并等待回包；EC_OP_FAILED 转成 EmuleError。"""
        frame = build_packet(opcode, nodes, detail)
        expected = _EXPECTED.get(opcode)
        with self._lock:
            attempt = 0
            while True:
                if self._sock is None:
                    self._open()
                sock = self._sock
                try:
                    sock.sendall(frame)
                except OSError as exc:
                    self.close()
                    if retry and attempt == 0:
                        attempt += 1
                        continue
                    raise EmuleOffline("EC 发送失败：%s" % exc)
                deadline = time.time() + (timeout or self.timeout)
                try:
                    packet = self._await_reply(expected, deadline)
                except EmuleTimeout:
                    # 超时重试没有意义（重发也要再等一轮），直接上抛，让面板立即回 504
                    raise
                except EmuleOffline:
                    if retry and attempt == 0:
                        attempt += 1
                        time.sleep(0.2)
                        continue
                    raise
                if packet.opcode == Op.FAILED:
                    raise EmuleError(translate_error(packet.child_text(Tag.STRING)))
                return packet

    # -- 状态 ---------------------------------------------------------
    def get_connstate(self, timeout=None):
        packet = self.request(Op.GET_CONNSTATE, timeout=timeout)
        tag = packet.get(Tag.CONNSTATE)
        if tag is None:
            raise EmuleError("aMule 未返回连接状态")
        return connstate_record(tag)

    def stat_request(self, timeout=None):
        """EC_OP_STAT_REQ：一次拿到速度/计数/连接状态/日志行。"""
        return stats_record(self.request(Op.STAT_REQ, timeout=timeout))

    def download_queue(self):
        packet = self.request(Op.GET_DLOAD_QUEUE, detail=Detail.FULL)
        return [partfile_record(tag) for tag in packet.all(Tag.PARTFILE)]

    def upload_queue(self):
        packet = self.request(Op.GET_ULOAD_QUEUE, detail=Detail.FULL)
        return [client_record(tag) for tag in packet.all(Tag.CLIENT)]

    def shared_files(self):
        packet = self.request(Op.GET_SHARED_FILES, detail=Detail.FULL)
        return [sharedfile_record(tag) for tag in packet.all(Tag.KNOWNFILE)]

    def server_list(self):
        packet = self.request(Op.GET_SERVER_LIST, detail=Detail.FULL)
        return [server_record(tag) for tag in packet.all(Tag.SERVER)]

    def get_update(self):
        """EC_OP_GET_UPDATE（增量）：文件/客户端/服务器/好友一次性取回。

        客户端 tag 带 EC_TAG_CLIENT_REQUEST_FILE，可据此把下载来源归属到具体文件；
        tag 自身数据是 ECID（而不是 IPv4），因此也是服务器 ECID 的唯一来源。

        **detail 必须用 INC_UPDATE，不能换成其它级别。** ExternalConn.cpp 的
        EC_OP_GET_UPDATE 分支只在 detail == EC_DETAIL_INC_UPDATE 时装配回包，其它级别下
        response 保持 NULL，于是走到包末尾的 wxFAIL（invalid opcode received: 0x52）——
        amuled 在 wx 断言后会断开这条 EC 连接，面板后续请求全部失败。

        回包结构是**两层**：顶层的 CLIENT / SERVER 只是空容器（CECEmptyTag，自身没有
        CLIENT_NAME 之类的字段），真正的客户端节点挂在容器的 children 里，CLIENT_NAME
        还再往下一层。所以必须遍历容器子节点逐个解析，不能拿顶层容器去判断。
        """
        packet = self.request(Op.GET_UPDATE, detail=Detail.INC_UPDATE)
        files, client_tags, server_tags = [], [], []
        for tag in packet.children:
            if tag.name == Tag.PARTFILE:
                files.append(partfile_record(tag))
            elif tag.name == Tag.CLIENT:
                client_tags.extend(_update_client_child_tags(tag))
            elif tag.name == Tag.SERVER:
                server_tags.extend(_update_server_child_tags(tag))
        # 文件每次请求都带最新状态，直接用；客户端与服务器是增量的，走按连接累积。
        clients = self._merge_update_cache("clients", client_tags, client_record)
        servers = self._merge_update_cache("servers", server_tags, server_record)
        return {"files": files, "clients": clients, "servers": servers}

    def _merge_update_cache(self, kind, tags, build):
        """把这次的增量 tag 合并进按连接累积的缓存，返回该类的完整当前快照。

        aMule 的增量语义（实测）：同一条连接上第一次回全量，之后每次只回
        **这一轮有变化的**条目 —— 带字段的是更新，只带 ECID 存根的是「这个编号
        还在，但字段没变」。所以：
          * 带字段的 tag → 解析后刷新缓存；
          * 存根 → 保留缓存里那份，只续一下存活时间；
          * **本次没出现的绝不能删** —— 没出现只表示这一轮没变化，
            当成「消失了」会把大部分来源误删（实测 4 条来源会掉成 1 条）。
        真正失效的条目靠存活超时清理，见 _UPDATE_CACHE_TTL。
        """
        cache = self._update_cache.get(kind)
        if cache is None:
            cache = self._update_cache[kind] = {}
        now = time.monotonic()
        for tag in tags or []:
            children = getattr(tag, "children", None) or []
            if children:
                ecid = int(build(tag).get("ecid") or 0) or int(tag.int() or 0)
                if not ecid:
                    continue
                # aMule 的回包有三种形态：全量（几十个字段）、部分更新（只有速度 /
                # 已下载 / 队列名次这几个）、以及只有 ECID 的存根。部分更新**不是**
                # 完整记录，直接覆盖会把名字和 IP 抹掉（实测来源会变成「一行没有 IP」）。
                # 所以按字段合并：这次给了哪些字段就更新哪些，没给的沿用旧值。
                patch = _filled_fields(build(tag))
                entry = cache.get(ecid)
                if entry is None:
                    # 第一次见到：至少是有字段的 tag，照常建一条
                    cache[ecid] = {"record": build(tag), "seen": now}
                    continue
                record = dict(entry["record"])
                record.update(patch)
                entry["record"] = record
                entry["seen"] = now
                continue
            ecid = tag.int()
            if ecid is None:
                continue
            entry = cache.get(int(ecid))
            if entry is not None:
                entry["seen"] = now
        for ecid in [key for key, entry in cache.items()
                     if now - entry["seen"] > _UPDATE_CACHE_TTL]:
            del cache[ecid]
        return [entry["record"] for entry in cache.values()]

    # -- 下载任务 -----------------------------------------------------
    def add_link(self, link, category=None):
        """EC_OP_ADD_LINK；一个请求只带一个链接以便逐条判定结果。"""
        nodes = [tag_string(Tag.STRING, link)]
        if category is not None:
            nodes[0].children.append(tag_uint(Tag.PARTFILE_CAT, int(category)))
        self.request(Op.ADD_LINK, nodes, retry=False)
        return True

    def partfile_command(self, opcode, file_hash, extra=None):
        """PAUSE/RESUME/STOP/PRIO_SET/DELETE —— 都是“PARTFILE tag + 可选子 tag”。"""
        node = tag_hash(Tag.PARTFILE, file_hash)
        if extra is not None:
            node.children.append(extra)
        packet = self.request(opcode, [node])
        return packet

    def set_partfile_priority(self, file_hash, prio_value):
        return self.partfile_command(Op.PARTFILE_PRIO_SET, file_hash,
                                     tag_uint(Tag.STRING, int(prio_value)))

    def clear_completed(self, ecids):
        if not ecids:
            return False
        self.request(Op.CLEAR_COMPLETED, [tag_uint(Tag.ECID, ecid) for ecid in ecids])
        return True

    # -- 服务器 -------------------------------------------------------
    def server_connect(self, ip, port):
        self.request(Op.SERVER_CONNECT, [tag_ip(Tag.SERVER, ip, port)])
        return True

    def server_disconnect(self):
        self.request(Op.SERVER_DISCONNECT)
        return True

    def server_add(self, ip, port, name=""):
        nodes = [tag_string(Tag.SERVER_ADDRESS, "%s:%d" % (ip, int(port)))]
        if name:
            nodes.append(tag_string(Tag.SERVER_NAME, name))
        self.request(Op.SERVER_ADD, nodes)
        return True

    def server_remove(self, ip, port):
        self.request(Op.SERVER_REMOVE, [tag_ip(Tag.SERVER, ip, port)])
        return True

    def server_set_priority(self, ecid, priority):
        self.request(Op.SERVER_SET_STATIC_PRIO, [
            tag_uint(Tag.SERVER, int(ecid)),
            tag_uint(Tag.SERVER_PRIO, int(priority)),
        ])
        return True

    # -- Kad / 网络 ---------------------------------------------------
    def connect_network(self):
        packet = self.request(Op.CONNECT)
        return [translate_message(tag.text()) for tag in packet.all(Tag.STRING)]

    def disconnect_network(self):
        packet = self.request(Op.DISCONNECT)
        return [translate_message(tag.text()) for tag in packet.all(Tag.STRING)]

    def kad_start(self):
        self.request(Op.KAD_START)
        return True

    def kad_stop(self):
        self.request(Op.KAD_STOP)
        return True

    def kad_bootstrap_ip(self, ip_uint32, port):
        self.request(Op.KAD_BOOTSTRAP_FROM_IP, [
            tag_uint(Tag.BOOTSTRAP_IP, ip_uint32),
            tag_uint(Tag.BOOTSTRAP_PORT, port),
        ])
        return True

    def ipfilter_reload(self):
        self.request(Op.IPFILTER_RELOAD)
        return True

    def sharedfiles_reload(self):
        """触发 aMule 重扫共享目录；发完就走，不等回包。

        这一个 opcode 在 aMule 侧是**同步**跑完整轮扫描的（ExternalConn.cpp 收到后
        直接调 CSharedFileList::Reload()，里面逐目录遍历再排哈希任务）。共享目录一多
        就要几十秒，而 EC 请求在这条连接上是严格串行的 —— 等它的这几十秒里，
        概览 / 任务 / 日志所有请求全排在后面，前端表现成整页卡死。

        所以只把请求发出去，把"待回收的 NOOP 回包"记个数：它回来的时候由
        _await_reply 当作迟到回包丢掉，不会被下个请求误认成自己的响应。
        """
        with self._lock:
            if self._sock is None:
                self._open()
            self._send(Op.SHAREDFILES_RELOAD)
            self._pending_noop += 1
        return True

    # -- 搜索 ---------------------------------------------------------
    def search_start(self, query, search_type, file_type="", extension="",
                     min_size=0, max_size=0, availability=0):
        """EC_OP_SEARCH_START：第一个 tag 必须是 EC_TAG_SEARCH_TYPE（服务端会强转）。"""
        search_tag = tag_uint(Tag.SEARCH_TYPE, int(search_type))
        search_tag.children.append(tag_string(Tag.SEARCH_NAME, query))
        search_tag.children.append(tag_string(Tag.SEARCH_FILE_TYPE, file_type or ""))
        if extension:
            search_tag.children.append(tag_string(Tag.SEARCH_EXTENSION, extension))
        if availability:
            search_tag.children.append(tag_uint(Tag.SEARCH_AVAILABILITY, availability))
        if min_size:
            search_tag.children.append(tag_uint(Tag.SEARCH_MIN_SIZE, min_size))
        if max_size:
            search_tag.children.append(tag_uint(Tag.SEARCH_MAX_SIZE, max_size))
        packet = self.request(Op.SEARCH_START, [search_tag], retry=False)
        return [translate_message(tag.text()) for tag in packet.all(Tag.STRING)]

    def search_progress(self):
        packet = self.request(Op.SEARCH_PROGRESS)
        tag = packet.get(Tag.SEARCH_STATUS)
        return tag.int() if tag is not None else 0

    def search_results(self):
        packet = self.request(Op.SEARCH_RESULTS, detail=Detail.FULL)
        return [search_record(tag) for tag in packet.all(Tag.SEARCHFILE)]

    def search_stop(self):
        self.request(Op.SEARCH_STOP)
        return True

    def download_search_result(self, file_hash, category=0):
        node = tag_hash(Tag.SEARCHFILE, file_hash)
        node.children.append(tag_uint(Tag.PARTFILE_CAT, int(category)))
        self.request(Op.DOWNLOAD_SEARCH_RESULT, [node])
        return True

    # -- 日志 / 统计 / 偏好 -------------------------------------------
    def log_lines(self):
        """EC_OP_GET_LOG：整个日志缓冲区，按行返回。"""
        packet = self.request(Op.GET_LOG, timeout=max(self.timeout, LONG_TIMEOUT))
        return [tag.text() for tag in packet.all(Tag.STRING)]

    def stat_tree(self):
        """EC_OP_GET_STATSTREE：返回扁平 [{group, name, label, value, value_type}]。"""
        packet = self.request(Op.GET_STATSTREE, detail=Detail.FULL,
                              timeout=max(self.timeout, LONG_TIMEOUT))
        nodes = [tag for tag in packet.children if tag.name == Tag.STATTREE_NODE]
        flat = []
        for node in nodes:
            _flatten_stat_node(node, "", flat)
        return flat

    def get_prefs(self, selection=None):
        selection = Prefs.ALL_USED if selection is None else int(selection)
        packet = self.request(Op.GET_PREFERENCES, [tag_uint(Tag.SELECT_PREFS, selection)],
                              timeout=max(self.timeout, LONG_TIMEOUT))
        return decode_prefs(packet)

    def set_prefs(self, nodes, selection=None):
        selection = Prefs.ALL_USED if selection is None else int(selection)
        payload = [tag_uint(Tag.SELECT_PREFS, selection)] + list(nodes)
        self.request(Op.SET_PREFERENCES, payload, timeout=max(self.timeout, LONG_TIMEOUT))
        return True

    def shutdown_core(self):
        self.request(Op.SHUTDOWN)
        return True


def _flatten_stat_node(tag, path, out):
    """EC_TAG_STATTREE_NODE 递归展开（对应 CEC_StatTree_Node_Tag::GetDisplayString）。"""
    label = tag.text()
    node_path = (path + " / " + label) if path else label
    for value_tag in tag.all(Tag.STAT_NODE_VALUE):
        out.append({
            "group": path,
            "name": label,
            "label": node_path,
            "value": stat_value_text(value_tag),
            "raw": stat_value_raw(value_tag),
            "value_type": stat_value_type(value_tag),
        })
    for child in tag.all(Tag.STATTREE_NODE):
        _flatten_stat_node(child, node_path, out)


def stat_value_type(tag):
    type_tag = tag.get(Tag.STAT_VALUE_TYPE)
    return type_tag.int() if type_tag is not None else ValueType.INTEGER


def stat_value_raw(tag):
    if stat_value_type(tag) in (ValueType.STRING,):
        return tag.text()
    if stat_value_type(tag) == ValueType.DOUBLE:
        return tag.float()
    return tag.int()


def stat_value_text(tag):
    """把统计值转成人类可读字符串（bytes/时间/速率做单位换算）。"""
    value_type = stat_value_type(tag)
    if value_type == ValueType.STRING:
        return tag.text()
    if value_type == ValueType.DOUBLE:
        return "%.2f" % tag.float()
    value = tag.int()
    if value_type == ValueType.BYTES:
        return format_bytes(value)
    if value_type == ValueType.TIME:
        return format_duration(value)
    if value_type == ValueType.SPEED:
        return "%s/s" % format_bytes(value)
    return str(value)


def format_bytes(value):
    """字节数转人类可读。"""
    value = float(value or 0)
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    index = 0
    while value >= 1024.0 and index < len(units) - 1:
        value /= 1024.0
        index += 1
    if index == 0:
        return "%d B" % int(value)
    return "%.2f %s" % (value, units[index])


def format_duration(seconds):
    """秒数转 Xh Ym Zs。"""
    seconds = int(seconds or 0)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return "%dh %dm %ds" % (hours, minutes, secs)
    if minutes:
        return "%dm %ds" % (minutes, secs)
    return "%ds" % secs


def format_speed(value):
    return "%s/s" % format_bytes(value)


# ---------------------------------------------------------------- 偏好解码

def _prefs_bool(tab, name):
    return tab is not None and tab.has(name)


def decode_prefs(packet):
    """EC_OP_GET_PREFERENCES 回包 → 面板 engine 设置字典。"""
    prefs = {}
    general = packet.get(Tag.PREFS_GENERAL)
    if general is not None:
        prefs["nick"] = general.child_text(Tag.USER_NICK)
        prefs["user_hash"] = (general.get(Tag.USER_HASH).hexhash()
                              if general.get(Tag.USER_HASH) else "")
        prefs["check_new_version"] = bool(general.child_value(Tag.GENERAL_CHECK_NEW_VERSION))
    conn = packet.get(Tag.PREFS_CONNECTIONS)
    if conn is not None:
        prefs["max_download"] = conn.child_value(Tag.CONN_MAX_DL)
        prefs["max_upload"] = conn.child_value(Tag.CONN_MAX_UL)
        prefs["max_connections"] = conn.child_value(Tag.CONN_MAX_CONN)
        prefs["max_sources"] = conn.child_value(Tag.CONN_MAX_FILE_SOURCES)
        prefs["tcp_port"] = conn.child_value(Tag.CONN_TCP_PORT)
        prefs["udp_port"] = conn.child_value(Tag.CONN_UDP_PORT)
        prefs["slot_allocation"] = conn.child_value(Tag.CONN_SLOT_ALLOCATION)
        prefs["udp_disabled"] = conn.has(Tag.CONN_UDP_DISABLE)
        prefs["autoconnect"] = conn.has(Tag.CONN_AUTOCONNECT)
        prefs["reconnect"] = conn.has(Tag.CONN_RECONNECT)
        prefs["connect_ed2k"] = conn.has(Tag.NETWORK_ED2K)
        prefs["connect_kad"] = conn.has(Tag.NETWORK_KADEMLIA)
    files = packet.get(Tag.PREFS_FILES)
    if files is not None:
        prefs["ich"] = files.has(Tag.FILES_ICH_ENABLED)
        prefs["aich"] = not files.has(Tag.FILES_AICH_TRUST)
        prefs["add_paused"] = files.has(Tag.FILES_NEW_PAUSED)
        prefs["add_auto_prio"] = files.has(Tag.FILES_NEW_AUTO_DL_PRIO)
        prefs["preview_prio"] = files.has(Tag.FILES_PREVIEW_PRIO)
        prefs["start_next_paused"] = files.has(Tag.FILES_START_NEXT_PAUSED)
        prefs["resume_same_cat"] = files.has(Tag.FILES_RESUME_SAME_CAT)
        prefs["save_sources"] = files.has(Tag.FILES_SAVE_SOURCES)
        prefs["alloc_full_size"] = files.has(Tag.FILES_ALLOC_FULL_SIZE)
        prefs["check_diskspace"] = files.has(Tag.FILES_CHECK_FREE_SPACE)
        prefs["min_free_space"] = files.child_value(Tag.FILES_MIN_FREE_SPACE)
    dirs = packet.get(Tag.PREFS_DIRECTORIES)
    if dirs is not None:
        prefs["incoming_dir"] = dirs.child_text(Tag.DIRECTORIES_INCOMING)
        prefs["temp_dir"] = dirs.child_text(Tag.DIRECTORIES_TEMP)
        shared = dirs.get(Tag.DIRECTORIES_SHARED)
        if shared is not None:
            prefs["shared_dirs"] = [child.text() for child in shared.children
                                    if child.name == Tag.STRING]
        prefs["share_hidden"] = dirs.child_value(Tag.DIRECTORIES_SHARE_HIDDEN) > 0
    security = packet.get(Tag.PREFS_SECURITY)
    if security is not None:
        prefs["can_see_shares"] = security.child_value(Tag.SECURITY_CAN_SEE_SHARES)
        prefs["ipfilter"] = security.has(Tag.IPFILTER_CLIENTS) or security.has(Tag.IPFILTER_SERVERS)
        prefs["ipfilter_clients"] = security.has(Tag.IPFILTER_CLIENTS)
        prefs["ipfilter_servers"] = security.has(Tag.IPFILTER_SERVERS)
        prefs["ipfilter_auto"] = security.has(Tag.IPFILTER_AUTO_UPDATE)
        prefs["ipfilter_url"] = security.child_text(Tag.IPFILTER_UPDATE_URL)
        prefs["ipfilter_level"] = security.child_value(Tag.IPFILTER_LEVEL)
        prefs["filter_lan"] = security.has(Tag.IPFILTER_FILTER_LAN)
        prefs["secure_ident"] = security.has(Tag.SECURITY_USE_SECIDENT)
        prefs["obfuscation"] = security.has(Tag.SECURITY_OBFUSCATION_SUPPORTED)
    servers = packet.get(Tag.PREFS_SERVERS)
    if servers is not None:
        prefs["remove_dead_servers"] = servers.has(Tag.SERVERS_REMOVE_DEAD)
        prefs["dead_server_retries"] = servers.child_value(Tag.SERVERS_DEAD_SERVER_RETRIES)
        prefs["auto_serverlist"] = servers.has(Tag.SERVERS_AUTO_UPDATE)
        prefs["add_from_server"] = servers.has(Tag.SERVERS_ADD_FROM_SERVER)
        prefs["add_from_client"] = servers.has(Tag.SERVERS_ADD_FROM_CLIENT)
        prefs["use_score_system"] = servers.has(Tag.SERVERS_USE_SCORE_SYSTEM)
        prefs["smart_id_check"] = servers.has(Tag.SERVERS_SMART_ID_CHECK)
        prefs["safe_server_connect"] = servers.has(Tag.SERVERS_SAFE_SERVER_CONNECT)
        prefs["autoconn_static_only"] = servers.has(Tag.SERVERS_AUTOCONN_STATIC_ONLY)
        prefs["manual_high_prio"] = servers.has(Tag.SERVERS_MANUAL_HIGH_PRIO)
        prefs["servers_url"] = servers.child_text(Tag.SERVERS_UPDATE_URL)
    coretweaks = packet.get(Tag.PREFS_CORETWEAKS)
    if coretweaks is not None:
        prefs["max_conn_per_five"] = coretweaks.child_value(Tag.CORETW_MAX_CONN_PER_FIVE)
        prefs["file_buffer"] = coretweaks.child_value(Tag.CORETW_FILEBUFFER)
        prefs["ul_queue"] = coretweaks.child_value(Tag.CORETW_UL_QUEUE)
        prefs["server_keepalive"] = coretweaks.child_value(Tag.CORETW_SRV_KEEPALIVE_TIMEOUT)
    kad = packet.get(Tag.PREFS_KADEMLIA)
    if kad is not None:
        prefs["nodes_url"] = kad.child_text(Tag.KADEMLIA_UPDATE_URL)
    onlinesig = packet.get(Tag.PREFS_ONLINESIG)
    if onlinesig is not None:
        prefs["online_signature"] = onlinesig.has(Tag.ONLINESIG_ENABLED)
    return prefs
