#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import uuid

from construct import Container, Enum, PrefixedArray, Struct, ULInt32
from construct import ULInt16, ULInt8, OptionalGreedyRange, PascalString
from construct import CString, Switch, GreedyRange
from PyQt4 import QtCore, QtNetwork
from functools import partial

log = logging.getLogger("instantsoup")
log.setLevel(logging.DEBUG)

group_address = QtNetwork.QHostAddress("239.255.99.63")
broadcast_port = 55555
server_start_port = 49190


class InstantSoupData(object):

    opt_client_nick = CString('nickname')

    # common
    server = Struct("server",
                 CString("server_id"),
                 PrefixedArray(CString('channels'),
                     ULInt8("num_channels")
                 )
             )

    # structures from rfc
    opt_client_membership = PrefixedArray(server,
                                 ULInt8("num_servers")
                             )

    opt_server_invite = Struct("opt_server_invite",
                             CString("channel_id"),
                             PrefixedArray(CString("client_id"),
                                 ULInt8("num_clients")
                             )
                         )

    opt_server_channel = Struct("opt_server_channel",
                             ULInt8("num_channels"),
                             GreedyRange(CString("channels"))
                         )

    opt_server = Struct("opt_server",
                     ULInt16("port")
                 )

    option = Struct("option",
                 Enum(ULInt8("option_id"),
                     CLIENT_NICK_OPTION=0x01,
                     CLIENT_MEMBERSHIP_OPTION=0x02,
                     SERVER_OPTION=0x10,
                     SERVER_CHANNELS_OPTION=0x11,
                     SERVER_INVITE_OPTION=0x12
                 ),
                 Switch("option_data",
                     lambda ctx: ctx["option_id"],
                     {
                     "CLIENT_NICK_OPTION": opt_client_nick,
                     "CLIENT_MEMBERSHIP_OPTION": opt_client_membership,
                     "SERVER_OPTION": opt_server,
                     "SERVER_CHANNELS_OPTION": opt_server_channel,
                     "SERVER_INVITE_OPTION": opt_server_invite
                     }
                 )
             )

    peer_pdu = Struct("peer_pdu",
                   CString('id'),
                   OptionalGreedyRange(option)
               )

    command = PascalString("command", length_field=ULInt32("length"))


class Client(QtCore.QObject):

    # emitted when a new client is discovered
    new_client = QtCore.pyqtSignal()

    # emitted when a nick of a client is changed
    client_nick_change = QtCore.pyqtSignal()

    # emitted when a new server is discovered
    new_server = QtCore.pyqtSignal(str)

    # emitted when a client received a message from a server, for testing purposes
    message_received = QtCore.pyqtSignal(str)

    def __init__(self, nickname="Telematik", parent=None):
        QtCore.QObject.__init__(self, parent)

        self.id = str(uuid.uuid1())
        self.nickname = nickname
        self.pdu_number = 0

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

    def join_channel(self, channel_name, server_id):
        self.send_command_to_server("JOIN\x00%s" % channel_name, server_id)

    def say(self, text, channel_name, server_id):
        self.send_command_to_server("SAY\x00%s" % text, channel_name, server_id)

    def standby(self, peer_id, channel_name, server_id):
        self.send_command_to_server("STANDBY\x00%s" % peer_id, channel_name, server_id)

    def exit(self, channel_name, server_id):
        self.send_command_to_server("EXIT", channel_name, server_id)

    def read_tcp_socket(self, socket):
        data = socket.readAll()
        peer_pdu = InstantSoupData.peer_pdu.parse(data)
        uid = peer_pdu["id"]
        for option in peer_pdu["option"]:
            if option["option_id"] == "SERVER_INVITE_OPTION":
                #TODO handle server invite option here
                pass

    def send_command_to_server(self, command, server_id, channel=None):
        if (server_id, channel) not in self.servers:
            print "server id", server_id
            log.error("trying to connect to server %s which doesn't exist or hasn't yet been recognized" % server_id)
            return

        # we are already connected!
        (_, _, socket) = self.servers[(server_id, channel)]
        socket.write(InstantSoupData.command.build(command))
        socket.waitForBytesWritten(1000)

    def send_regular_pdu(self):

        # send nickname
        self.send_client_nick()

        self.pdu_number += 1

    def setup_socket(self):
        self.udp_socket = QtNetwork.QUdpSocket(self)
        self.udp_socket.bind(broadcast_port,
            QtNetwork.QUdpSocket.ReuseAddressHint)
        self.udp_socket.joinMulticastGroup(group_address)
        self.udp_socket.readyRead.connect(self.process_pending_datagrams)

    def send_client_nick(self):

        # define the data to send & send
        option_data = self.nickname

        option = Container(option_id="CLIENT_NICK_OPTION",
                     option_data=option_data
                 )

        pdu = Container(id=self.id,
                  option=[option]
              )

        data = InstantSoupData.peer_pdu.build(pdu)
        self._send_datagram(data)

        log.debug('PDU: CLIENT_NICK_OPTION - ID: %i - SENT' % self.pdu_number)

    def process_pending_datagrams(self):
        maxlen = self.udp_socket.pendingDatagramSize()
        while self.udp_socket.hasPendingDatagrams():
            data, address, port = self.udp_socket.readDatagram(maxlen)
            packet = InstantSoupData.peer_pdu.parse(data)
            uid = packet["id"]
            for option in packet["option"]:

                if option["option_id"] == "CLIENT_NICK_OPTION":

                    # new client found or client nick was changed
                    if uid in self.lobby_users:
                        # user already exists
                        if self.lobby_users[uid] != option["option_data"]:
                            # client nick was changed
                            self.client_nick_change.emit()
                    else:
                        # add new client
                        self.lobby_users[uid] = option["option_data"]
                        self.new_client.emit()
                elif option["option_id"] == "SERVER_OPTION":
                    if (uid, None) not in self.servers:
                        # add new server
                        port = option["option_data"]["port"]

                        try:
                            socket = self.create_new_socket(address, port)
                            self.servers[(uid, None)] = (address, port, socket)
                            # signal: we have a new server!
                            self.new_server.emit(uid)
                        except Exception as error:
                            print error
                elif option["option_id"] == "SERVER_CHANNELS_OPTION":
                    channels = option["option_data"]["channels"]
                    for channel in channels:
                        if (uid, channel) not in self.servers:
                            try:
                                (address, port, _) = self.servers[(uid, None)]
                                socket = self.create_new_socket(address, port)
                                self.servers[(uid, channel)] = (address,
                                    port,
                                    socket
                                )
                                # signal: we have a new server!
                                self.new_server.emit(uid)
                            except Exception as error:
                                print error

    def create_new_socket(self, address, port):
        socket = QtNetwork.QTcpSocket()

        # we have a port, connect!
        socket.connectToHost(address, port)

        if not socket.waitForConnected(100):
            raise Exception('no connection for address %s:%s' %
                      (address.toString(), port))

        # connect with processing function
        socket.readyRead.connect(partial(self.read_tcp_socket, socket))

        return socket

    def _send_datagram(self, datagram):
        self.udp_socket.writeDatagram(datagram, group_address, broadcast_port)

    def __repr__(self):
        return "Client(%s, %s, lobby_users:%s, servers:%s)" % (self.nickname,
            self.id,
            self.lobby_users,
            self.servers)


class Server(QtCore.QObject):
    debug_output = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        global server_start_port

        QtCore.QObject.__init__(self, parent)

        # Create a channel with a unique id
        self.id = str(uuid.uuid1())
        self.port = server_start_port
        self.pdu_number = 0
        server_start_port += 1

        self.setup_socket()
        self.tcp_server = QtNetwork.QTcpServer(self)

        # mapping from channel_id to a list of (client_id, tcp_socket)
        self.channels = {}

        # mapping from address to a list of (client_id, nickname)
        self.lobby_users = {}

        if not self.tcp_server.listen(QtNetwork.QHostAddress.Any, self.port):
            log.error("Unable to start the server: %s." %
                self.tcp_server.errorString())

        # Hint: IP: 0.0.0.0 means ANY
        address = self.tcp_server.serverAddress().toString()
        port = self.tcp_server.serverPort()
        log.debug("Server is running with address %s and port %s" % (address,
            port))

        # do something, when we are connected
        self.tcp_server.newConnection.connect(self.handle_connection)

        # setup the regular_pdu_timer for the regular pdu
        self.regular_pdu_timer = QtCore.QTimer()
        self.regular_pdu_timer.timeout.connect(self.send_regular_pdu)
        self.regular_pdu_timer.start(15000)

    def handle_connection(self):
        client_connection = self.tcp_server.nextPendingConnection()
        client_connection.disconnected.connect(client_connection.deleteLater)

        if not client_connection.waitForConnected(1000):
            log.error((client_connection.error(),
               client_connection.errorString()))
            return

        # if the connection is ready, read from socket
        client_connection.readyRead.connect(partial(self.read_incoming_socket,
            client_connection))
        client_connection.waitForReadyRead(1000)

    def read_incoming_socket(self, client_connection):
        data = str(client_connection.readAll())
        client_connection.flush()
        self.handle_data(data, client_connection)
        client_connection.disconnected.connect(client_connection.deleteLater)

    def search_channel(self, socket):
        for channel_name, iterable in self.channels.items():
                for client_id, client_socket in iterable:
                    if client_socket == socket:
                        return client_id, channel_name
        return []

    def handle_data(self, command, socket):
        address = socket.peerAddress()
        port = socket.peerPort()
        log.debug(("address and port of client", address.toString(), port))

        data = InstantSoupData.command.parse(command)
        if data.startswith("SAY"):
            # send message to all connected peers in channel
            message = " ".join(data.split("\x00")[1:])

            try:
                author_id, channel_name = self.search_channel(socket)
                for (_, socket) in self.channels[channel_name]:
                    command = "SAY\x00%s\x00%s\x00" % (author_id, message)
                    data = InstantSoupData.command.build(command)
                    socket.write(data)
                    socket.waitForBytesWritten(3000)
            except ValueError:
                log.error("socket was not found, make sure the socket is" +
                    " associated with a channel. use the join command")

        elif data.startswith("JOIN"):
            channel_name = data.split("\x00")[1]
            log.debug("user %s is opening/joining a channel with name %s" % (self.lobby_users[address], channel_name))
            try:
                self.channels[channel_name].add((self.lobby_users[address][0], socket))
                log.debug("channel already exists")
            except KeyError:
                private = channel_name.startswith("@")
                log.debug("creating channel %s" % channel_name)
                self.channels[channel_name] = set()
                self.channels[channel_name].add((self.lobby_users[address][0], socket))
                if not private:
                    self.send_server_channel_option()
                else:
                    self.send_server_invite_option([self.lobby_users[address][0]], channel_name)

        elif data.startswith("EXIT"):
            pass

        return data

    def send_server_invite_option(self, invite_client_ids, channel_id):
        # for each client_id find the socket on which to send the server_invite option
        for invite_client_id in invite_client_ids:
            for channel_id, client_sockets in self.channels.items():
                for (client_id, socket) in client_sockets:
                    if invite_client_id == client_id:
                        option = Container(option_id="SERVER_INVITE_OPTION",
                                           option_data = Container(channel_id=channel_id, client_id=invite_client_ids))
                        pdu = Container(id=self.id, option=[option])
                        socket.write(InstantSoupData.peer_pdu.build(pdu))
                        socket.waitForBytesWritten()
        log.debug('PDU: SERVER_INVITE_OPTION - id: %i - SENT' % self.pdu_number)

    def send_regular_pdu(self):

        # simply send all data
        self.send_server_option()

        # sent the option with every fourth pdu (see rfc)
        if self.pdu_number % 4 == 0:
            self.send_server_channel_option()

    def send_server_option(self):

        # define the data to send & send
        option_data = Container(port=self.port)

        option = Container(option_id="SERVER_OPTION",
                   option_data=option_data)

        pdu = Container(id=self.id,
                option=[option])

        data = InstantSoupData.peer_pdu.build(pdu)
        self.send_datagram(data)

        log.debug('PDU: SERVER_OPTION - id: %i - SENT' % self.pdu_number)

        # increment the number of sent packets
        self.pdu_number += 1

    def send_server_channel_option(self):

        number_of_channels = len(self.channels)

        if number_of_channels > 0:

            # define the data to send & send
            list_of_channel = self.channels.keys()

            option_data = Container(num_channels=number_of_channels,
                            channels=list_of_channel)

            option = Container(option_id="SERVER_CHANNELS_OPTION",
                       option_data=option_data)

            pdu = Container(id=self.id,
                    option=[option])

            data = InstantSoupData.peer_pdu.build(pdu)
            self.send_datagram(data)

            log.debug('PDU: SERVER_CHANNELS_OPTION - id: %i - SENT' %
                      self.pdu_number)

    def send_datagram(self, datagram):
        self.udp_socket.writeDatagram(datagram, group_address, broadcast_port)

    def _process_pending_datagrams(self):
        maxlen = self.udp_socket.pendingDatagramSize()

        # loop through all datagrams which are not send yet
        while self.udp_socket.hasPendingDatagrams():
            (datagram, address, _) = self.udp_socket.readDatagram(maxlen)
            packet = InstantSoupData.peer_pdu.parse(datagram)
            uid = packet['id']

            if uid != self.id:
                for option in packet["option"]:
                    if option["option_id"] == "CLIENT_NICK_OPTION":

                        # new client found or client nick was changed
                        if address not in self.lobby_users:
                            self.lobby_users[address] = (uid, option["option_data"])
                            self.send_server_option()

    def setup_socket(self):
        self.udp_socket = QtNetwork.QUdpSocket(self)
        self.udp_socket.bind(broadcast_port,
            QtNetwork.QUdpSocket.ReuseAddressHint)
        self.udp_socket.joinMulticastGroup(group_address)
        self.udp_socket.readyRead.connect(self._process_pending_datagrams)
