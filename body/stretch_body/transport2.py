from __future__ import print_function
import serial
import time
import struct
import array as arr
import stretch_body.cobbs_framing as cobbs_framing
import copy
import fcntl

import asyncio
import serial_asyncio


RPC_START_NEW_RPC =100
RPC_ACK_NEW_RPC= 101

RPC_SEND_BLOCK_MORE = 102
RPC_ACK_SEND_BLOCK_MORE = 103
RPC_SEND_BLOCK_LAST = 104
RPC_ACK_SEND_BLOCK_LAST = 105

RPC_GET_BLOCK = 106
RPC_ACK_GET_BLOCK_MORE = 107
RPC_ACK_GET_BLOCK_LAST = 108

RPC_BLOCK_SIZE = 32
RPC_DATA_SIZE = 1024

dbg_on = 0

# ##############################################
"""
Loop protocol is:

RPC Data is sent over a COBBS encoding with CRC error detection.

The  packet is:

Data can be up to X bytes.

Data is mannually packed / unpacked into dictionaries (Python) and C-structs (Arduino). 
Care should be taken that the pack/unpack size and types are consistent between the two.
This is not automated.
"""

# ##################### TRANSPORT ####################################



class TransportError(Exception):
    """Base class for exceptions in this module."""
    pass








# #####################################
def pack_string_t(s,sidx,x):
    n=len(x)
    return struct.pack_into(str(n)+'s',s,sidx,x)

def unpack_string_t(s,n):
    return (struct.unpack(str(n)+'s', s[:n])[0].strip(b'\x00')).decode('utf-8')

def unpack_int32_t(s):
    return struct.unpack('i',s[:4])[0]

def unpack_uint32_t(s):
    return struct.unpack('I',s[:4])[0]

def unpack_int16_t(s):
    return struct.unpack('h',s[:2])[0]

def unpack_uint16_t(s):
    return struct.unpack('H',s[:2])[0]

def unpack_uint8_t(s):
    return struct.unpack('B',s[:1])[0]

def unpack_float_t(s):
    return struct.unpack('f', s[:4])[0]

def unpack_double_t(s):
    return struct.unpack('d', s[:8])[0]

def pack_float_t(s,sidx,x):
    return struct.pack_into('f',s,sidx,x)

def pack_double_t(s,sidx,x):
    return struct.pack_into('d',s,sidx,x)

def pack_int32_t(s,sidx,x):
    return struct.pack_into('i',s,sidx,x)

def pack_uint32_t(s,sidx,x):
    return struct.pack_into('I',s,sidx,x)

def pack_int16_t(s,sidx,x):
    return struct.pack_into('h',s,sidx,x)

def pack_uint16_t(s,sidx,x):
    return struct.pack_into('H',s,sidx,x)

def pack_uint8_t(s,sidx,x):
    return struct.pack_into('B',s,sidx,x)



















