from __future__ import print_function

import fcntl
import serial
import aioserial
import array as arr
import time
import struct
import stretch_body.cobbs_framing as cobbs_framing
import copy

"""
TODO: Describe how transport layer works
"""

# #################################################################################

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


class TransportError(Exception):
    """Base class for exceptions in this module."""
    pass

# #################################################################################

class Transport():
    """
    Asynchronous comms with serial devices
    """
    def __init__(self,usb_name, verbose=False):
        self.usb_name=usb_name
        self.verbose=verbose
        self.write_error = 0
        self.read_error = 0
        self.rpc_queue = []
        self.rpc_queue2 = []
        self.itr = 0
        self.itr_time = 0
        self.tlast = 0
        self.ser=None
        self.payload_out = arr.array('B', [0] * (RPC_DATA_SIZE + 1))
        self.framer = cobbs_framing.CobbsFraming()
        self.status = {'rate': 0, 'read_error': 0, 'write_error': 0, 'itr': 0, 'transaction_time_avg': 0,
                       'transaction_time_max': 0, 'timestamp_pc': 0}
    def startup(self):
        if self.verbose:
            print('Starting TransportConnection on: ' + self.usb_name)
        try:
            self.ser = aioserial.AioSerial(port=self.usb_name)
            if self.ser.isOpen():
                try:
                    fcntl.flock(self.ser.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except IOError:
                    print('Port %s is busy. Check if another Stretch Body process is already running' % self.usb_name)
                    self.ser.close()
                    self.ser = None
        except serial.SerialException as e:
            print("SerialException({0}): {1}".format(e.errno, e.strerror))
            self.ser = None
        return self.ser is not None #return if hardware connection valid

    def queue_rpc(self,n,reply_callback):
        if self.ser:
            self.rpc_queue.append((copy.copy(self.payload_out[:n]),reply_callback))

    def queue_rpc2(self,n,reply_callback):
        if self.ser:
            self.rpc_queue2.append((copy.copy(self.payload_out[:n]),reply_callback))

    async def _recv_framed_data(self):
        timeout = .2  # Was .05 but on heavy loads can get starved
        packet_marker = 0
        t_start = time.time()
        rx_buffer = []
        while ((time.time() - t_start) < timeout):
            #TODO: Drop inWaiting, just await
            nn = self.ser.inWaiting()
            if (nn > 0):
                rbuf = await self.ser.read_async(nn)
                nu = 0
                for byte_in in rbuf:
                    nu = nu + 1
                    if (type(byte_in) == str):  # Py2 needs this, Py3 not
                        byte_in = struct.unpack('B', byte_in)[0]
                    if byte_in == packet_marker:
                        crc_ok, nr, decoded_data = self.framer.decode_data(rx_buffer)
                        if nu < nn:
                            print('Warning: Transport dropped %d bytes during recv_framed_data' % (nn - nu))
                        return crc_ok, nr, decoded_data
                    else:
                        rx_buffer.append(byte_in)
        return 0, 0, []

    async def _step_frame(self,id, ack, data, ack_alt=None):
        """
        id: RPC Request ID
        ack: RPC acknowledge ID
        data: frame data to send to uC
        """
        buf_tx = arr.array('B', [id]+data)  # TODO, move to bytes
        encoded_data=arr.array('B',self.framer.encode_data(buf_tx))
        await self.ser.write_async(encoded_data)
        crc, nr, buf_rx = await self._recv_framed_data()
        if crc==1 and (buf_rx[0]==ack or buf_rx[0]==ack_alt):
            return buf_rx, nr
        else:
            print('Transport Frame Error| CRC valid %d | Num bytes rcvd %d | Ack desired %d | Ack recvd %d'%(crc, nr, ack, buf_rx[0]))
            raise TransportError

    async def step_rpc(self,rpc,rpc_callback): #Handle a single RPC transaction
        try:
            #Start new RPC transmission
            ts = time.time()
            tsa=ts
            await self._step_frame(id=RPC_START_NEW_RPC,ack=RPC_ACK_NEW_RPC,data=[])
            #Send all RPC data down in one or more frames
            ntx = 0
            while ntx < len(rpc):
                nb = min(len(rpc) - ntx, RPC_BLOCK_SIZE)  # Num bytes to send
                b = rpc[ntx:ntx + nb]
                ntx = ntx + nb
                if ntx == len(rpc):  # Last block
                    await self._step_frame(id=RPC_SEND_BLOCK_LAST, ack=RPC_ACK_SEND_BLOCK_LAST,data=b)
                else:
                    await self._step_frame(id=RPC_SEND_BLOCK_MORE, ack=RPC_ACK_SEND_BLOCK_MORE,data=b)

            #Now receive RPC reply in one or more frames
            reply = []
            while True: #TODO: Timeout in case very corrupted comms
                ts = time.time()
                buf_rx, nr =await self._step_frame(id=RPC_GET_BLOCK, ack=RPC_ACK_GET_BLOCK_LAST, data=[], ack_alt=RPC_ACK_GET_BLOCK_MORE)
                reply = reply + buf_rx[1:nr]
                if buf_rx[0]==RPC_ACK_GET_BLOCK_LAST:
                    break
            rpc_callback(arr.array('B', reply))  # Now process the reply
        except TransportError as e:
            print("TransportError: %s : %s" % (self.usb_name, str(e)))
        except serial.SerialTimeoutException as e:
            print("SerialTimeoutException: %s : %s" % (self.usb_name, str(e)))
        except serial.SerialException as e:
            print("SerialException: %s : %s" % (self.usb_name, str(e)))
        except TypeError as e:
            print("TypeError: %s : %s" % (self.usb_name, str(e)))

    async def step(self,exiting=False):
        if not self.ser:
            return
        if exiting:
            time.sleep(0.1) #May have been a hard exit, give time for bad data to land, remove, do final RPC
            self.ser.reset_output_buffer()
            self.ser.reset_input_buffer()

        #This will block until all RPCs have been commpleted
        #called by body thread at cyclic rate
        self.itr += 1
        self.itr_time = time.time() - self.tlast
        self.tlast = time.time()
        #Now run RPC calls
        while len(self.rpc_queue):
            rpc,reply_callback=self.rpc_queue[0]
            #if dbg_on:
            #    print('RPC of',reply_callback)
            await self.step_rpc(rpc,reply_callback)
            self.rpc_queue = self.rpc_queue[1:]

        # Update status
        if self.itr_time != 0:
            self.status['rate'] = 1 / self.itr_time
        else:
            self.status['rate'] = 0
        self.status['read_error'] = self.read_error
        self.status['write_error'] = self.write_error
        self.status['itr'] = self.itr

    async def step2(self,exiting=False):
        if not self.ser:
            return
        if exiting:
            time.sleep(0.1)  # May have been a hard exit, give time for bad data to land, remove, do final RPC
            self.ser.reset_output_buffer()
            self.ser.reset_input_buffer()
        while len(self.rpc_queue2):
            rpc,reply_callback=self.rpc_queue2[0]
            await self.step_rpc(rpc,reply_callback)
            self.rpc_queue2 = self.rpc_queue2[1:]
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



















