from __future__ import print_function
from stretch_body.transport import *
from stretch_body.device import Device
import threading
import textwrap

RPC_SET_WACC_CONFIG = 1
RPC_REPLY_WACC_CONFIG = 2
RPC_GET_WACC_STATUS = 3
RPC_REPLY_WACC_STATUS = 4
RPC_SET_WACC_COMMAND = 5
RPC_REPLY_WACC_COMMAND = 6
RPC_GET_WACC_BOARD_INFO =7
RPC_REPLY_WACC_BOARD_INFO =8

TRIGGER_BOARD_RESET = 1

# ######################## WACC #################################

class Wacc(Device):
    """
    API to the Stretch RE1 wrist+accelerometer (Wacc) board
    The Wacc has:
    -- 3-axis accelerometer reported as Ax,Ay,and Az
    -- Two digital inputs D0, D1
    -- Two digital outputs D2, D3
    -- One analog input: A0
    -- A single tap count based on the accelerometer

    ext_status_cb: Callback to handle custom status data
    ext_command_cb: Callback to handle custom command data
    """

    def __init__(self, ext_status_cb=None, ext_command_cb=None):
        Device.__init__(self, 'wacc')
        self.ext_status_cb=ext_status_cb
        self.ext_command_cb=ext_command_cb
        self.lock=threading.RLock()
        self.config = self.params['config']
        self._dirty_config = True #Force push down
        self._dirty_command = False
        self._command = {'d2':0,'d3':0, 'trigger':0}
        self.name ='hello-wacc'
        self.transport = Transport(usb='/dev/hello-wacc', logger=self.logger)
        self.status = { 'ax':0,'ay':0,'az':0,'a0':0,'d0':0,'d1':0, 'd2':0,'d3':0,'single_tap_count': 0, 'state':0, 'debug':0,
                       'timestamp': 0,
                       'transport': self.transport.status}
        self.ts_last=None
        self.board_info = {'board_version': None, 'firmware_version': None, 'protocol_version': None}
        self.valid_firmware_protocol = 'p0'
        self.hw_valid = False

    # ###########  Device Methods #############

    def startup(self):
        with self.lock:
            self.hw_valid=self.transport.startup()
            if self.hw_valid:
                # Pull board info
                self.transport.payload_out[0] = RPC_GET_WACC_BOARD_INFO
                self.transport.queue_rpc(1, self.rpc_board_info_reply)
                self.transport.step(exiting=False)
                # Check that protocol matches
                if not(self.valid_firmware_protocol == self.board_info['protocol_version']):
                    protocol_msg = """
                    ----------------
                    Firmware protocol mismatch on {0}.
                    Protocol on board is {1}.
                    Valid protocol is: {2}.
                    Disabling device.
                    Please upgrade the firmware and/or version of Stretch Body.
                    ----------------
                    """.format(self.name, self.board_info['protocol_version'], self.valid_firmware_protocol)
                    self.logger.warn(textwrap.dedent(protocol_msg))
                    self.hw_valid=False
                    self.transport.stop()

            if self.hw_valid:
                self.push_command()
                self.pull_status()
                return True
            return False



    def stop(self):
        if not self.hw_valid:
            return
        with self.lock:
            self.hw_valid = False
            self.push_command(exiting=True)
            self.transport.stop()

    def set_D2(self,on):#0 or 1
        """
        Set the Digital Out 2 on the Wacc expansion header
        """
        self._command['d2']=bool(on)
        self._dirty_command = True

    def set_D3(self,on): #0 or 1
        """
        Set the Digital Out 3 on the Wacc expansion header
        """
        self._command['d3']=bool(on)
        self._dirty_command = True

    def pull_status(self,exiting=False):
        if not self.hw_valid:
            return
        with self.lock:
            # Queue Status RPC
            self.transport.payload_out[0] = RPC_GET_WACC_STATUS
            sidx = 1
            self.transport.queue_rpc(sidx, self.rpc_status_reply)
            self.transport.step(exiting=exiting)

    def push_command(self,exiting=False):
        if not self.hw_valid:
            return
        with self.lock:
            if self._dirty_config:
                self.transport.payload_out[0] = RPC_SET_WACC_CONFIG
                sidx = self.pack_config(self.transport.payload_out, 1)
                self.transport.queue_rpc2(sidx, self.rpc_config_reply)
                self._dirty_config=False

            if self._dirty_command:
                self.transport.payload_out[0] = RPC_SET_WACC_COMMAND
                sidx = self.pack_command(self.transport.payload_out, 1)
                self.transport.queue_rpc2(sidx, self.rpc_command_reply)
                self._command['trigger'] =0
                self._dirty_command=False
            self.transport.step2(exiting=exiting)

    def pretty_print(self):
        print('------------------------------')
        print('Ax (m/s^2)',self.status['ax'])
        print('Ay (m/s^2)', self.status['ay'])
        print('Az (m/s^2)', self.status['az'])
        print('A0', self.status['a0'])
        print('D0 (In)', self.status['d0'])
        print('D1 (In)', self.status['d1'])
        print('D2 (Out)', self.status['d2'])
        print('D3 (Out)', self.status['d3'])
        print('Single Tap Count', self.status['single_tap_count'])
        print('State ', self.status['state'])
        print('Debug',self.status['debug'])
        print('Timestamp', self.status['timestamp'])
        print('Board version:', self.board_info['board_version'])
        print('Firmware version:', self.board_info['firmware_version'])

    # ####################### Utility functions ####################################################
    def board_reset(self):
        with self.lock:
            self._command['trigger']=self._command['trigger']| TRIGGER_BOARD_RESET
            self._dirty_command=True

    # ################Data Packing #####################

    def unpack_board_info(self,s):
        with self.lock:
            sidx=0
            self.board_info['board_version'] = unpack_string_t(s[sidx:], 20)
            sidx += 20
            self.board_info['firmware_version'] = unpack_string_t(s[sidx:], 20)
            self.board_info['protocol_version'] = self.board_info['firmware_version'][self.board_info['firmware_version'].rfind('p'):]
            sidx += 20
            return sidx

    def unpack_status(self,s):
        with self.lock:
            sidx=0
            if self.ext_status_cb is not None:
                sidx+=self.ext_status_cb(s[sidx:])
            self.status['ax'] = unpack_float_t(s[sidx:]);sidx+=4
            self.status['ay'] = unpack_float_t(s[sidx:]);sidx+=4
            self.status['az'] = unpack_float_t(s[sidx:]);sidx+=4
            self.status['a0'] = unpack_int16_t(s[sidx:]);sidx+=2
            self.status['d0'] = unpack_uint8_t(s[sidx:]); sidx += 1
            self.status['d1'] = unpack_uint8_t(s[sidx:]); sidx += 1
            self.status['d2'] = unpack_uint8_t(s[sidx:]); sidx += 1
            self.status['d3'] = unpack_uint8_t(s[sidx:]); sidx += 1
            self.status['single_tap_count'] = unpack_uint32_t(s[sidx:]);sidx += 4
            self.status['state'] = unpack_uint32_t(s[sidx:]); sidx += 4
            self.status['timestamp'] = self.timestamp.set(unpack_uint32_t(s[sidx:]));sidx += 4
            self.status['debug'] = unpack_uint32_t(s[sidx:]);sidx += 4
            return sidx

    def pack_command(self,s,sidx):
        if self.ext_command_cb is not None:  # Pack custom data first
            sidx += self.ext_command_cb(s, sidx)
        pack_uint8_t(s, sidx, self._command['d2'])
        sidx += 1
        pack_uint8_t(s, sidx, self._command['d3'])
        sidx += 1
        pack_uint32_t(s, sidx, self._command['trigger'])
        sidx += 4
        return sidx

    def pack_config(self,s,sidx):
        with self.lock:
            pack_uint8_t(s, sidx, self.config['accel_range_g'])
            sidx += 1
            pack_float_t(s, sidx, self.config['accel_LPF'])
            sidx += 4
            pack_float_t(s, sidx, self.config['ana_LPF'])
            sidx += 4
            pack_uint8_t(s, sidx, self.config['accel_single_tap_dur'])
            sidx += 1
            pack_uint8_t(s, sidx, self.config['accel_single_tap_thresh'])
            sidx += 1
            pack_float_t(s, sidx, self.config['accel_gravity_scale'])
            sidx += 4
            return sidx

    # ################Transport Callbacks #####################
    def rpc_board_info_reply(self,reply):
        if reply[0] == RPC_REPLY_WACC_BOARD_INFO:
            self.unpack_board_info(reply[1:])
        else:
            print('Error RPC_REPLY_WACC_BOARD_INFO', reply[0])

    def rpc_command_reply(self,reply):
        if reply[0] != RPC_REPLY_WACC_COMMAND:
            print('Error RPC_REPLY_WACC_COMMAND', reply[0])

    def rpc_config_reply(self,reply):
        if reply[0] != RPC_REPLY_WACC_CONFIG:
            print('Error RPC_REPLY_WACC_CONFIG', reply[0])

    def rpc_status_reply(self,reply):
        if reply[0] == RPC_REPLY_WACC_STATUS:
            self.unpack_status(reply[1:])
        else:
            print('Error RPC_REPLY_WACC_STATUS', reply[0])







