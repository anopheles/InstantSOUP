#!/usr/bin/env python
# -*- coding: utf-8 -*-


import logging
import uuid


from construct import Container, Enum, PrefixedArray, Struct, ULInt16, ULInt8, OptionalGreedyRange, CString, Switch
from PyQt4 import QtGui, QtCore, QtNetwork


log = logging.getLogger("instantsoup")
log.setLevel(logging.DEBUG)

group_address = QtNetwork.QHostAddress("239.255.99.63")
broadcast_port = 55555
server_port = 49152

class InstantSoupData(object):

    ClientMemberShipOption = PrefixedArray(Struct("Server",
                                                  CString("ServerID"),
                                                  PrefixedArray(CString('Channels'),
                                                                ULInt8("NumChannels"))
                                                  ),
                                           ULInt8("NumServers"))

    ServerInviteOption = Struct("ServerInviteOption",
                                CString("ChannelID"),
                                PrefixedArray(CString("ClientID"),
                                              ULInt8("NumClients")))

    Option = Struct("Option",
                    Enum(ULInt8("OptionID"),
                         CLIENT_NICK_OPTION = 0x01,
                         CLIENT_MEMBERSHIP_OPTION = 0x02,
                         SERVER_OPTION = 0x10,
                         SERVER_CHANNELS_OPTION = 0x11,
                         SERVER_INVITE_OPTION = 0x12),
                    Switch("OptionData",
                           lambda ctx: ctx["OptionID"],
                           {
                                "CLIENT_NICK_OPTION" : CString('Nickname'),
                                "CLIENT_MEMBERSHIP_OPTION" : ClientMemberShipOption,
                                "SERVER_OPTION" : Struct("ServerOption", ULInt16("Port")),
                                "SERVER_CHANNELS_OPTION" : PrefixedArray(CString("Channels"), ULInt8("NumChannels")),
                                "SERVER_INVITE_OPTION" : ServerInviteOption
                           }))

    peerPDU = Struct("peerPDU",
                     CString('ID'),
                     OptionalGreedyRange(Option))


class Client(QtCore.QObject):
    new_client = QtCore.pyqtSignal() # emitted when a new client is discovered
    client_nick_change = QtCore.pyqtSignal() # emitted when a nick of a client is changed
    new_server = QtCore.pyqtSignal() # emitted when a new server is discovered

    def __init__(self, nickname="Telematik"):
        QtCore.QObject.__init__(self)
        self.nickname = nickname
        self.id = str(uuid.uuid1())
        self.setup_socket()
        self.lobby_users = {} # mapping from client.id to nickname
        self.servers = {}

        self.send_client_nick()
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._send_regular_pdu)
        self.peer_id = 0
        self.timer.start(15000)

        self.new_client.connect(self.send_client_nick)

        # Testing
        self.new_server.connect(self.receive_message_from_server) # for testing purposes

    def receive_message_from_server(self):
        for server_id, server_port in self.servers.items():
            self.client_thread = ClientThread()
            self.client_thread.request_new_command(QtNetwork.QHostAddress.LocalHost, server_port)
            self.client_thread.new_command.connect(self.handle_command)

    def _send_message_to_server(self, server, port, message):
        pass


    def handle_command(self, command):
        print "handling command", command

    def _send_regular_pdu(self):
        self.peer_id += 1
        log.debug("sending regular")

    def setup_socket(self):
        self.udp_socket = QtNetwork.QUdpSocket(self)
        self.udp_socket.bind(broadcast_port, QtNetwork.QUdpSocket.ReuseAddressHint)
        self.udp_socket.joinMulticastGroup(group_address)
        self.udp_socket.readyRead.connect(self._process_pending_datagrams)

    def send_client_nick(self):
        data = InstantSoupData.peerPDU.build(Container(ID=self.id,
                                                       Option=[Container(OptionID="CLIENT_NICK_OPTION", OptionData=self.nickname)])
                                            )
        self._send_datagram(data)

    def _process_pending_datagrams(self):
        while self.udp_socket.hasPendingDatagrams():
            datagram, host, port = self.udp_socket.readDatagram(self.udp_socket.pendingDatagramSize())
            #print self, "received datagram", datagram
            packet = InstantSoupData.peerPDU.parse(datagram)
            if packet["ID"] != self.id:
                for option in packet["Option"]:
                    if option["OptionID"] == "CLIENT_NICK_OPTION":
                        # new client found or client nick was changed
                        if self.lobby_users.has_key(packet["ID"]):
                            # user already exists
                            if self.lobby_users[packet["ID"]] != option["OptionData"]:
                                # client nick was changed
                                self.client_nick_change.emit()
                        else:
                            # add new client
                            self.new_client.emit()
                        self.lobby_users[packet["ID"]] = option["OptionData"]
                    if option["OptionID"] == "SERVER_OPTION":
                        # add new server
                        self.servers[packet["ID"]] = option["OptionData"]["Port"]
                        self.new_server.emit()
            log.debug(self)

    def _send_datagram(self, datagram):
        self.udp_socket.writeDatagram(datagram, group_address, broadcast_port)

    def __repr__(self):
        return "Client(%s, %s, lobby_users:%s, servers:%s)" % (self.nickname, self.id, self.lobby_users, self.servers)

class ClientThread(QtCore.QThread):
    """
        taken from http://doc.qt.nokia.com/4.8-snapshot/network-blockingfortuneclient.html
    """
    new_command = QtCore.pyqtSignal(str)
    error = QtCore.pyqtSignal(int, str)

    def __init__(self, parent=None):
        super(ClientThread, self).__init__(parent)

        self.quit = False
        self.hostName = ''
        self.cond = QtCore.QWaitCondition()
        self.mutex = QtCore.QMutex()
        self.port = 0

    def __del__(self):
        self.mutex.lock()
        self.quit = True
        self.cond.wakeOne()
        self.mutex.unlock()
        self.wait()

    def request_new_command(self, host_name, port):
        locker = QtCore.QMutexLocker(self.mutex)
        self.host_name = host_name
        self.port = port
        if not self.isRunning():
            self.start()
        else:
            self.cond.wakeOne()

    def run(self):
        self.mutex.lock()
        server_name = self.host_name
        server_port = self.port
        self.mutex.unlock()

        while not self.quit:
            Timeout = 5 * 1000

            socket = QtNetwork.QTcpSocket()
            socket.connectToHost(server_name, server_port)

            if not socket.waitForConnected(Timeout):
                self.error.emit(socket.error(), socket.errorString())
                return

            while socket.bytesAvailable() < 2:
                if not socket.waitForReadyRead(Timeout):
                    self.error.emit(socket.error(), socket.errorString())
                    return

            instr = QtCore.QDataStream(socket)
            instr.setVersion(QtCore.QDataStream.Qt_4_0)
            blockSize = instr.readUInt32()

            while socket.bytesAvailable() < blockSize:
                if not socket.waitForReadyRead(Timeout):
                    self.error.emit(socket.error(), socket.errorString())
                    return

            self.mutex.lock()
            message = instr.readString()

            try:
                # Python v3.
                fortune = str(message, encoding='ascii')
            except TypeError:
                # Python v2.
                pass

            self.new_command.emit(message)

            self.cond.wait(self.mutex)
            server_name = self.host_name
            server_port = self.port
            self.mutex.unlock()


class Server(QtCore.QObject):
    port = server_port

    def __init__(self):
        QtCore.QObject.__init__(self)
        self.id = str(uuid.uuid1())
        self.setup_socket()
        self.tcp_server = QtNetwork.QTcpServer(self)
        self.port = Server.port+600
        Server.port += 1
        self.send_server_option()

        if not self.tcp_server.listen(QtNetwork.QHostAddress.Any, self.port):
            log.error("Unable to start the server: %s." % self.tcp_server.errorString())

        log.debug("Server is running with address %s and port %s" % (self.tcp_server.serverAddress().toString(), self.tcp_server.serverPort()))
        self.tcp_server.newConnection.connect(self._handle_connection)


    def _handle_connection(self):
        block = QtCore.QByteArray()
        out = QtCore.QDataStream(block, QtCore.QIODevice.WriteOnly)
        out.setVersion(QtCore.QDataStream.Qt_4_0)
        out.writeUInt32(0)
        message = "SAY Hello this is a simple server message"

        try:
            # Python v3.
            message = bytes(fortune, encoding='ascii')
        except:
            # Python v2.
            pass

        out.writeString(message)
        out.device().seek(0)
        out.writeUInt32(block.size()-4)

        clientConnection = self.tcp_server.nextPendingConnection()
        clientConnection.disconnected.connect(clientConnection.deleteLater)

        clientConnection.write(block)
        clientConnection.disconnectFromHost()


    def send_server_option(self):
        data = InstantSoupData.peerPDU.build(Container(ID=self.id,
                                                       Option=[Container(OptionID="SERVER_OPTION", OptionData=Container(Port=self.port))])
                                            )
        self._send_datagram(data)

    def _send_datagram(self, datagram):
        self.udp_socket.writeDatagram(datagram, group_address, broadcast_port)

    def _process_pending_datagrams(self):
        while self.udp_socket.hasPendingDatagrams():
            datagram, host, port = self.udp_socket.readDatagram(self.udp_socket.pendingDatagramSize())
            #print self, "received datagram", datagram
            packet = InstantSoupData.peerPDU.parse(datagram)
            if packet["ID"] != self.id:
                for option in packet["Option"]:
                    if option["OptionID"] == "CLIENT_NICK_OPTION":
                        # new client found or client nick was changed
                        # TODO only send server option when a new client is seen
                        self.send_server_option()

    def setup_socket(self):
        self.udp_socket = QtNetwork.QUdpSocket(self)
        self.udp_socket.bind(broadcast_port, QtNetwork.QUdpSocket.ReuseAddressHint)
        self.udp_socket.joinMulticastGroup(group_address)
        self.udp_socket.readyRead.connect(self._process_pending_datagrams)