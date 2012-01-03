#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import uuid

from construct import Container, Enum, PrefixedArray, Struct, ULInt32, ULInt16, ULInt8, OptionalGreedyRange, PascalString, CString, Switch
from PyQt4 import QtCore, QtNetwork
from functools import partial

log = logging.getLogger("instantsoup")
log.setLevel(logging.DEBUG)

group_address = QtNetwork.QHostAddress("239.255.99.63")
broadcast_port = 55555
server_port = 49172

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

    command = PascalString("command", length_field=ULInt32("length"))


class Client(QtCore.QObject):
    new_client = QtCore.pyqtSignal() # emitted when a new client is discovered
    client_nick_change = QtCore.pyqtSignal() # emitted when a nick of a client is changed
    new_server = QtCore.pyqtSignal() # emitted when a new server is discovered
    message_received = QtCore.pyqtSignal(str) # emitted a client received a message from a server, for testing purposes

    def __init__(self, nickname="Telematik", parent=None):
        QtCore.QObject.__init__(self, parent)
        self.nickname = nickname
        self.id = str(uuid.uuid1())
        self.setup_socket()
        self.lobby_users = {} # mapping from client.id to nickname
        self.servers = {} # mapping from (server.id, channel) to a tuple containing (address, port, tcp_socket)

        self.send_client_nick()
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._send_regular_pdu)
        self.peer_id = 0
        self.timer.start(15000)

        # this is actually not part of InstantSOUP specification but speeds up the discovery
        self.new_client.connect(self.send_client_nick)
        self.new_server.connect(self.send_client_nick)

    def join_channel(self, channel_name, server_id):
        self.send_command_to_server("JOIN %s" % channel_name)

    def say(self, text, channel_name, server_id):
        self.send_command_to_server("SAY %s" % text)

    def standby(self, peer_id, channel_name, server_id):
        self.send_command_to_server("STANDBY %s" % peer_id)

    def exit(self, channel_name, server_id):
        self.send_command_to_server("EXIT")

    def send_command_to_server(self, command, server_id="1", channel=None):
        try:
            (address, port, socket) = self.servers[(server_id, channel)]
            socket.connectToHost(address, port) # checking socket.state doesn't seem to work
        except KeyError:
            # get address and port from default channel
            address, port, _ = self.servers[(server_id, None)]
            socket = QtNetwork.QTcpSocket()
            socket.connectToHost(address, port)
            self.servers[(server_id, channel)] = (address, port, socket)

        if socket.waitForConnected(5000):
            socket.write(InstantSoupData.command.build(command))
            socket.waitForBytesWritten(1000)
            socket.waitForReadyRead(1000)
            response = socket.readAll()
            self.message_received.emit(str(response))
        else:
            log.error((socket.error(), socket.errorString()))

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
            datagram, address, port = self.udp_socket.readDatagram(self.udp_socket.pendingDatagramSize())
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
                        socket = QtNetwork.QTcpSocket()
                        self.servers[(packet["ID"], None)] = (address, option["OptionData"]["Port"], socket)
                        self.new_server.emit()
            log.debug(self)

    def _send_datagram(self, datagram):
        self.udp_socket.writeDatagram(datagram, group_address, broadcast_port)

    def __repr__(self):
        return "Client(%s, %s, lobby_users:%s, servers:%s)" % (self.nickname, self.id, self.lobby_users, self.servers)

class Server(QtCore.QObject):
    port = server_port
    debug_output = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        QtCore.QObject.__init__(self, parent)
        #self.id = str(uuid.uuid1())
        self.id = "1" # for testing purposes
        self.setup_socket()
        self.tcp_server = QtNetwork.QTcpServer(self)
        self.port = Server.port+1
        self.channels = {} # mapping from channel_id to a list of (client_id, tcp_socket)
        self.lobby_users = {}
        Server.port += 1
        self.send_server_option()

        if not self.tcp_server.listen(QtNetwork.QHostAddress.Any, self.port):
            log.error("Unable to start the server: %s." % self.tcp_server.errorString())

        log.debug("Server is running with address %s and port %s" % (self.tcp_server.serverAddress().toString(), self.tcp_server.serverPort()))
        self.tcp_server.newConnection.connect(self._handle_connection)


    def _handle_connection(self):
        log.debug("Server handling connection")
        clientConnection = self.tcp_server.nextPendingConnection()
        clientConnection.disconnected.connect(clientConnection.deleteLater)
        if not clientConnection.waitForConnected(1000):
            log.error((clientConnection.error(), clientConnection.errorString()))
            return
        clientConnection.readyRead.connect(partial(self.read_incoming_socket, clientConnection))
        clientConnection.waitForReadyRead(1000)

    def read_incoming_socket(self, clientConnection):
        data = str(clientConnection.readAll())
        clientConnection.flush()
        clientConnection.write(self.handle_data(data, clientConnection))
        clientConnection.waitForBytesWritten(3000)
        clientConnection.disconnected.connect(clientConnection.deleteLater)

    def handle_data(self, command, socket):
        address = socket.peerAddress()
        port = socket.peerPort()
        log.debug(("adress and port of client", address.toString(), port))
        data = InstantSoupData.command.parse(command)
        if data.startswith("SAY"):
            message = " ".join(data.split()[1:])
            return message
        elif data.startswith("JOIN"):
            channel_name = data.split()[1]
            log.debug(("user ", self.lobby_users[address], "is opening a channel with name", channel_name))
            try:
                self.channels[channel_name].add((self.lobby_users[address][0], socket))
                log.error("channel already exists")
            except KeyError:
                log.debug("creating channel %s" % channel_name)
                self.channels[channel_name] = set()
                self.channels[channel_name].add((self.lobby_users[address][0], socket))
            return channel_name
        elif data.startswith("EXIT"):
            pass
        return data

    def send_server_option(self):
        data = InstantSoupData.peerPDU.build(Container(ID=self.id,
                                                       Option=[Container(OptionID="SERVER_OPTION", OptionData=Container(Port=self.port))])
                                            )
        self._send_datagram(data)

    def _send_datagram(self, datagram):
        self.udp_socket.writeDatagram(datagram, group_address, broadcast_port)

    def _process_pending_datagrams(self):
        while self.udp_socket.hasPendingDatagrams():
            datagram, address, port = self.udp_socket.readDatagram(self.udp_socket.pendingDatagramSize())
            packet = InstantSoupData.peerPDU.parse(datagram)
            if packet["ID"] != self.id:
                for option in packet["Option"]:
                    if option["OptionID"] == "CLIENT_NICK_OPTION":
                        # new client found or client nick was changed
                        if not self.lobby_users.has_key(address):
                            self.lobby_users[address] = (packet["ID"], option["OptionData"])
                            self.send_server_option()

    def setup_socket(self):
        self.udp_socket = QtNetwork.QUdpSocket(self)
        self.udp_socket.bind(broadcast_port, QtNetwork.QUdpSocket.ReuseAddressHint)
        self.udp_socket.joinMulticastGroup(group_address)
        self.udp_socket.readyRead.connect(self._process_pending_datagrams)