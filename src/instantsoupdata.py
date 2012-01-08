#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import uuid
import time

from construct import Container, Enum, PrefixedArray, Struct, ULInt32, ULInt16, ULInt8, OptionalGreedyRange, PascalString, CString, Switch
from PyQt4 import QtCore, QtNetwork
from functools import partial
from threading import Timer

log = logging.getLogger("instantsoup")
log.setLevel(logging.DEBUG)

group_address = QtNetwork.QHostAddress("239.255.99.63")
broadcast_port = 55555
server_start_port = 49152

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
                                "SERVER_CHANNELS_OPTION" : Struct("ServerChannelsOption", CString("Channels"), ULInt8("NumChannels")),
                                "SERVER_INVITE_OPTION" : ServerInviteOption
                           }))

    peerPDU = Struct("peerPDU",
                     CString('ID'),
                     OptionalGreedyRange(Option))

    command = PascalString("command", length_field=ULInt32("length"))


class Client(QtCore.QObject):

    # emitted when a new client is discovered
    new_client = QtCore.pyqtSignal()

    # emitted when a nick of a client is changed
    client_nick_change = QtCore.pyqtSignal()

    # emitted when a new server is discovered
    new_server = QtCore.pyqtSignal()

    # emitted a client received a message from a server, for testing purposes
    message_received = QtCore.pyqtSignal(str)

    def __init__(self, nickname="Telematik", parent=None):
        QtCore.QObject.__init__(self, parent)
        self.nickname = nickname
        self.id = str(uuid.uuid1())
        self.setup_socket()

        # mapping from client.id to nickname
        self.lobby_users = {}

        # mapping from (server.id, channel) to a tuple containing (address,
        # port, tcp_socket)
        self.servers = {}

        self.send_client_nick()

        # setup the regular_pdu_timer for the regular pdu
        self.regular_pdu_timer = QtCore.QTimer()
        self.regular_pdu_timer.timeout.connect(self.send_regular_pdu)
        self.regular_pdu_timer.start(15000)

        self.peer_id = 0

    def join_channel(self, channel_name, server_id):
        self.send_command_to_server("JOIN\x00%s" % channel_name, server_id)

    def say(self, text, channel_name, server_id):
        self.send_command_to_server("SAY\x00%s" % text)

    def standby(self, peer_id, channel_name, server_id):
        self.send_command_to_server("STANDBY\x00%s" % peer_id)

    def exit(self, channel_name, server_id):
        self.send_command_to_server("EXIT")

    def read_tcp_socket(self, socket):
        response = socket.readAll()
        self.message_received.emit(str(response))

    def send_command_to_server(self, command, server_id="1", channel=None):
        if (server_id, channel) not in self.servers:
            log.error("trying to connect to server %s which doesn't exist or hasn't yet been recognized" % server_id)
            return

        # we are already connected!
        (_, _, socket) = self.servers[(server_id, channel)]
        socket.write(InstantSoupData.command.build(command))
        socket.waitForBytesWritten(1000)

    def send_regular_pdu(self):
        self.peer_id += 1
        log.debug("sending regular id:" + str(self.peer_id))

    def setup_socket(self):
        self.udp_socket = QtNetwork.QUdpSocket(self)
        self.udp_socket.bind(broadcast_port, QtNetwork.QUdpSocket.ReuseAddressHint)
        self.udp_socket.joinMulticastGroup(group_address)
        self.udp_socket.readyRead.connect(self.process_pending_datagrams)

    def send_client_nick(self):
        data = InstantSoupData.peerPDU.build(Container(ID=self.id,
                                                       Option=[Container(OptionID="CLIENT_NICK_OPTION", OptionData=self.nickname)])
                                            )
        self._send_datagram(data)

    def process_pending_datagrams(self):
        while self.udp_socket.hasPendingDatagrams():
            data, address, port = self.udp_socket.readDatagram(self.udp_socket.pendingDatagramSize())
            packet = InstantSoupData.peerPDU.parse(data)
            for option in packet["Option"]:
                if option["OptionID"] == "CLIENT_NICK_OPTION":
                    # new client found or client nick was changed
                    if packet["ID"] in self.lobby_users:
                        # user already exists
                        if self.lobby_users[packet["ID"]] != option["OptionData"]:
                            # client nick was changed
                            self.client_nick_change.emit()
                    else:
                        # add new client
                        self.new_client.emit()
                    self.lobby_users[packet["ID"]] = option["OptionData"]
                elif option["OptionID"] == "SERVER_OPTION":
                    # add new server
                    port = option["OptionData"]["Port"]

                    try:
                        socket = self.create_new_socket(address, port)
                        self.servers[(packet["ID"], None)] = (address, port, socket)

                        # signal: we have a new server!
                        self.new_server.emit()
                    except Exception as error:
                        print error
                elif option["OptionID"] == "SERVER_CHANNELS_OPTION":
                    # add new server
                    channel = option["OptionData"]["Channels"]

                    try:
                        (address, port, _) = self.servers[(packet["ID"], None)]
                        socket = self.create_new_socket(address, port)
                        self.servers[(packet["ID"], channel)] = (address, port, socket)

                        # signal: we have a new server!
                        self.new_server.emit()
                    except Exception as error:
                        print error

            log.debug(self)

    def create_new_socket(self, address, port):
        socket = QtNetwork.QTcpSocket()

        # we have a port, connect!
        socket.connectToHost(address, port)

        if not socket.waitForConnected(100):
            raise Exception('no connection for address %s:%s' % (address.toString(), port))

        # connect with processing function
        socket.readyRead.connect(partial(self.read_tcp_socket, socket))

        return socket

    def _send_datagram(self, datagram):
        self.udp_socket.writeDatagram(datagram, group_address, broadcast_port)

    def __repr__(self):
        return "Client(%s, %s, lobby_users:%s, servers:%s)" % (self.nickname, self.id, self.lobby_users, self.servers)


class Server(QtCore.QObject):
    debug_output = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        global server_start_port

        QtCore.QObject.__init__(self, parent)

        # Create a channel with a unique id
        self.id = str(uuid.uuid1())

        self.port = server_start_port
        server_start_port += 1

        self.setup_socket()
        self.tcp_server = QtNetwork.QTcpServer(self)

        # mapping from channel_id to a list of (client_id, tcp_socket)
        self.channels = {}
        self.lobby_users = {}

        if not self.tcp_server.listen(QtNetwork.QHostAddress.Any, self.port):
            log.error("Unable to start the server: %s." % self.tcp_server.errorString())

        # Hint: IP: 0.0.0.0 means ANY
        log.debug("Server is running with address %s and port %s" % (self.tcp_server.serverAddress().toString(), self.tcp_server.serverPort()))
        self.tcp_server.newConnection.connect(self.handle_connection)

        self.pdu_number = -1

        # setup the regular_pdu_timer for the regular pdu
        self.regular_pdu_timer = QtCore.QTimer()
        self.regular_pdu_timer.timeout.connect(self.send_regular_pdu)
        self.regular_pdu_timer.start(15000)

    def handle_connection(self):
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
        self.handle_data(data, clientConnection)
        clientConnection.disconnected.connect(clientConnection.deleteLater)

    def search_channel(self, socket):
        for channel_name, iterable in self.channels.items():
                for client_id, client_socket in iterable:
                    if client_socket == socket:
                        return client_id, channel_name
        return []

    def handle_data(self, command, socket):
        address = socket.peerAddress()
        port = socket.peerPort()
        log.debug(("adress and port of client", address.toString(), port))

        data = InstantSoupData.command.parse(command)
        if data.startswith("SAY"):

            # send message to all connected peers in channel
            message = " ".join(data.split("\x00")[1:])
            try:
                author_id, channel_name = self.search_channel(socket)
                for (client_id, socket) in self.channels[channel_name]:
                    socket.write(InstantSoupData.command.build("SAY\x00%s\x00%s\x00" % (author_id, message)))
                    socket.waitForBytesWritten(3000)
            except ValueError:
                log.error("socket was not found, make sure the socket is associated with a channel. use the join command")

        elif data.startswith("JOIN"):
            channel_name = data.split("\x00")[1]
            log.debug(("user ", self.lobby_users[address], "is opening/joining a channel with name", channel_name))
            try:
                self.channels[channel_name].add((self.lobby_users[address][0], socket))
                log.debug("channel already exists")
            except KeyError:
                log.debug("creating channel %s" % channel_name)
                self.channels[channel_name] = set()
                self.channels[channel_name].add((self.lobby_users[address][0], socket))
                self.send_server_channel_option()

        elif data.startswith("EXIT"):
            pass

        return data

    def send_regular_pdu(self):

        # simply send all data
        self.send_server_option()

        # sent the option with every fourth pdu (see rfc)
        if self.pdu_number % 4 == 0:
            self.send_server_channel_option()

    def send_server_option(self):

        # define the data to send & send
        data = InstantSoupData.peerPDU.build(Container(ID=self.id,
                                                       Option=[Container(OptionID="SERVER_OPTION", OptionData=Container(Port=self.port))])
                                            )
        self.send_datagram(data)

        log.debug('PDU: SERVER_OPTION - ID: %i - SENT' % self.pdu_number)

        # increment the number of sent packets
        self.pdu_number += 1

    def send_server_channel_option(self):

        number_of_channels = len(self.channels)

        if number_of_channels > 0:
            list_of_channel = str(self.channels.keys()[0])

            # define the data to send & send
            data = InstantSoupData.peerPDU.build(Container(ID=self.id,
                                                           Option=[Container(OptionID="SERVER_CHANNELS_OPTION",
                                                                             OptionData=Container(Channels=list_of_channel,
                                                                                                  NumChannels=number_of_channels))])
                                                )
            self.send_datagram(data)

            log.debug('PDU: SERVER_CHANNELS_OPTION - ID: %i - SENT' % self.pdu_number)

    def send_datagram(self, datagram):
        self.udp_socket.writeDatagram(datagram, group_address, broadcast_port)

    def _process_pending_datagrams(self):

        # loop through all datagrams which are not send yet
        while self.udp_socket.hasPendingDatagrams():
            datagram, address, port = self.udp_socket.readDatagram(self.udp_socket.pendingDatagramSize())
            packet = InstantSoupData.peerPDU.parse(datagram)
            if packet["ID"] != self.id:
                for option in packet["Option"]:
                    if option["OptionID"] == "CLIENT_NICK_OPTION":

                        # new client found or client nick was changed
                        if address not in self.lobby_users:
                            self.lobby_users[address] = (packet["ID"], option["OptionData"])
                            self.send_server_option()

    def setup_socket(self):
        self.udp_socket = QtNetwork.QUdpSocket(self)
        self.udp_socket.bind(broadcast_port, QtNetwork.QUdpSocket.ReuseAddressHint)
        self.udp_socket.joinMulticastGroup(group_address)
        self.udp_socket.readyRead.connect(self._process_pending_datagrams)