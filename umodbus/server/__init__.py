try:
    import socketserver
except ImportError:
    import SocketServer as socketserver

from umodbus.exceptions import ServerDeviceFailureError, ModbusError, ServerDeviceFailureError
from umodbus.functions import create_function_from_request_pdu 
from umodbus.utils import (get_function_code_from_request_pdu,
                           pack_exception_pdu, recv_exactly,
                           unpack_mbap, pack_mbap)
from binascii import hexlify
from umodbus import log

import struct
#from types import MethodType
import numpy as np
from threading import Thread

import logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')


class RequestHandler(socketserver.BaseRequestHandler):
    """ A subclass of :class:`socketserver.BaseRequestHandler` dispatching
    incoming Modbus TCP/IP request using the server's :attr:`route_map`.

    """
    def handle(self):
        logging.debug("handle")
        try:
            while True:
                try:
                    mbap_header = recv_exactly(self.request.recv, 7)
                    remaining = self.get_meta_data(mbap_header)['length'] - 1
                    request_pdu = recv_exactly(self.request.recv, remaining)
                except ValueError:
                    return

                response_adu = self.process(mbap_header + request_pdu)
                self.respond(response_adu)
        except:
            import traceback
            log.exception('Error while handling request: {0}.'
                          .format(traceback.print_exc()))
            raise

    def process(self, request_adu):
        logging.debug("process")
        """ Process request ADU and return response.

        :param request_adu: A bytearray containing the ADU request.
        :return: A bytearray containing the response of the ADU request.
        """
        meta_data = self.get_meta_data(request_adu)
        request_pdu = self.get_request_pdu(request_adu)

        response_pdu = self.process_request(meta_data, request_pdu)
        response_adu = self.create_response_adu(meta_data, response_pdu)

        return response_adu

    def process_request(self, meta_data, request_pdu):
        """ Execute configured route based on requests meta data and request
        PDU.

        :param meta_data: A dict with meta data. It must at least contain
            key 'unit_id'.
        :param request_pdu: A bytearray containing request PDU.
        :return: A bytearry containing reponse PDU.
        """
        function = create_function_from_request_pdu(request_pdu)
        logging.debug("process request")
        results =\
            function.execute(meta_data['unit_id'], self.server)


        try:


            try:
                # ReadFunction's use results of callbacks to build response
                # PDU...
                return function.create_response_pdu(results)
            except TypeError:
                # ...other functions don't.
                return function.create_response_pdu()
        except ModbusError as e:
            function_code = get_function_code_from_request_pdu(request_pdu)
            return pack_exception_pdu(function_code, e.error_code)
        except Exception as e:
            log.exception('Could not handle request: {0}.'.format(e))
            function_code = get_function_code_from_request_pdu(request_pdu)

            return pack_exception_pdu(function_code,
                                      ServerDeviceFailureError.error_code)

    def respond(self, response_adu):
        """ Send response ADU back to client.

        :param response_adu: A bytearray containing the response of an ADU.
        """
        log.info('--> {0} - {1}.'.format(self.client_address[0],
                 hexlify(response_adu)))
        self.request.sendall(response_adu)

    def get_meta_data(self, request_adu):
        """" Extract MBAP header from request adu and return it. The dict has
        4 keys: transaction_id, protocol_id, length and unit_id.

        :param request_adu: A bytearray containing request ADU.
        :return: Dict with meta data of request.
        """
        try:
            transaction_id, protocol_id, length, unit_id = \
                unpack_mbap(request_adu[:7])
        except struct.error:
            raise ServerDeviceFailureError()

        return {
            'transaction_id': transaction_id,
            'protocol_id': protocol_id,
            'length': length,
            'unit_id': unit_id,
        }

    def get_request_pdu(self, request_adu):
        """ Extract PDU from request ADU and return it.

        :param request_adu: A bytearray containing request ADU.
        :return: An bytearray container request PDU.
        """
        return request_adu[7:]

    def create_response_adu(self, meta_data, response_pdu):
        """ Build response ADU from meta data and response PDU and return it.

        :param meta_data: A dict with meta data.
        :param request_pdu: A bytearray containing request PDU.
        :return: A bytearray containing request ADU.
        """
        response_mbap = pack_mbap(
            transaction_id=meta_data['transaction_id'],
            protocol_id=meta_data['protocol_id'],
            length=len(response_pdu) + 1,
            unit_id=meta_data['unit_id']
        )

        return response_mbap + response_pdu
READ_COILS = 1
READ_DISCRETE_INPUTS = 2
READ_HOLDING_REGISTERS = 3
READ_INPUT_REGISTERS = 4

WRITE_SINGLE_COIL = 5
WRITE_SINGLE_REGISTER = 6
WRITE_MULTIPLE_COILS = 15
WRITE_MULTIPLE_REGISTERS = 16

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass

class Server():
    def __init__(
            self, 
            port=5502, 
            host="localhost", 
            handler=RequestHandler, 
            slave_id=1):

        self.server = ThreadedTCPServer((host, port), handler)
        self.server.slave_id = slave_id
        self.server.read_coils = lambda start, length: list(np.random.randint(2, size=length))
        self.server.read_inputs = lambda start, length: list(np.random.randint(2, size=length))
        self.server.read_registers = lambda start, length: list(np.random.randint(65530, size=length))
        self.server.read_analog = lambda start, length: list(np.random.randint(65530, size=length))
        self.server.write_coil = lambda start, value: None
        self.server.write_register = lambda start, value: None
        self.server.write_multi_coil = lambda start, value: None
        self.server.write_multi_regs = lambda start, value: None
    
    def start(self):
        self.thread = Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.server.shutdown()
